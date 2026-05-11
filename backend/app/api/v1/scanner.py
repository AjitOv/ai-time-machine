"""Top-opportunities scanner – ranks NIFTY 50 setups by decision strength."""

import asyncio
import logging
import time
from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.engines.behavior_engine import behavior_engine
from app.engines.context_engine import context_engine
from app.engines.data_engine import data_engine
from app.engines.dna_engine import dna_engine, DNAEngine
from app.engines.scenario_engine import scenario_engine
from app.engines.simulation_engine import simulation_engine
from app.engines.symbols import NIFTY_50, NIFTY_INDICES
from app.engines.uncertainty_engine import uncertainty_engine

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory TTL cache: { (universe, timeframe): (expires_at, results) }
_CACHE: Dict[tuple, tuple] = {}
_CACHE_TTL = 300  # seconds


async def _score_symbol(
    db: AsyncSession, symbol: str, timeframe: str
) -> Optional[Dict]:
    """Run the gating engines and return a ranked-row dict, or None on error."""
    try:
        df = data_engine.get_latest_features(symbol, timeframe, lookback=100)
        if df.empty or len(df) < 30:
            return None

        ctx = context_engine.analyze(df)
        beh = behavior_engine.analyze(df, ctx.htf_bias, ctx.zone)

        latest = df.iloc[-1]
        rsi_val = float(latest.get("rsi_14", 50)) if latest.get("rsi_14") == latest.get("rsi_14") else 50
        atr_val = float(latest.get("atr_14", 0)) if latest.get("atr_14") == latest.get("atr_14") else 0
        atr_mean = float(df["atr_14"].mean()) if "atr_14" in df else 1
        ema_alignment = 0.0
        if "ema_11" in latest and "ema_50" in latest:
            if latest["ema_11"] == latest["ema_11"] and latest["ema_50"] == latest["ema_50"] and latest["ema_50"] != 0:
                ema_alignment = max(-1, min(1, (float(latest["ema_11"]) - float(latest["ema_50"])) / float(latest["ema_50"]) * 100))
        zone_val = {"DISCOUNT": -1, "EQUILIBRIUM": 0, "PREMIUM": 1}.get(ctx.zone, 0)
        phase_val = {"RANGE": 0.2, "TREND": 0.8, "EXHAUSTION": 0.4, "CHAOTIC": 0.1}.get(ctx.phase, 0.5)

        feature_vector = DNAEngine.build_feature_vector(
            ctx.context_score, beh.behavior_score, rsi_val, ema_alignment,
            atr_val / atr_mean if atr_mean > 0 else 1, zone_val, phase_val,
        )
        dna_result = await dna_engine.find_matches(db, feature_vector, symbol)

        returns = np.diff(np.log(df["close"].values))
        returns = returns[~np.isnan(returns)]
        sim_result = simulation_engine.simulate(
            current_price=float(df["close"].iloc[-1]),
            historical_returns=returns,
            dna_direction=dna_result.best_match.direction if dna_result.best_match else None,
            dna_confidence=dna_result.dna_confidence,
            regime=ctx.regime,
        )
        scenarios = scenario_engine.build_scenarios(
            sim_result, ctx.context_score, beh.behavior_score, float(df["close"].iloc[-1])
        )
        rough_conf = abs(ctx.context_score * 0.25 + beh.behavior_score * 0.25 +
                         dna_result.dna_confidence * 0.25 + sim_result.simulation_bias * 0.25)
        unc = uncertainty_engine.evaluate(ctx, beh, dna_result, sim_result, rough_conf)

        # Combined score: weighted vote × (1 − uncertainty), with context permission baked in
        weighted = (ctx.context_score * 0.25 + beh.behavior_score * 0.25 +
                    sim_result.simulation_bias * 0.25 +
                    (dna_result.dna_confidence if dna_result.best_match and dna_result.best_match.direction == "BUY" else
                     -dna_result.dna_confidence if dna_result.best_match and dna_result.best_match.direction == "SELL" else 0) * 0.25)
        rank_score = weighted * (1 - unc.uncertainty_score)
        if not ctx.trade_permission:
            rank_score *= 0.3  # heavy penalty, not zero — still surface for inspection

        direction = "BUY" if weighted > 0.15 else ("SELL" if weighted < -0.15 else "NO_TRADE")
        dominant = max(scenarios.scenarios, key=lambda s: s.probability)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "current_price": round(float(df["close"].iloc[-1]), 2),
            "direction": direction,
            "rank_score": round(rank_score, 4),
            "weighted_score": round(weighted, 4),
            "context_score": round(ctx.context_score, 4),
            "behavior_score": round(beh.behavior_score, 4),
            "dna_confidence": round(dna_result.dna_confidence, 4),
            "sim_bullish_prob": round(sim_result.bullish_probability, 4),
            "uncertainty": round(unc.uncertainty_score, 4),
            "phase": ctx.phase,
            "regime": ctx.regime,
            "zone": ctx.zone,
            "trade_permission": ctx.trade_permission,
            "dominant_scenario": {
                "label": dominant.label,
                "probability": round(dominant.probability, 4),
                "expected_price": round(dominant.expected_price, 2),
            },
        }
    except Exception as e:
        logger.error(f"Scanner error on {symbol}: {e}")
        return None


def _universe(name: str) -> List[str]:
    name = (name or "nifty50").lower()
    if name == "indices":
        return NIFTY_INDICES
    if name == "all":
        return NIFTY_INDICES + NIFTY_50
    return NIFTY_50


@router.get("/scan")
async def scan(
    universe: str = Query(default="nifty50", description="nifty50 | indices | all"),
    timeframe: str = Query(default="1h"),
    limit: int = Query(default=10, ge=1, le=50),
    only_actionable: bool = Query(default=False),
    refresh: bool = Query(default=False, description="Force re-scan, bypass cache"),
    db: AsyncSession = Depends(get_db),
):
    """Rank symbols by decision-strength. Cached for 5 min by (universe, timeframe)."""
    cache_key = (universe.lower(), timeframe)
    now = time.time()
    if not refresh and cache_key in _CACHE:
        expires_at, cached = _CACHE[cache_key]
        if now < expires_at:
            return _filter_and_slice(cached, limit, only_actionable, cached_at=expires_at - _CACHE_TTL)

    symbols = _universe(universe)

    # Bound concurrency so we don't melt rate limits / CPU
    sem = asyncio.Semaphore(6)

    async def bound(sym: str):
        async with sem:
            return await _score_symbol(db, sym, timeframe)

    rows = await asyncio.gather(*[bound(s) for s in symbols], return_exceptions=False)
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: abs(r["rank_score"]), reverse=True)

    _CACHE[cache_key] = (now + _CACHE_TTL, rows)
    return _filter_and_slice(rows, limit, only_actionable, cached_at=now)


def _filter_and_slice(rows: List[Dict], limit: int, only_actionable: bool, cached_at: float):
    filtered = [r for r in rows if r["direction"] != "NO_TRADE"] if only_actionable else rows
    return {
        "count": len(filtered),
        "scanned": len(rows),
        "cached_at": int(cached_at),
        "ttl_seconds": _CACHE_TTL,
        "results": filtered[:limit],
    }
