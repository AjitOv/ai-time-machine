"""Backtest API — replays history through the engine stack."""

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.engines.backtest_engine import backtest_engine
from app.engines.dna_engine import dna_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/run")
async def run_backtest(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
    warmup: int = Query(default=100, ge=20, le=500),
    max_bars: int = Query(default=600, ge=100, le=5000,
                          description="Cap on the number of bars to replay (limits runtime)."),
):
    """Run a backtest over the cached candle history for the symbol+timeframe.
    Returns trades, equity curve, and summary stats. Runs synchronously — for
    typical 1h windows of ~600 bars on a NIFTY index this returns in ~5–15s."""
    sym = symbol or settings.DEFAULT_SYMBOL
    logger.info(f"backtest start: {sym} {timeframe} warmup={warmup} max_bars={max_bars}")
    result = backtest_engine.run(sym, timeframe, warmup=warmup, max_bars=max_bars)
    logger.info(
        f"backtest done: {sym} {timeframe} bars={result.bars_processed} "
        f"trades={result.total_trades} wr={result.win_rate} pf={result.profit_factor} "
        f"runtime={result.runtime_ms}ms"
    )
    return asdict(result)


@router.post("/seed-dna")
async def seed_dna_from_backtest(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
    warmup: int = Query(default=100, ge=20, le=500),
    max_bars: int = Query(default=600, ge=100, le=5000),
    include_losses: bool = Query(default=True,
                                 description="Also seed LOSS patterns so DNA learns what to avoid."),
    db: AsyncSession = Depends(get_db),
):
    """Run a backtest and seed the live DNA library with the resulting patterns.

    Each unique pattern_signature gets one DNA record; multiple trades with the
    same signature merge into that record (existing dna_engine.store_dna logic
    handles updates via EMA on the feature vector + reliability scoring).
    Losses are seeded by default — DNA needs negative examples too.
    """
    sym = symbol or settings.DEFAULT_SYMBOL
    result = backtest_engine.run(sym, timeframe, warmup=warmup, max_bars=max_bars)

    if not result.trades:
        return {"ok": False, "reason": "No trades produced", "result": asdict(result)}

    seeded_wins = 0
    seeded_losses = 0
    skipped = 0
    # result.trades is a List[Dict] (asdict-converted in BacktestResult)
    for tr in result.trades:
        outcome = tr.get("outcome")
        if outcome not in ("WIN", "LOSS"):
            skipped += 1
            continue
        if outcome == "LOSS" and not include_losses:
            skipped += 1
            continue
        if not tr.get("feature_vector") or not tr.get("pattern_signature"):
            skipped += 1
            continue

        try:
            await dna_engine.store_dna(
                db=db,
                symbol=tr["symbol"],
                timeframe=tr["timeframe"],
                direction=tr["direction"],
                pattern_signature=tr["pattern_signature"],
                feature_vector=tr["feature_vector"],
                context_features={
                    "regime": tr.get("regime"), "phase": tr.get("phase"),
                    "zone": tr.get("zone"), "htf_bias": tr.get("htf_bias"),
                    "context_score": tr.get("context_score"),
                },
                behavior_features={"behavior_score": tr.get("behavior_score")},
                entry_conditions={
                    "entry": tr.get("entry_price"), "stop_loss": tr.get("stop_loss"),
                    "take_profit": tr.get("take_profit"), "confidence": tr.get("confidence"),
                },
                outcome=outcome,
                risk_reward=tr.get("rr_realized") or 0.0,
            )
            if outcome == "WIN":
                seeded_wins += 1
            else:
                seeded_losses += 1
        except Exception as e:
            logger.warning(f"seed-dna error for {tr.get('timestamp')}: {e}")
            skipped += 1

    await db.commit()
    return {
        "ok": True,
        "symbol": sym,
        "timeframe": timeframe,
        "bars_processed": result.bars_processed,
        "total_trades": result.total_trades,
        "seeded_wins": seeded_wins,
        "seeded_losses": seeded_losses,
        "skipped": skipped,
        "win_rate_seed": result.win_rate,
        "profit_factor": result.profit_factor,
    }
