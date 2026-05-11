"""System health & management API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.trades import Trade
from app.models.model_weights import ModelWeight
from app.engines.learning_engine import learning_engine
from app.engines.meta_engine import meta_engine
from app.engines.alerts import maybe_alert, _is_configured

router = APIRouter()


@router.get("/health")
async def health_check():
    """System health check."""
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "default_symbol": settings.DEFAULT_SYMBOL,
    }


@router.get("/performance")
async def get_performance(
    symbol: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get performance metrics."""
    sym = symbol or settings.DEFAULT_SYMBOL
    stats = await learning_engine.get_performance_stats(db, sym)
    meta = await meta_engine.evaluate(db, sym)

    return {
        "symbol": sym,
        "performance": stats,
        "meta": {
            "health_status": meta.health_status,
            "performance_trend": meta.performance_trend,
            "regime_stable": meta.regime_stable,
            "overfitting_risk": meta.overfitting_risk,
            "recommended_actions": meta.recommended_actions,
        },
    }


@router.get("/weights")
async def get_weights(
    db: AsyncSession = Depends(get_db),
):
    """Get current adaptive model weights."""
    weights = await learning_engine.get_weights(db)
    return {"weights": weights}


@router.get("/trades")
async def get_trade_history(
    symbol: str = Query(default=None),
    limit: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
):
    """Get trade history log."""
    sym = symbol or settings.DEFAULT_SYMBOL
    query = select(Trade).order_by(Trade.timestamp.desc()).limit(limit)
    if sym:
        query = query.where(Trade.symbol == sym)

    result = await db.execute(query)
    trades = result.scalars().all()

    return {
        "symbol": sym,
        "count": len(trades),
        "trades": [t.to_dict() for t in trades],
    }


