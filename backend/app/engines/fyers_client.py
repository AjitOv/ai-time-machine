"""
FYERS REST API v3 client.

Fetches OHLCV via the public FYERS HTTP API. Caller supplies app_id and
access_token (obtained from the OAuth authcode flow at
https://myapi.fyers.in).

Docs: https://myapi.fyers.in/docsv3#tag/Data-Api/paths/~1data~1history/get
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

HIST_URL = "https://api-t1.fyers.in/data/history"

# TimeMachine timeframe → FYERS resolution
RESOLUTION_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "1D",
}

# FYERS historical range caps (verified empirically):
#   - Any intraday resolution (1, 5, 15, 60, 240 min): max 100 days per request
#   - Daily: max 365 days per request
# Requests beyond these limits return HTTP 422 "Invalid input".
DAYS_BACK_MAP = {
    "1m": 5,
    "5m": 30,
    "15m": 60,
    "1h": 100,
    "4h": 100,
    "1d": 365,
}


class FyersClient:
    """Minimal FYERS REST client — historical candles only."""

    def __init__(self, app_id: str, access_token: str, timeout: float = 10.0):
        self.app_id = app_id
        self.access_token = access_token
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"{app_id}:{access_token}"},
        )

    def close(self):
        self._client.close()

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str = "1h",
        days_back: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles. Returns empty DataFrame on failure."""
        resolution = RESOLUTION_MAP.get(timeframe)
        if resolution is None:
            logger.warning(f"FYERS: unsupported timeframe {timeframe}")
            return pd.DataFrame()

        end = datetime.now().date()
        start = end - timedelta(days=days_back or DAYS_BACK_MAP.get(timeframe, 30))

        params = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": "1",
            "range_from": start.isoformat(),
            "range_to": end.isoformat(),
            "cont_flag": "1",
        }

        try:
            resp = self._client.get(HIST_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.error(f"FYERS history error for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

        if payload.get("s") != "ok" or not payload.get("candles"):
            logger.warning(f"FYERS empty/error response for {symbol} {timeframe}: {payload.get('s')}")
            return pd.DataFrame()

        df = pd.DataFrame(
            payload["candles"],
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df.set_index("timestamp", inplace=True)
        logger.info(f"FYERS fetched {len(df)} candles for {symbol} {timeframe}")
        return df
