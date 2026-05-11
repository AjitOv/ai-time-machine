"""
Alerts – fires a notification (with chart screenshot) when a fresh BUY/SELL
signal passes all gates.

Channels (each optional):
  - Telegram bot: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
        Sends a candlestick chart image (entry/SL/TP overlaid) with a
        Markdown caption via sendPhoto.
  - Generic webhook: ALERT_WEBHOOK_URL (POST JSON, no image)

Dedup: same (symbol, timeframe, direction) is not re-sent within
ALERT_DEDUP_SECONDS (default 30 min). A signal flip (BUY → SELL)
re-arms instantly because the dedup key includes direction.
"""

import asyncio
import io
import logging
import time
from typing import Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_LAST_SENT: Dict[tuple, float] = {}


def _is_configured() -> bool:
    return bool(
        (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)
        or settings.ALERT_WEBHOOK_URL
    )


def _format_caption(payload: Dict) -> str:
    d = payload["decision"]
    ctx = payload.get("context", {})
    rr = d.get("risk_reward")
    rr_str = f"1 : {rr:.2f}" if isinstance(rr, (int, float)) and rr else "—"
    direction = d["direction"]
    arrow = "🟢 BUY" if direction == "BUY" else ("🔴 SELL" if direction == "SELL" else "⚪ NO_TRADE")
    lines = [
        f"*{arrow}* — {payload['symbol']} · {payload['timeframe']}",
        f"price `{payload.get('current_price', '?')}`  ·  conf `{(d.get('confidence') or 0) * 100:.0f}%`",
        f"entry `{d.get('entry_price')}`  sl `{d.get('stop_loss')}`  tp `{d.get('take_profit')}`  rr `{rr_str}`",
        f"phase `{ctx.get('phase')}`  regime `{ctx.get('regime')}`  zone `{ctx.get('zone')}`",
    ]
    reasons = d.get("reasons") or []
    if reasons:
        lines.append("reasons: " + ", ".join(str(r) for r in reasons[:5]))
    return "\n".join(lines)