@router.get("/activity")
async def get_recent_activity(
    limit: int = Query(default=50, ge=1, le=500),
    only_actionable: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Cross-symbol recent decision log — every analysis run shows up here."""
    query = select(Trade).order_by(Trade.timestamp.desc()).limit(limit)
    if only_actionable:
        query = query.where(Trade.direction.in_(("BUY", "SELL")))

    result = await db.execute(query)
    trades = result.scalars().all()
    return {
        "count": len(trades),
        "only_actionable": only_actionable,
        "trades": [t.to_dict() for t in trades],
    }


@router.get("/dhan-token-info")
async def dhan_token_info():
    """Decode the JWT payload of the current Dhan access token.
    Reports issued/expiry time so the UI can warn before it goes stale."""
    import base64, json, time as _t
    tok = settings.DHAN_ACCESS_TOKEN
    if not tok:
        return {"configured": False}
    try:
        payload_b64 = tok.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        iat = payload.get("iat")
        now = int(_t.time())
        seconds_left = (exp - now) if exp else None
        return {
            "configured": True,
            "client_id": payload.get("dhanClientId"),
            "issued_at": iat,
            "expires_at": exp,
            "seconds_left": seconds_left,
            "expired": seconds_left is not None and seconds_left <= 0,
            "warn": seconds_left is not None and 0 < seconds_left < 7200,  # < 2h
        }
    except Exception as e:
        return {"configured": True, "error": f"could not decode token: {e}"}


@router.post("/dhan-token")
async def dhan_token_update(payload: dict):
    """Hot-swap the Dhan access token without restarting the backend.

    Body: {"access_token": "<jwt>", "client_id": "<optional>"}
    Persists to backend/.env and re-creates the live REST client + feed
    manager in place. Returns the decoded info on success.
    """
    import re
    from pathlib import Path

    new_token = (payload or {}).get("access_token", "").strip()
    if not new_token or new_token.count(".") != 2:
        return {"ok": False, "error": "invalid JWT format"}

    new_client_id = (payload or {}).get("client_id") or settings.DHAN_CLIENT_ID
    if not new_client_id:
        return {"ok": False, "error": "missing client_id"}

    # 1. Persist to backend/.env (replacing existing keys, preserving order/comments)
    env_path = Path(__file__).resolve().parents[3] / ".env"
    try:
        content = env_path.read_text() if env_path.exists() else ""
        for key, value in (("DHAN_ACCESS_TOKEN", new_token), ("DHAN_CLIENT_ID", str(new_client_id))):
            pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
            if pat.search(content):
                content = pat.sub(f"{key}={value}", content)
            else:
                if content and not content.endswith("\n"):
                    content += "\n"
                content += f"{key}={value}\n"
        env_path.write_text(content)
    except Exception as e:
        return {"ok": False, "error": f"failed to write .env: {e}"}

    # 2. Update in-memory settings
    settings.DHAN_ACCESS_TOKEN = new_token
    settings.DHAN_CLIENT_ID = str(new_client_id)

    # 3. Hot-swap REST client on data_engine
    from app.engines.data_engine import data_engine
    data_engine.dhan = data_engine._init_dhan()

    # 4. Reset the live tick feed manager (forces reconnect with new creds)
    try:
        from app.engines.dhan_feed import get_feed_manager
        mgr = get_feed_manager()
        if mgr._feed:
            try:
                if mgr._feed.ws:
                    await mgr._feed.ws.close()
            except Exception:
                pass
        mgr._feed = None
        mgr._client = mgr._make_resolver()  # rebuild with fresh creds
    except Exception as e:
        logger_ = __import__("logging").getLogger(__name__)
        logger_.debug(f"feed reset on token rotation: {e}")

    return {"ok": True, "info": await dhan_token_info()}


@router.post("/alert-test")
async def alert_test():
    """Send a synthetic alert through every configured channel — used to
    verify Telegram bot token / chat ID / webhook URL without waiting for a
    real signal. Bypasses dedup."""
    from app.engines.alerts import _LAST_SENT
    if not _is_configured():
        return {
            "configured": False,
            "message": "No alert channel is configured. Set TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID or ALERT_WEBHOOK_URL in .env.",
        }
    fake = {
        "symbol": "NSE:NIFTY50-INDEX",
        "timeframe": "1h",
        "current_price": 24017.6,
        "decision": {
            "direction": "BUY",
            "entry_price": 24017.6,
            "stop_loss": 23890.0,
            "take_profit": 24260.0,
            "confidence": 0.78,
            "risk_reward": 2.4,
            "reasons": ["TEST", "ignore-me"],
        },
        "context": {"phase": "TREND", "regime": "TRENDING", "zone": "DISCOUNT"},
    }
    # Bypass dedup
    _LAST_SENT.pop(("NSE:NIFTY50-INDEX", "1h", "BUY"), None)
    result = await maybe_alert(fake)
    return {"configured": True, "result": result}


@router.get("/open-positions")
async def get_open_positions(
    db: AsyncSession = Depends(get_db),
):
    """All currently PENDING BUY/SELL trades — the paper-trading book.
    Each row is enriched with current price + unrealized P&L."""
    from sqlalchemy import and_
    result = await db.execute(
        select(Trade)
        .where(and_(Trade.outcome == "PENDING", Trade.direction.in_(("BUY", "SELL"))))
        .order_by(Trade.timestamp.desc())
    )
    trades = result.scalars().all()
    return {"count": len(trades), "trades": [_enrich_trade(t) for t in trades]}


@router.get("/paper-trades")
async def get_paper_trades(
    status: str = Query(default="all", description="all | open | closed"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Unified paper-book view: open + closed positions with full economics."""
    query = select(Trade).where(Trade.direction.in_(("BUY", "SELL")))
    s = (status or "all").lower()
    if s == "open":
        query = query.where(Trade.outcome == "PENDING")
    elif s == "closed":
        query = query.where(Trade.outcome.in_(("WIN", "LOSS", "TIMEOUT")))
    query = query.order_by(Trade.timestamp.desc()).limit(limit)
    result = await db.execute(query)
    trades = result.scalars().all()
    return {"count": len(trades), "status": s, "trades": [_enrich_trade(t) for t in trades]}


def _enrich_trade(t: Trade) -> dict:
    """Add unrealized P&L for OPEN, realized P&L% / RR for CLOSED."""
    d = t.to_dict()
    entry = t.entry_price
    sl = t.stop_loss
    direction = (t.direction or "").upper()

    if t.outcome == "PENDING" and entry:
        from app.engines.data_engine import data_engine
        df = data_engine.get_cached(t.symbol, t.timeframe)
        cur = float(df["close"].iloc[-1]) if df is not None and not df.empty else None
        if cur is not None:
            if direction == "BUY":
                upnl = cur - entry
            elif direction == "SELL":
                upnl = entry - cur
            else:
                upnl = 0.0
            risk = abs(entry - sl) if sl else None
            d.update({
                "current_price": round(cur, 2),
                "pnl_value": round(upnl, 2),
                "pnl_pct": round(upnl / entry * 100, 2) if entry else None,
                "rr_realized": round(abs(upnl) / risk, 2) if risk and risk > 0 else None,
                "is_realized": False,
            })
    elif t.outcome in ("WIN", "LOSS", "TIMEOUT") and entry and t.pnl is not None:
        d.update({
            "pnl_value": round(float(t.pnl), 2),
            "pnl_pct": round(float(t.pnl) / entry * 100, 2),
            "rr_realized": round(float(t.risk_reward), 2) if t.risk_reward else None,
            "is_realized": True,
        })
    return d


@router.get("/loop/status")
async def loop_status():
    """Status of the auto-running paper-trading loop."""
    from dataclasses import asdict
    from app.engines.paper_loop import paper_loop
    return asdict(paper_loop.status)


@router.post("/loop/start")
async def loop_start():
    """Start the paper-trading loop."""
    from app.engines.paper_loop import paper_loop
    started = await paper_loop.start()
    return {"started": started, "already_running": not started}


@router.post("/loop/stop")
async def loop_stop():
    """Stop the paper-trading loop."""
    from app.engines.paper_loop import paper_loop
    stopped = await paper_loop.stop()
    return {"stopped": stopped}


@router.post("/loop/scan-once")
async def loop_scan_once():
    """Trigger a single watchlist scan immediately, regardless of schedule.
    Useful for manual nudges and testing outside market hours."""
    from app.engines.paper_loop import paper_loop
    await paper_loop._run_one_scan()
    return {"ok": True, "status": loop_status_dict()}


def loop_status_dict():
    from dataclasses import asdict
    from app.engines.paper_loop import paper_loop
    return asdict(paper_loop.status)


@router.post("/loop/resolve-once")
async def loop_resolve_once():
    """Run the SL/TP resolver once."""
    from app.engines.paper_loop import paper_loop
    resolved = await paper_loop._resolve_pending()
    return {"resolved": resolved, "status": loop_status_dict()}


@router.get("/dna")
async def get_dna_library(
    symbol: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get DNA library."""
    from app.models.setup_dna import SetupDNA

    sym = symbol or settings.DEFAULT_SYMBOL
    result = await db.execute(
        select(SetupDNA)
        .where(SetupDNA.symbol == sym)
        .order_by(SetupDNA.reliability_score.desc())
        .limit(20)
    )
    records = result.scalars().all()

    return {
        "symbol": sym,
        "count": len(records),
        "dna_library": [r.to_dict() for r in records],
    }
