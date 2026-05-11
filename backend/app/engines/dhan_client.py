"""
Dhan REST API v2 client.

Fetches OHLCV via the public Dhan HTTP API. Maps our FYERS-style symbols
(`NSE:TCS-EQ`, `NSE:NIFTY50-INDEX`, `MCX:GOLD26JUNFUT`) to Dhan's
(security_id, exchange_segment, instrument) tuple via the official
api-scrip-master CSV cached locally (auto-downloaded if missing).

Docs: https://dhanhq.co/docs/v2/historical/
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

# Dhan publishes the instrument master CSV publicly; we cache locally.
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


def ensure_scrip_master(path: Path) -> bool:
    """Download Dhan's public scrip master if it's missing or truncated.
    Called from DhanClient.__init__ (REST), DhanFeedManager (live ticks),
    and the /symbols/search route — so a fresh Render boot self-heals."""
    if path.exists() and path.stat().st_size > 1_000_000:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading Dhan scrip master to {path} ...")
        with httpx.Client(timeout=60.0) as client:
            r = client.get(SCRIP_MASTER_URL)
            r.raise_for_status()
            path.write_bytes(r.content)
        logger.info(f"Scrip master saved: {path.stat().st_size:,} bytes")
        return True
    except Exception as e:
        logger.warning(f"Could not fetch Dhan scrip master: {e}")
        return False


def default_scrip_master_path() -> Path:
    """The canonical location for the scrip master CSV — under
    backend/historical_data/ which always exists in the deploy bundle and
    is writable on Render."""
    return Path(__file__).resolve().parents[2] / "historical_data" / "dhan_scrip_master.csv"

INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
HISTORICAL_URL = "https://api.dhan.co/v2/charts/historical"

# TimeMachine timeframe → Dhan intraday interval (minutes, as string)
INTRADAY_INTERVAL = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
}

# Days of history to request per timeframe (Dhan caps intraday at ~90d).
DAYS_BACK = {
    "1m": 5,
    "5m": 30,
    "15m": 60,
    "1h": 90,
    "4h": 365,
    "1d": 1825,
}

# Hardcoded index map — small, stable, indexes don't follow EQ naming.
# Format in our codebase: NSE:<KEY>-INDEX
INDEX_MAP: Dict[str, Tuple[str, str]] = {
    "NIFTY50": ("13", "IDX_I"),
    "NIFTYBANK": ("25", "IDX_I"),
    "BANKNIFTY": ("25", "IDX_I"),
    "FINNIFTY": ("27", "IDX_I"),
    "MIDCPNIFTY": ("442", "IDX_I"),
    "INDIAVIX": ("21", "IDX_I"),
    "NIFTY100": ("17", "IDX_I"),
    "NIFTY200": ("18", "IDX_I"),
    "NIFTY500": ("19", "IDX_I"),
    "NIFTYAUTO": ("14", "IDX_I"),
    "NIFTYFMCG": ("28", "IDX_I"),
    "NIFTYIT": ("29", "IDX_I"),
    "NIFTYMETAL": ("31", "IDX_I"),
    "NIFTYPHARMA": ("32", "IDX_I"),
    "NIFTYREALTY": ("34", "IDX_I"),
    "NIFTYNEXT50": ("38", "IDX_I"),
    "NIFTYENERGY": ("42", "IDX_I"),
    "NIFTYMIDCAP50": ("20", "IDX_I"),
    "NIFTYMIDCAP150": ("1", "IDX_I"),
    "NIFTYSMALLCAP100": ("5", "IDX_I"),
    "NIFTYSMALLCAP250": ("3", "IDX_I"),
    "NIFTYTOTALMKT": ("443", "IDX_I"),
}

# Our exchange prefix → Dhan exchange_segment for equity/cash
CASH_SEGMENT = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
}


class DhanClient:
    """Dhan REST client — historical candles only."""

    def __init__(
        self,
        client_id: str,
        access_token: str,
        scrip_master_path: Path,
        timeout: float = 15.0,
    ):
        # Self-heal: download the public scrip master CSV if absent. Render's
        # fresh boot doesn't ship the file (gitignored), so this is what makes
        # symbol resolution work in production.
        ensure_scrip_master(scrip_master_path)
        self.client_id = client_id
        self.access_token = access_token
        self._scrip_master_path = scrip_master_path
        self._symbol_cache: Dict[str, Tuple[str, str, str]] = {}
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "access-token": access_token,
                "client-id": client_id,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    def close(self):
        self._client.close()

    # ──────────────────────────────────────────────
    # SYMBOL RESOLUTION
    # ──────────────────────────────────────────────

    def _resolve_symbol(self, symbol: str) -> Optional[Tuple[str, str, str]]:
        """
        Map a TimeMachine symbol to (security_id, exchange_segment, instrument).
        Returns None if unknown.
        """
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]

        if ":" not in symbol:
            return None
        exch, rest = symbol.split(":", 1)

        # Index path: NSE:NIFTY50-INDEX
        if rest.endswith("-INDEX"):
            key = rest[:-6]
            mapped = INDEX_MAP.get(key)
            if mapped:
                sid, seg = mapped
                result = (sid, seg, "INDEX")
                self._symbol_cache[symbol] = result
                return result
            # Fall through to CSV lookup for indices not in the hardcoded map
            return self._lookup_csv(exch, key, want_instrument="INDEX")

        # Equity path: NSE:TCS-EQ
        if rest.endswith("-EQ"):
            trading_symbol = rest[:-3]
            return self._lookup_csv(exch, trading_symbol, want_instrument="EQUITY")

        # Commodity / futures path: MCX:GOLD26JUNFUT
        # Match SEM_TRADING_SYMBOL exactly within the requested exchange.
        return self._lookup_csv(exch, rest)

    def _lookup_csv(
        self,
        exch: str,
        trading_symbol: str,
        want_instrument: Optional[str] = None,
    ) -> Optional[Tuple[str, str, str]]:
        """Scan the scrip master CSV for a matching row."""
        if not self._scrip_master_path.exists():
            logger.error(f"Dhan scrip master not found at {self._scrip_master_path}")
            return None

        try:
            with self._scrip_master_path.open(newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("SEM_EXM_EXCH_ID") != exch:
                        continue
                    if row.get("SEM_TRADING_SYMBOL") != trading_symbol:
                        continue
                    instrument = row.get("SEM_INSTRUMENT_NAME", "")
                    if want_instrument and instrument != want_instrument:
                        continue
                    sid = row.get("SEM_SMST_SECURITY_ID")
                    segment = self._segment_for(exch, instrument)
                    if not sid or not segment:
                        continue
                    result = (sid, segment, instrument)
                    self._symbol_cache[f"{exch}:{trading_symbol}"] = result
                    return result
        except Exception as e:
            logger.error(f"Dhan CSV scan failed for {exch}:{trading_symbol}: {e}")
            return None

        logger.warning(f"Dhan: no scrip master entry for {exch}:{trading_symbol}")
        return None

    @staticmethod
    def _segment_for(exch: str, instrument: str) -> Optional[str]:
        if instrument == "INDEX":
            return "IDX_I"
        if instrument == "EQUITY":
            return CASH_SEGMENT.get(exch)
        if instrument in ("FUTIDX", "OPTIDX", "FUTSTK", "OPTSTK"):
            if exch == "NSE":
                return "NSE_FNO"
            if exch == "BSE":
                return "BSE_FNO"
        if instrument in ("FUTCOM", "OPTFUT"):
            return "MCX_COMM"
        return None

    # ──────────────────────────────────────────────
    # CANDLE FETCH
    # ──────────────────────────────────────────────

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        days_back: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles. Returns empty DataFrame on failure."""
        resolved = self._resolve_symbol(symbol)
        if not resolved:
            return pd.DataFrame()
        security_id, exchange_segment, instrument = resolved

        end = datetime.now().date()
        start = end - timedelta(days=days_back or DAYS_BACK.get(timeframe, 30))

        body = {
            "securityId": security_id,
            "exchangeSegment": exchange_segment,
            "instrument": instrument,
            "oi": False,
            "fromDate": start.isoformat(),
            "toDate": end.isoformat(),
        }

        if timeframe in INTRADAY_INTERVAL:
            url = INTRADAY_URL
            body["interval"] = INTRADAY_INTERVAL[timeframe]
        else:
            url = HISTORICAL_URL
            body["expiryCode"] = 0

        try:
            resp = self._client.post(url, json=body)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.error(f"Dhan history error for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

        if not payload or not payload.get("timestamp"):
            logger.warning(f"Dhan empty response for {symbol} {timeframe}")
            return pd.DataFrame()

        try:
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(payload["timestamp"], unit="s"),
                "open": payload["open"],
                "high": payload["high"],
                "low": payload["low"],
                "close": payload["close"],
                "volume": payload.get("volume", [0] * len(payload["timestamp"])),
            })
        except (KeyError, ValueError) as e:
            logger.error(f"Dhan response shape unexpected for {symbol}: {e}")
            return pd.DataFrame()

        df.set_index("timestamp", inplace=True)
        logger.info(f"Dhan fetched {len(df)} candles for {symbol} {timeframe}")
        return df
