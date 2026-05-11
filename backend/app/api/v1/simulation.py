"""Simulation API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import numpy as np

from app.database import get_db
from app.config import settings
from app.engines.data_engine import data_engine
from app.engines.dna_engine import dna_engine, DNAEngine
from app.engines.simulation_engine import simulation_engine
from app.engines.scenario_engine import scenario_engine
from app.engines.context_engine import context_engine
from app.engines.behavior_engine import behavior_engine

router = APIRouter()


_TIMEFRAME_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400,
}


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


@router.post("/forecast")
async def forecast_chart(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
    num_simulations: int = Query(default=200, ge=20, le=1000),
    forecast_steps: int = Query(default=40, ge=5, le=200),
    sample_paths: int = Query(default=30, ge=0, le=100, description="Individual paths to return for the fan"),
    db: AsyncSession = Depends(get_db),
):
    """Return a chart-ready forward forecast.

    Bands (p5/p25/p50/p75/p95) computed across all simulated paths, plus
    a downsampled handful of individual paths that the frontend draws as
    a translucent fan extending past the last candle. Drift is DNA-biased
    and σ is regime-scaled, same as the full pipeline."""
    sym = symbol or settings.DEFAULT_SYMBOL
    df = data_engine.get_latest_features(sym, timeframe, lookback=300)
    if df.empty:
        return {"error": "No data available", "symbol": sym, "timeframe": timeframe}

    current_price = float(df["close"].iloc[-1])
    last_ts_ms = int(df.index[-1].value // 10**6)  # ms
    last_ts = last_ts_ms // 1000  # unix seconds
    step_sec = _TIMEFRAME_SECONDS.get(timeframe, 3600)

    returns = np.diff(np.log(df["close"].values))
    returns = returns[~np.isnan(returns)]

    ctx = context_engine.analyze(df)
    beh = behavior_engine.analyze(df, ctx.htf_bias, ctx.zone)

    # Build a feature vector + DNA match so the simulation drift carries
    # genuine pattern bias rather than plain GBM.
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
    dna_result = await dna_engine.find_matches(db, feature_vector, sym)
    dna_dir = dna_result.best_match.direction if dna_result.best_match else None

    sim = simulation_engine.simulate(
        current_price=current_price,
        historical_returns=returns,
        num_sims=num_simulations,
        forecast_steps=forecast_steps,
        dna_direction=dna_dir,
        dna_confidence=dna_result.dna_confidence,
        regime=ctx.regime,
    )

    if sim.paths is None:
        return {"error": "Simulation produced no paths", "symbol": sym}

    paths = sim.paths  # shape: (steps+1, n_sims)

    # Compute per-step percentile bands (excluding the seed step which is just current_price)
    bands = []
    for step in range(paths.shape[0]):
        col = paths[step, :]
        t = last_ts + step * step_sec
        bands.append({
            "t": t,
            "p5":  round(float(np.percentile(col, 5)),  2),
            "p25": round(float(np.percentile(col, 25)), 2),
            "p50": round(float(np.percentile(col, 50)), 2),
            "p75": round(float(np.percentile(col, 75)), 2),
            "p95": round(float(np.percentile(col, 95)), 2),
            "mean": round(float(np.mean(col)),          2),
        })

    # Sample a handful of paths for the visual fan
    n_sample = min(sample_paths, paths.shape[1])
    if n_sample > 0:
        idx = np.linspace(0, paths.shape[1] - 1, num=n_sample, dtype=int)
        sampled = []
        for j in idx:
            series = []
            for step in range(paths.shape[0]):
                series.append({"t": last_ts + step * step_sec, "v": round(float(paths[step, j]), 2)})
            sampled.append(series)
    else:
        sampled = []

    # ── PREDICTED CANDLES ──
    # Each forecast step gets a synthetic OHLC built from the cross-section
    # of all paths: open = prior close, close = median, high = p75, low = p25.
    # This renders as "ghost candles" extending past the live chart so the
    # user literally sees what the next session is most likely to look like.
    predicted_candles = []
    prev_close = current_price
    for step in range(1, paths.shape[0]):
        col = paths[step, :]
        close_v = float(np.percentile(col, 50))
        high_v = float(np.percentile(col, 75))
        low_v = float(np.percentile(col, 25))
        open_v = prev_close
        # Ensure OHLC integrity: high ≥ max(o,c), low ≤ min(o,c)
        high_v = max(high_v, open_v, close_v)
        low_v = min(low_v, open_v, close_v)
        predicted_candles.append({
            "t": last_ts + step * step_sec,
            "open": round(open_v, 2),
            "high": round(high_v, 2),
            "low": round(low_v, 2),
            "close": round(close_v, 2),
            "direction": "UP" if close_v >= open_v else "DOWN",
        })
        prev_close = close_v

    # ── NEXT-SESSION HEADLINE ──
    # An NSE cash session ≈ 6.25 hours = roughly:
    #   1m → 375 steps   5m → 75   15m → 25   1h → 6   4h → 2   1d → 1
    session_steps_map = {"1m": 375, "5m": 75, "15m": 25, "1h": 6, "4h": 2, "1d": 1}
    sess = min(session_steps_map.get(timeframe, 6), len(predicted_candles))
    if sess > 0:
        sess_slice = paths[1:sess + 1, :]  # all paths over next-session steps
        sess_open = current_price
        sess_close = float(np.percentile(sess_slice[-1, :], 50))
        sess_high = float(np.percentile(sess_slice.max(axis=0), 75))  # 75th of per-path max
        sess_low = float(np.percentile(sess_slice.min(axis=0), 25))   # 25th of per-path min
        pct_change = (sess_close - sess_open) / sess_open * 100 if sess_open else 0.0
        direction = "UP" if pct_change > 0.1 else ("DOWN" if pct_change < -0.1 else "FLAT")
        next_session = {
            "steps": sess,
            "open": round(sess_open, 2),
            "expected_high": round(sess_high, 2),
            "expected_low": round(sess_low, 2),
            "expected_close": round(sess_close, 2),
            "expected_pct": round(pct_change, 3),
            "direction": direction,
            "label": f"Next ~{sess} {timeframe} candle{'s' if sess > 1 else ''}",
        }
    else:
        next_session = None

    # Scenario summary for label overlays
    scenarios = scenario_engine.build_scenarios(sim, ctx.context_score, beh.behavior_score, current_price)

    return {
        "symbol": sym,
        "timeframe": timeframe,
        "now": last_ts,
        "step_seconds": step_sec,
        "current_price": round(current_price, 2),
        "bands": bands,
        "paths": sampled,
        "predicted_candles": predicted_candles,
        "next_session": next_session,
        "summary": {
            "bullish_probability": sim.bullish_probability,
            "bearish_probability": sim.bearish_probability,
            "neutral_probability": sim.neutral_probability,
            "simulation_bias": sim.simulation_bias,
            "p5_final": sim.price_5th_percentile,
            "p95_final": sim.price_95th_percentile,
            "mean_final": sim.mean_final_price,
            "regime": ctx.regime,
            "phase": ctx.phase,
            "dna_direction": dna_dir,
            "dna_confidence": round(dna_result.dna_confidence, 4),
        },
        "scenarios": [
            {
                "label": s.label,
                "name": s.name,
                "probability": round(s.probability, 4),
                "expected_price": round(s.expected_price, 2),
            }
            for s in scenarios.scenarios
        ],
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
