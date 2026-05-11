"""
Dhan live tick feed manager.

Holds one upstream WebSocket connection to Dhan's marketfeed and fans out
parsed ticks to any number of frontend subscribers (one queue per FastAPI
WebSocket client). The frontend doesn't talk to Dhan directly — that would
require leaking the access_token to the browser.

Lifecycle:
  - First subscriber spins up the upstream connection (lazy).
  - When all subscribers for a symbol disconnect, that symbol is unsubscribed
    upstream. The connection itself stays open until app shutdown.
  - Reconnects automatically with exponential backoff on disconnect.
"""

import asyncio
import logging
import urllib.parse
from collections import defaultdict
from typing import Dict, Optional, Set, Tuple

import websockets
from dhanhq import marketfeed

from app.config import settings
from app.engines.dhan_client import DhanClient

logger = logging.getLogger(__name__)

# Dhan v2 WS endpoint requires credentials in the URL — the dhanhq<2.0 SDK
# only knows the legacy binary-auth flow, so we override .connect() below.
_DHAN_WSS_V2_BASE = "wss://api-feed.dhan.co"


async def _connect_v2(feed: "marketfeed.DhanFeed"):
    """Open a v2 WebSocket with credentials in the URL — v1 binary auth is deprecated."""
    qs = urllib.parse.urlencode({
        "version": "2",
        "token": feed.access_token,
        "clientId": feed.client_id,
        "authType": "2",
    })
    url = f"{_DHAN_WSS_V2_BASE}?{qs}"
    feed.ws = await websockets.connect(url, ping_interval=20, ping_timeout=20)
    feed.is_authorized = True


def _ws_is_open(ws) -> bool:
    """websockets >= 12 dropped `.closed`; use `.state` / `.close_code` instead."""
    if ws is None:
        return False
    if hasattr(ws, "closed"):
        return not ws.closed
    if hasattr(ws, "close_code"):
        return ws.close_code is None
    return True


async def _send_subscribe(feed, instruments):
    """Direct subscribe path that doesn't rely on the SDK's ws.closed check."""
    from dhanhq.marketfeed import validate_and_process_tuples
    grouped = validate_and_process_tuples(instruments, 100)
    for type_str, batches in grouped.items():
        for batch in batches:
            if not batch:
                continue
            packet = feed.create_subscription_packet(batch, int(type_str))
            await feed.ws.send(packet)

# Map our REST exchange_segment strings → marketfeed integer codes
_SEGMENT_TO_INT = {
    "IDX_I": marketfeed.IDX,         # 0
    "NSE_EQ": marketfeed.NSE,        # 1
    "NSE_FNO": marketfeed.NSE_FNO,   # 2
    "BSE_EQ": marketfeed.BSE,        # 4
    "MCX_COMM": marketfeed.MCX,      # 5
}


