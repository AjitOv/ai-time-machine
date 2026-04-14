"""Simulation API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import numpy as np

from app.database import get_db
from app.config import settings
from app.engines.data_engine import data_engine
from app.engines.simulation_engine import simulation_engine
from app.engines.scenario_engine import scenario_engine
from app.engines.context_engine import context_engine
from app.engines.behavior_engine import behavior_engine

router = APIRouter()


@router.post("/run")
async def run_simulation(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
    num_simulations: int = Query(default=100),
    forecast_steps: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
):
    """Run Monte Carlo simulation."""
    sym = symbol or settings.DEFAULT_SYMBOL
    df = data_engine.get_latest_features(sym, timeframe, lookback=200)

    if df.empty:
        return {"error": "No data available for simulation"}

    current_price = float(df["close"].iloc[-1])
    returns = np.diff(np.log(df["close"].values))
    returns = returns[~np.isnan(returns)]

    # Get context for regime
    ctx = context_engine.analyze(df)

    sim_result = simulation_engine.simulate(
        current_price=current_price,
        historical_returns=returns,
        num_sims=num_simulations,
        forecast_steps=forecast_steps,
        regime=ctx.regime,
    )

    # Build scenarios
    beh = behavior_engine.analyze(df)
    scenarios = scenario_engine.build_scenarios(
        sim_result, ctx.context_score, beh.behavior_score, current_price
    )

    # Sample paths for visualization (first 10)
    paths_sample = []
    if sim_result.paths is not None:
        for i in range(min(10, sim_result.paths.shape[1])):
            paths_sample.append([round(float(p), 2) for p in sim_result.paths[:, i]])

    return {
        "symbol": sym,
        "current_price": round(current_price, 2),
        "bullish_probability": sim_result.bullish_probability,
        "bearish_probability": sim_result.bearish_probability,
        "neutral_probability": sim_result.neutral_probability,
        "target_hit_probability": sim_result.target_hit_probability,
        "stop_loss_risk": sim_result.stop_loss_risk,
        "mean_final_price": sim_result.mean_final_price,
        "median_final_price": sim_result.median_final_price,
        "price_5th_percentile": sim_result.price_5th_percentile,
        "price_95th_percentile": sim_result.price_95th_percentile,
        "simulation_bias": sim_result.simulation_bias,
        "scenarios": [
            {
                "label": s.label,
                "name": s.name,
                "probability": round(s.probability, 4),
                "expected_price": round(s.expected_price, 2),
                "price_range": list(s.price_range),
                "key_risks": s.key_risks,
                "description": s.description,
            }
            for s in scenarios.scenarios
        ],
        "paths_sample": paths_sample,
        "details": sim_result.details,
    }


@router.get("/scenarios")
async def get_scenarios(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
):
    """Get current scenarios without re-running full simulation."""
    sym = symbol or settings.DEFAULT_SYMBOL
    df = data_engine.get_latest_features(sym, timeframe, lookback=200)

    if df.empty:
        return {"error": "No data available"}

    current_price = float(df["close"].iloc[-1])
    returns = np.diff(np.log(df["close"].values))
    returns = returns[~np.isnan(returns)]

    ctx = context_engine.analyze(df)
    beh = behavior_engine.analyze(df)

    sim_result = simulation_engine.simulate(
        current_price=current_price,
        historical_returns=returns,
        num_sims=50,  # Fewer for quick response
        forecast_steps=30,
        regime=ctx.regime,
    )

    scenarios = scenario_engine.build_scenarios(
        sim_result, ctx.context_score, beh.behavior_score, current_price
    )

    return {
        "symbol": sym,
        "dominant_scenario": scenarios.dominant_scenario,
        "confidence_spread": scenarios.confidence_spread,
        "scenarios": [
            {
                "label": s.label,
                "name": s.name,
                "probability": round(s.probability, 4),
                "expected_price": round(s.expected_price, 2),
                "description": s.description,
            }
            for s in scenarios.scenarios
        ],
    }
