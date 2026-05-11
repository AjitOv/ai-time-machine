"""Market data API endpoints."""

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.config import settings
from app.engines.data_engine import data_engine
from app.engines.symbols import MCX_COMMODITIES, NIFTY_50, NIFTY_INDICES

router = APIRouter()


@router.get("/data")
async def get_market_data(
    symbol: str = Query(default=None, description="Market symbol"),
    timeframe: str = Query(default="1h", description="Timeframe"),
    limit: int = Query(default=100, description="Number of candles"),
    db: AsyncSession = Depends(get_db),
):
    """Get current OHLCV data with computed indicators."""
    sym = symbol or settings.DEFAULT_SYMBOL
    df = data_engine.get_latest_features(sym, timeframe, limit)

    if df.empty:
        return {"symbol": sym, "timeframe": timeframe, "candles": [], "features": []}

    candles = []
    features = []
    for ts, row in df.iterrows():
        candles.append({
            "timestamp": ts.isoformat(),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": float(row["volume"]),
        })
        features.append({
            "timestamp": ts.isoformat(),
            "close": round(float(row["close"]), 2),
            "rsi_14": round(float(row["rsi_14"]), 2) if "rsi_14" in row and row["rsi_14"] == row["rsi_14"] else None,
            "ema_11": round(float(row["ema_11"]), 2) if "ema_11" in row and row["ema_11"] == row["ema_11"] else None,
            "ema_21": round(float(row["ema_21"]), 2) if "ema_21" in row and row["ema_21"] == row["ema_21"] else None,
            "ema_50": round(float(row["ema_50"]), 2) if "ema_50" in row and row["ema_50"] == row["ema_50"] else None,
            "atr_14": round(float(row["atr_14"]), 4) if "atr_14" in row and row["atr_14"] == row["atr_14"] else None,
        })

    return {
        "symbol": sym,
        "timeframe": timeframe,
        "candles": candles,
        "features": features,
        "count": len(candles),
    }


@router.get("/history")
async def get_market_history(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch and store historical data, return enriched dataset."""
    sym = symbol or settings.DEFAULT_SYMBOL
    results = await data_engine.ingest_and_compute(db, sym, [timeframe])

    df = results.get(timeframe)
    if df is None or df.empty:
        return {"symbol": sym, "timeframe": timeframe, "status": "no_data", "count": 0}

    return {
        "symbol": sym,
        "timeframe": timeframe,
        "status": "ok",
        "count": len(df),
        "latest_price": round(float(df["close"].iloc[-1]), 2),
        "latest_rsi": round(float(df["rsi_14"].iloc[-1]), 2) if "rsi_14" in df else None,
    }


@router.post("/ingest")
async def ingest_all_timeframes(
    symbol: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Ingest data for all supported timeframes."""
    sym = symbol or settings.DEFAULT_SYMBOL
    results = await data_engine.ingest_and_compute(db, sym)

    summary = {}
    for tf, df in results.items():
        summary[tf] = {
            "candles": len(df),
            "latest_price": round(float(df["close"].iloc[-1]), 2) if not df.empty else None,
        }

    return {"symbol": sym, "status": "ok", "timeframes": summary}


@router.get("/universe")
async def get_symbol_universe():
    """Return the curated symbol lists used by batch operations."""
    return {
        "nifty_50": NIFTY_50,
        "mcx_commodities": MCX_COMMODITIES,
        "indices": NIFTY_INDICES,
    }


@router.post("/batch/nifty50")
async def ingest_nifty50(
    timeframe: str = Query(default="1h"),
    include_mcx: bool = Query(default=True),
    include_indices: bool = Query(default=True),
    concurrency: int = Query(default=2, ge=1, le=10),
):
    """Ingest a single timeframe for Nifty 50 + (optionally) MCX + indices.

    Each symbol uses its own DB session to avoid SQLAlchemy session conflicts
    under concurrency. Low default concurrency (2) respects FYERS rate limits.
    """
    symbols = list(NIFTY_50)
    if include_indices:
        symbols.extend(NIFTY_INDICES)
    if include_mcx:
        symbols.extend(MCX_COMMODITIES)

    sem = asyncio.Semaphore(concurrency)

    async def _ingest_one(sym: str):
        async with sem:
            async with async_session() as session:
                try:
                    results = await data_engine.ingest_and_compute(session, sym, [timeframe])
                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    return sym, {"status": "error", "error": str(e)[:120]}

            df = results.get(timeframe)
            if df is None or df.empty:
                return sym, {"status": "no_data", "candles": 0}
            return sym, {
                "status": "ok",
                "candles": len(df),
                "latest_close": round(float(df["close"].iloc[-1]), 2),
            }

    completed = await asyncio.gather(*(_ingest_one(s) for s in symbols))
    per_symbol = dict(completed)
    ok_count = sum(1 for v in per_symbol.values() if v["status"] == "ok")

    return {
        "timeframe": timeframe,
        "requested": len(symbols),
        "succeeded": ok_count,
        "failed": len(symbols) - ok_count,
        "results": per_symbol,
    }
