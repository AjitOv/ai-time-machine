"""
Auto-running paper-trading loop.

Two cooperating background tasks:
  - SCANNER: every PAPER_LOOP_SCAN_INTERVAL_SECONDS, walks the watchlist
    and triggers the full analysis pipeline. The analysis pipeline already
    logs a Trade with outcome=PENDING for every actionable BUY/SELL and
    outcome=SKIPPED for NO_TRADE — this loop just drives it on a schedule.

  - RESOLVER: every PAPER_LOOP_RESOLVE_INTERVAL_SECONDS, scans PENDING
    BUY/SELL trades and checks whether the SL or TP has been hit by any
    candle since the trade opened. First hit wins. Conservative tie-break:
    if both SL and TP are inside the same candle, assume SL fired first.

The loop is opt-in via PAPER_LOOP_ENABLED, can be toggled at runtime via
/api/v1/system/loop/toggle, and respects NSE market hours by default.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Optional

import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.engines.data_engine import data_engine
from app.engines.learning_engine import learning_engine
from app.engines.symbols import NIFTY_50, NIFTY_INDICES
from app.models.trades import Trade

logger = logging.getLogger(__name__)

# IST is UTC+5:30; NSE cash session is 09:15–15:30 IST, Mon–Fri.
_IST = timezone(timedelta(hours=5, minutes=30))
_NSE_OPEN = dtime(9, 15)
_NSE_CLOSE = dtime(15, 30)


def _is_market_hours(now_utc: Optional[datetime] = None) -> bool:
    now = (now_utc or datetime.now(timezone.utc)).astimezone(_IST)
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return _NSE_OPEN <= now.time() <= _NSE_CLOSE


def _watchlist() -> List[str]:
    raw = settings.PAPER_LOOP_WATCHLIST
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return list(NIFTY_INDICES) + list(NIFTY_50)


@dataclass
class LoopStatus:
    enabled: bool = False
    market_open: bool = False
    last_scan_at: Optional[str] = None
    last_resolve_at: Optional[str] = None
    last_scan_signals: int = 0    # actionable signals from the most recent scan
    last_scan_total: int = 0      # symbols scanned
    open_positions: int = 0
    next_scan_in: Optional[int] = None
    next_resolve_in: Optional[int] = None
    errors_in_a_row: int = 0
    started_at: Optional[str] = None


@dataclass
class _Tasks:
    scan: Optional[asyncio.Task] = None
    resolve: Optional[asyncio.Task] = None
    status: LoopStatus = field(default_factory=LoopStatus)


class PaperLoop:
    """Owns the two background asyncio tasks and exposes start/stop + status."""

    def __init__(self):
        self._tasks = _Tasks()
        self._next_scan_at: Optional[float] = None
        self._next_resolve_at: Optional[float] = None

    @property
    def status(self) -> LoopStatus:
        s = self._tasks.status
        loop = asyncio.get_event_loop()
        now = loop.time() if loop.is_running() else 0
        s.next_scan_in = max(0, int(self._next_scan_at - now)) if self._next_scan_at else None
        s.next_resolve_in = max(0, int(self._next_resolve_at - now)) if self._next_resolve_at else None
        s.market_open = _is_market_hours()
        return s

    async def start(self) -> bool:
        if self._tasks.scan and not self._tasks.scan.done():
            return False  # already running
        self._tasks.status.enabled = True
        self._tasks.status.started_at = datetime.utcnow().isoformat() + "Z"
        self._tasks.scan = asyncio.create_task(self._scan_loop(), name="paper-scan")
        self._tasks.resolve = asyncio.create_task(self._resolve_loop(), name="paper-resolve")
        logger.info("Paper loop started.")
        return True

    async def stop(self) -> bool:
        changed = False
        for t in (self._tasks.scan, self._tasks.resolve):
            if t and not t.done():
                t.cancel()
                changed = True
        self._tasks.scan = None
        self._tasks.resolve = None
        self._tasks.status.enabled = False
        self._next_scan_at = None
        self._next_resolve_at = None
        if changed:
            logger.info("Paper loop stopped.")
        return changed

    # ──────────────────────────────────────────────
    # SCAN LOOP
    # ──────────────────────────────────────────────

    async def _scan_loop(self):
        """Drive the analysis pipeline across the watchlist on a schedule."""
        # Stagger start so we don't slam Dhan with the first scan instantly.
        await asyncio.sleep(5)
        while True:
            try:
                if settings.PAPER_LOOP_RESPECT_MARKET_HOURS and not _is_market_hours():
                    await self._set_next_scan_in(60)
                    await asyncio.sleep(60)
                    continue
                await self._run_one_scan()
                self._tasks.status.errors_in_a_row = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._tasks.status.errors_in_a_row += 1
                logger.warning(f"Paper scan error: {e}")
            await self._set_next_scan_in(settings.PAPER_LOOP_SCAN_INTERVAL_SECONDS)
            await asyncio.sleep(settings.PAPER_LOOP_SCAN_INTERVAL_SECONDS)

    async def _set_next_scan_in(self, seconds: int):
        loop = asyncio.get_event_loop()
        self._next_scan_at = loop.time() + seconds

    async def _run_one_scan(self):
        watchlist = _watchlist()
        timeframes = settings.PAPER_LOOP_TIMEFRAMES or ["1h"]
        actionable = 0
        total = 0

        # Bound concurrency — we hit Dhan and write to DB per call.
        sem = asyncio.Semaphore(4)

        async def one(symbol: str, timeframe: str):
            nonlocal actionable, total
            async with sem:
                try:
                    decision = await self._analyse_one(symbol, timeframe)
                    total += 1
                    if decision and decision.get("direction") in ("BUY", "SELL"):
                        actionable += 1
                except Exception as e:
                    logger.debug(f"scan {symbol}/{timeframe}: {e}")

        await asyncio.gather(*[one(s, tf) for s in watchlist for tf in timeframes])

        self._tasks.status.last_scan_at = datetime.utcnow().isoformat() + "Z"
        self._tasks.status.last_scan_signals = actionable
        self._tasks.status.last_scan_total = total
        logger.info(f"Paper scan: {actionable}/{total} actionable across {len(watchlist)} symbols × {len(timeframes)} tf")

    async def _analyse_one(self, symbol: str, timeframe: str) -> Optional[dict]:
        """Re-uses the existing /analysis/run endpoint over loopback so that
        all wiring (alerts, regime logging, learning trade-log) fires exactly
        the same way as a manual click. Avoids duplicating the pipeline code."""
        url = f"http://127.0.0.1:{settings.PORT or 8001}/api/v1/analysis/run"
        params = {"symbol": symbol, "timeframe": timeframe}
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(url, params=params)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.debug(f"loopback analyse {symbol}: {e}")
                return None
        return data.get("decision")

    # ──────────────────────────────────────────────
    # RESOLVE LOOP
    # ──────────────────────────────────────────────

    async def _resolve_loop(self):
        await asyncio.sleep(15)  # let the scanner go first
        while True:
            try:
                resolved = await self._resolve_pending()
                if resolved:
                    logger.info(f"Paper resolver closed {resolved} positions")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Paper resolve error: {e}")
            self._tasks.status.last_resolve_at = datetime.utcnow().isoformat() + "Z"
            await self._set_next_resolve_in(settings.PAPER_LOOP_RESOLVE_INTERVAL_SECONDS)
            await asyncio.sleep(settings.PAPER_LOOP_RESOLVE_INTERVAL_SECONDS)

    async def _set_next_resolve_in(self, seconds: int):
        loop = asyncio.get_event_loop()
        self._next_resolve_at = loop.time() + seconds

    async def _resolve_pending(self) -> int:
        async with async_session() as db:
            result = await db.execute(
                select(Trade).where(
                    and_(
                        Trade.outcome == "PENDING",
                        Trade.direction.in_(("BUY", "SELL")),
                    )
                )
            )
            pending = list(result.scalars().all())
            self._tasks.status.open_positions = len(pending)

            resolved = 0
            timeout_cutoff = datetime.utcnow() - timedelta(hours=settings.PAPER_LOOP_TIMEOUT_HOURS)

            for trade in pending:
                try:
                    outcome, exit_price = await self._resolve_one(trade)
                except Exception as e:
                    logger.debug(f"resolve {trade.trade_id}: {e}")
                    continue

                if outcome:
                    await learning_engine.update_trade_outcome(db, trade.trade_id, outcome, exit_price)
                    resolved += 1
                elif trade.timestamp and trade.timestamp < timeout_cutoff:
                    # Forced close at last close price — neutral outcome
                    last_close = self._last_close(trade.symbol, trade.timeframe)
                    if last_close is not None:
                        await learning_engine.update_trade_outcome(
                            db, trade.trade_id, "TIMEOUT", float(last_close)
                        )
                        resolved += 1

            await db.commit()
            return resolved

    async def _resolve_one(self, trade: Trade):
        """Walk candles since trade.timestamp and find the first SL/TP hit.
        Returns (outcome, exit_price) or (None, None) if still pending."""
        df = data_engine.get_cached(trade.symbol, trade.timeframe)
        if df is None or df.empty:
            return None, None

        try:
            since = trade.timestamp
            mask = df.index > since
            later = df[mask]
        except Exception:
            return None, None
        if later.empty:
            return None, None

        sl = trade.stop_loss
        tp = trade.take_profit
        direction = trade.direction
        if not sl or not tp:
            return None, None

        for _, row in later.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            if direction == "BUY":
                sl_hit = low <= sl
                tp_hit = high >= tp
                if sl_hit and tp_hit:
                    return "LOSS", float(sl)  # conservative: SL fires first
                if tp_hit:
                    return "WIN", float(tp)
                if sl_hit:
                    return "LOSS", float(sl)
            else:  # SELL
                sl_hit = high >= sl
                tp_hit = low <= tp
                if sl_hit and tp_hit:
                    return "LOSS", float(sl)
                if tp_hit:
                    return "WIN", float(tp)
                if sl_hit:
                    return "LOSS", float(sl)
        return None, None

    @staticmethod
    def _last_close(symbol: str, timeframe: str) -> Optional[float]:
        df = data_engine.get_cached(symbol, timeframe)
        if df is None or df.empty:
            return None
        return float(df["close"].iloc[-1])


# Singleton
paper_loop = PaperLoop()