def _render_chart_png(payload: Dict) -> Optional[bytes]:
    """
    Render a candlestick chart with entry/SL/TP overlays.
    Returns PNG bytes, or None if anything fails (we'd rather send a text-only
    alert than block on a rendering bug).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        import matplotlib.dates as mdates

        from app.engines.data_engine import data_engine

        symbol = payload["symbol"]
        timeframe = payload["timeframe"]
        decision = payload["decision"]

        df = data_engine.get_cached(symbol, timeframe)
        if df is None or df.empty:
            return None
        df = df.tail(60).copy()
        if len(df) < 5:
            return None

        # Build x positions and color per candle
        x = list(range(len(df)))
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        up = closes >= opens

        fig, ax = plt.subplots(figsize=(9, 5), facecolor="#0a0a14")
        ax.set_facecolor("#0a0a14")

        # Wicks
        for i in range(len(df)):
            color = "#34d399" if up[i] else "#f87171"
            ax.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.9, alpha=0.85)

        # Bodies
        body_w = 0.65
        for i in range(len(df)):
            color = "#34d399" if up[i] else "#f87171"
            top = max(opens[i], closes[i])
            bot = min(opens[i], closes[i])
            height = max(top - bot, (highs[i] - lows[i]) * 0.001)
            ax.add_patch(Rectangle(
                (i - body_w / 2, bot), body_w, height,
                facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.95,
            ))

        # Entry / SL / TP
        entry = decision.get("entry_price")
        stop = decision.get("stop_loss")
        target = decision.get("take_profit")
        right_x = len(df) - 0.5
        if entry:
            ax.axhline(entry, color="#7cf", linewidth=1.3, linestyle="--", alpha=0.95)
            ax.text(right_x, entry, f"  entry {entry:.2f}", color="#7cf",
                    fontsize=9, fontweight="bold", va="center", ha="left")
        if stop:
            ax.axhline(stop, color="#f87171", linewidth=1.2, linestyle=":", alpha=0.9)
            ax.text(right_x, stop, f"  sl {stop:.2f}", color="#f87171",
                    fontsize=9, fontweight="bold", va="center", ha="left")
        if target:
            ax.axhline(target, color="#34d399", linewidth=1.2, linestyle=":", alpha=0.9)
            ax.text(right_x, target, f"  tp {target:.2f}", color="#34d399",
                    fontsize=9, fontweight="bold", va="center", ha="left")

        # Title
        direction = decision.get("direction", "?")
        conf = decision.get("confidence") or 0
        rr = decision.get("risk_reward")
        rr_str = f"  rr 1:{rr:.2f}" if isinstance(rr, (int, float)) and rr else ""
        title = f"{symbol}  ·  {timeframe}  ·  {direction}  ·  conf {conf*100:.0f}%{rr_str}"
        ax.set_title(title, color="#e8eaf2", fontsize=12, fontweight="bold", pad=14, loc="left")

        # X axis: timestamps from index, sparse ticks
        idx = df.index
        ticks = list(range(0, len(df), max(1, len(df) // 6)))
        ax.set_xticks(ticks)
        ax.set_xticklabels(
            [idx[i].strftime("%m-%d %H:%M") for i in ticks],
            color="#8b8ea3", fontsize=8, rotation=0,
        )

        # Spines and grid
        for s in ax.spines.values():
            s.set_color("#22232c")
        ax.tick_params(colors="#8b8ea3")
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.grid(True, axis="y", linestyle=":", linewidth=0.5, alpha=0.25, color="#ffffff")
        ax.set_xlim(-1, len(df) + 7)  # extra room on the right for the entry/SL/TP labels

        # Brand strip
        fig.text(0.012, 0.02, "AI Time Machine", color="#8b8ea3", fontsize=8, alpha=0.7)
        fig.text(0.99, 0.02, "telegram alert", color="#8b8ea3", fontsize=8, alpha=0.7, ha="right")

        plt.tight_layout(pad=1.5)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, facecolor=fig.get_facecolor())
        plt.close(fig)
        return buf.getvalue()

    except Exception as e:
        logger.warning(f"Chart render failed for {payload.get('symbol')}: {e}")
        return None


async def _send_telegram_text(text: str) -> None:
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    body = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=body)
        if r.status_code >= 400:
            logger.warning(f"Telegram text alert HTTP {r.status_code}: {r.text[:200]}")


async def _send_telegram_photo(image_bytes: bytes, caption: str) -> None:
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes, "image/png")}
    data = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "caption": caption,
        "parse_mode": "Markdown",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(url, data=data, files=files)
        if r.status_code >= 400:
            logger.warning(f"Telegram photo alert HTTP {r.status_code}: {r.text[:300]}")


async def _send_webhook(payload: Dict) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(settings.ALERT_WEBHOOK_URL, json=payload)
        if r.status_code >= 400:
            logger.warning(f"Webhook alert HTTP {r.status_code}: {r.text[:200]}")


def _is_duplicate(symbol: str, timeframe: str, direction: str) -> bool:
    key = (symbol, timeframe, direction)
    last = _LAST_SENT.get(key)
    now = time.time()
    if last is not None and now - last < settings.ALERT_DEDUP_SECONDS:
        return True
    _LAST_SENT[key] = now
    return False


async def maybe_alert(payload: Dict) -> Optional[Dict]:
    """
    Fire alerts if the decision is actionable (BUY/SELL), dedup hasn't blocked,
    and at least one channel is configured.
    """
    if not _is_configured():
        return None
    decision = payload.get("decision") or {}
    direction = decision.get("direction")
    if direction not in ("BUY", "SELL"):
        return None
    symbol = payload.get("symbol", "?")
    timeframe = payload.get("timeframe", "?")
    if _is_duplicate(symbol, timeframe, direction):
        return {"sent": False, "reason": "dedup"}

    caption = _format_caption(payload)
    # Render off the event loop — matplotlib is sync.
    image_bytes = await asyncio.to_thread(_render_chart_png, payload)

    tasks = []
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        if image_bytes:
            tasks.append(_send_telegram_photo(image_bytes, caption))
        else:
            tasks.append(_send_telegram_text(caption))
    if settings.ALERT_WEBHOOK_URL:
        tasks.append(_send_webhook(payload))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [str(r) for r in results if isinstance(r, Exception)]
    if failures:
        logger.warning(f"Alert delivery had failures: {failures}")
    sent = len(tasks) - len(failures)
    logger.info(
        f"Alert sent for {symbol} {timeframe} {direction} via {sent}/{len(tasks)} channels "
        f"(image={'yes' if image_bytes else 'no'})"
    )
    return {"sent": sent > 0, "channels": sent, "failures": len(failures), "image": bool(image_bytes)}