class DhanFeedManager:
    """Singleton-ish: one upstream connection, many frontend subscribers."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._feed: Optional[marketfeed.DhanFeed] = None
        self._reader_task: Optional[asyncio.Task] = None
        # symbol → set of asyncio.Queue (one per connected frontend client)
        self._listeners: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        # symbol → (segment_int, security_id_str)
        self._resolved: Dict[str, Tuple[int, str]] = {}
        self._client = self._make_resolver()

    def _make_resolver(self) -> Optional[DhanClient]:
        """Reuse the existing Dhan REST client just for symbol resolution."""
        if not (settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN):
            return None
        from pathlib import Path
        from app.engines.dhan_client import default_scrip_master_path
        legacy = Path(__file__).resolve().parents[3] / "data" / "dhan_scrip_master.csv"
        scrip_path = legacy if legacy.exists() else default_scrip_master_path()
        return DhanClient(
            settings.DHAN_CLIENT_ID,
            settings.DHAN_ACCESS_TOKEN,
            scrip_master_path=scrip_path,
        )

    def _resolve(self, symbol: str) -> Optional[Tuple[int, str]]:
        if symbol in self._resolved:
            return self._resolved[symbol]
        if not self._client:
            return None
        rec = self._client._resolve_symbol(symbol)
        if not rec:
            return None
        sid_str, seg_str, _ = rec
        seg_int = _SEGMENT_TO_INT.get(seg_str)
        if seg_int is None:
            return None
        self._resolved[symbol] = (seg_int, sid_str)
        return self._resolved[symbol]

    async def _ensure_connected(self) -> bool:
        """Create the upstream connection on first use."""
        if self._feed and _ws_is_open(self._feed.ws):
            return True
        if not (settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN):
            return False

        # Build with empty instruments — we'll subscribe dynamically.
        self._feed = marketfeed.DhanFeed(
            client_id=settings.DHAN_CLIENT_ID,
            access_token=settings.DHAN_ACCESS_TOKEN,
            instruments=[],
        )
        try:
            await _connect_v2(self._feed)
        except Exception as e:
            logger.error(f"Dhan feed connect failed: {e}")
            self._feed = None
            return False

        # Start the reader loop
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("Dhan feed connected.")
        return True

    async def _reader_loop(self):
        """Consume ticks from upstream and fan out to listener queues."""
        backoff = 1.0
        while True:
            if not self._feed or not _ws_is_open(self._feed.ws):
                # try to reconnect
                ok = await self._ensure_connected()
                if not ok:
                    logger.warning(f"Dhan feed reconnect failed; sleeping {backoff:.1f}s")
                    await asyncio.sleep(min(30.0, backoff))
                    backoff *= 1.6
                    continue
                # Re-subscribe everything we currently have listeners for
                instruments = []
                for sym in list(self._listeners.keys()):
                    res = self._resolve(sym)
                    if res:
                        instruments.append((res[0], res[1], marketfeed.Ticker))
                if instruments:
                    try:
                        await _send_subscribe(self._feed, instruments)
                    except Exception as e:
                        logger.warning(f"Re-subscribe failed: {e}")
                backoff = 1.0

            try:
                tick = await self._feed.get_instrument_data()
            except Exception as e:
                logger.warning(f"Dhan feed read error: {e}; will reconnect")
                self._feed = None
                continue

            if not isinstance(tick, dict):
                continue

            # We only handle Ticker mode here — extend if Quote/Depth ever wired
            ttype = tick.get("type", "")
            if "Ticker" not in ttype:
                continue

            seg = tick.get("exchange_segment")
            sid = tick.get("security_id")
            ltp = tick.get("LTP")
            ltt = tick.get("LTT")
            if seg is None or sid is None:
                continue

            # Resolve back which symbol(s) this matches
            for sym, (s_seg, s_sid) in list(self._resolved.items()):
                if s_seg == seg and str(s_sid) == str(sid):
                    payload = {"symbol": sym, "ltp": float(ltp) if ltp is not None else None,
                               "ltt": str(ltt) if ltt is not None else None}
                    for q in list(self._listeners.get(sym, ())):
                        # Drop ticks if a listener can't keep up — never block the reader.
                        if q.full():
                            try:
                                q.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        q.put_nowait(payload)

    async def subscribe(self, symbol: str, queue: asyncio.Queue) -> bool:
        """Register a queue to receive ticks for a symbol. Idempotent.
        Returns True if the symbol was resolvable."""
        async with self._lock:
            res = self._resolve(symbol)
            if not res:
                return False
            ok = await self._ensure_connected()
            if not ok:
                return False
            had_listeners = bool(self._listeners[symbol])
            self._listeners[symbol].add(queue)
            if not had_listeners and self._feed:
                # First listener for this symbol → ask Dhan for it
                try:
                    await _send_subscribe(self._feed, [(res[0], res[1], marketfeed.Ticker)])
                    logger.info(f"Dhan feed subscribed {symbol} ({res[0]},{res[1]})")
                except Exception as e:
                    logger.warning(f"Dhan subscribe failed for {symbol}: {e}")
            return True

    async def unsubscribe(self, symbol: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._listeners[symbol].discard(queue)
            if not self._listeners[symbol]:
                # No more listeners — drop upstream subscription. Dhan v2 has
                # an unsubscribe code (16) but we keep it simple: leave the
                # symbol subscribed (cheap) and just stop forwarding to clients.
                self._listeners.pop(symbol, None)


# Singleton — instantiated lazily so import order doesn't matter
_manager: Optional[DhanFeedManager] = None


def get_feed_manager() -> DhanFeedManager:
    global _manager
    if _manager is None:
        _manager = DhanFeedManager()
    return _manager
