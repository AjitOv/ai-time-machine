"""Analysis API endpoints – runs the full intelligence pipeline."""

import json
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import numpy as np


def _sanitize(obj):
    """Recursively convert numpy types to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(i) for i in obj]
    if isinstance(obj, (np.bool_, np.generic)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

from app.database import get_db
from app.config import settings
from app.engines.data_engine import data_engine
from app.engines.context_engine import context_engine
from app.engines.behavior_engine import behavior_engine
from app.engines.dna_engine import dna_engine, DNAEngine
from app.engines.simulation_engine import simulation_engine
from app.engines.scenario_engine import scenario_engine
from app.engines.decision_engine import decision_engine
from app.engines.uncertainty_engine import uncertainty_engine
from app.engines.risk_engine import risk_engine
from app.engines.learning_engine import learning_engine
from app.engines.meta_engine import meta_engine
from app.engines.alerts import maybe_alert
from app.models.regime_states import RegimeState

router = APIRouter()


@router.post("/run")
async def run_full_analysis(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
    db: AsyncSession = Depends(get_db),
):
    """Run the full analysis pipeline across all engines."""
    sym = symbol or settings.DEFAULT_SYMBOL

    # 1. GET DATA
    df = data_engine.get_latest_features(sym, timeframe, lookback=100)
    htf_df = data_engine.get_latest_features(sym, "4h" if timeframe != "4h" else "1h", lookback=100)

    if df.empty:
        # Try fetching first
        await data_engine.ingest_and_compute(db, sym, [timeframe])
        df = data_engine.get_latest_features(sym, timeframe, lookback=100)

    if df.empty:
        return {"error": "No data available", "symbol": sym, "timeframe": timeframe}

    # 2. CONTEXT ENGINE
    ctx = context_engine.analyze(df, htf_df if not htf_df.empty else None)

    # 3. BEHAVIOR ENGINE
    beh = behavior_engine.analyze(df, ctx.htf_bias, ctx.zone)

    # 4. DNA ENGINE
    # Build current feature vector
    latest = df.iloc[-1]
    rsi_val = float(latest["rsi_14"]) if "rsi_14" in latest and latest["rsi_14"] == latest["rsi_14"] else 50
    atr_val = float(latest["atr_14"]) if "atr_14" in latest and latest["atr_14"] == latest["atr_14"] else 0
    atr_mean = float(df["atr_14"].mean()) if "atr_14" in df else 1

    ema_alignment = 0.0
    if "ema_11" in latest and "ema_50" in latest:
        if latest["ema_11"] == latest["ema_11"] and latest["ema_50"] == latest["ema_50"]:
            ema_alignment = (float(latest["ema_11"]) - float(latest["ema_50"])) / float(latest["ema_50"]) * 100 if latest["ema_50"] != 0 else 0
            ema_alignment = max(-1, min(1, ema_alignment))

    zone_val = {"DISCOUNT": -1, "EQUILIBRIUM": 0, "PREMIUM": 1}.get(ctx.zone, 0)
    phase_val = {"RANGE": 0.2, "TREND": 0.8, "EXHAUSTION": 0.4, "CHAOTIC": 0.1}.get(ctx.phase, 0.5)

    feature_vector = DNAEngine.build_feature_vector(
        ctx.context_score, beh.behavior_score,
        rsi_val, ema_alignment,
        atr_val / atr_mean if atr_mean > 0 else 1,
        zone_val, phase_val
    )

    dna_result = await dna_engine.find_matches(db, feature_vector, sym)

    # 5. SIMULATION ENGINE
    returns = np.diff(np.log(df["close"].values))
    returns = returns[~np.isnan(returns)]

    dna_dir = dna_result.best_match.direction if dna_result.best_match else None

    sim_result = simulation_engine.simulate(
        current_price=float(df["close"].iloc[-1]),
        historical_returns=returns,
        dna_direction=dna_dir,
        dna_confidence=dna_result.dna_confidence,
        regime=ctx.regime,
    )

    # 6. SCENARIO ENGINE
    scenarios = scenario_engine.build_scenarios(
        sim_result, ctx.context_score, beh.behavior_score,
        float(df["close"].iloc[-1])
    )

    # 7. UNCERTAINTY ENGINE
    # Pre-compute a rough confidence for uncertainty evaluation
    rough_confidence = abs(ctx.context_score * 0.25 + beh.behavior_score * 0.25 +
                           dna_result.dna_confidence * 0.25 + sim_result.simulation_bias * 0.25)

    unc = uncertainty_engine.evaluate(ctx, beh, dna_result, sim_result, rough_confidence)

    # 8. DECISION ENGINE
    weights = await learning_engine.get_weights(db)
    weight_map = {
        "context": weights.get("context_weight", settings.CONTEXT_WEIGHT),
        "behavior": weights.get("behavior_weight", settings.BEHAVIOR_WEIGHT),
        "dna": weights.get("dna_weight", settings.DNA_WEIGHT),
        "simulation": weights.get("simulation_weight", settings.SIMULATION_WEIGHT),
    }

    decision = decision_engine.decide(
        df, ctx, beh, dna_result, sim_result, scenarios,
        uncertainty=unc.uncertainty_score, weights=weight_map
    )

    # 9. RISK ENGINE
    risk_result = await risk_engine.evaluate(
        db, decision.confidence, decision.risk_reward, sym
    )

    # Apply risk gate
    if not risk_result.is_allowed and decision.direction != "NO_TRADE":
        decision.direction = "NO_TRADE"
        decision.rejected_reasons.extend(risk_result.reasons)

    # 10. META ENGINE
    meta = await meta_engine.evaluate(db, sym)

    # 11. LOG TRADE
    trade = await learning_engine.log_trade(
        db, sym, timeframe,
        direction=decision.direction,
        entry_price=decision.entry_price,
        stop_loss=decision.stop_loss,
        take_profit=decision.take_profit,
        confidence=decision.confidence,
        context_score=ctx.context_score,
        behavior_score=beh.behavior_score,
        dna_confidence=dna_result.dna_confidence,
        simulation_bias=sim_result.simulation_bias,
        uncertainty=unc.uncertainty_score,
        feature_snapshot={"vector": feature_vector, "rsi": rsi_val, "atr_ratio": atr_val / atr_mean if atr_mean > 0 else 1},
        dna_id=dna_result.best_match.dna_id if dna_result.best_match else None,
    )

    # 12. LOG REGIME STATE
    regime_state = RegimeState(
        timestamp=datetime.utcnow(),
        symbol=sym,
        timeframe=timeframe,
        regime=ctx.regime,
        phase=ctx.phase,
        htf_bias=ctx.htf_bias,
        context_score=ctx.context_score,
        trade_permission=1 if ctx.trade_permission else 0,
        equilibrium=ctx.equilibrium,
        zone=ctx.zone,
    )
    db.add(regime_state)

    # Build response
    response = _sanitize({
        "symbol": sym,
        "timeframe": timeframe,
        "timestamp": datetime.utcnow().isoformat(),
        "current_price": round(float(df["close"].iloc[-1]), 2),
        "trade_id": trade.trade_id,
        "context": {
            "phase": ctx.phase,
            "regime": ctx.regime,
            "htf_bias": ctx.htf_bias,
            "zone": ctx.zone,
            "equilibrium": round(ctx.equilibrium, 2),
            "context_score": round(ctx.context_score, 4),
            "trade_permission": ctx.trade_permission,
        },
        "behavior": {
            "behavior_score": round(beh.behavior_score, 4),
            "pattern_signature": beh.pattern_signature,
            "patterns": [
                {"name": p.name, "direction": p.direction, "strength": round(p.strength, 4)}
                for p in beh.patterns
            ],
            "confluence_count": beh.confluence_count,
        },
        "dna": {
            "dna_confidence": round(dna_result.dna_confidence, 4),
            "best_match": {
                "dna_id": dna_result.best_match.dna_id,
                "similarity": round(dna_result.best_match.similarity, 4),
                "direction": dna_result.best_match.direction,
                "win_rate": round(dna_result.best_match.win_rate, 4),
                "total_trades": dna_result.best_match.total_trades,
            } if dna_result.best_match else None,
            "matches_found": dna_result.details.get("matches_found", 0),
        },
        "simulation": {
            "bullish_probability": sim_result.bullish_probability,
            "bearish_probability": sim_result.bearish_probability,
            "neutral_probability": sim_result.neutral_probability,
            "mean_final_price": sim_result.mean_final_price,
            "price_range": [sim_result.price_5th_percentile, sim_result.price_95th_percentile],
            "simulation_bias": sim_result.simulation_bias,
        },
        "scenarios": [
            {
                "label": s.label,
                "name": s.name,
                "probability": round(s.probability, 4),
                "expected_price": round(s.expected_price, 2),
                "key_risks": s.key_risks,
                "description": s.description,
            }
            for s in scenarios.scenarios
        ],
        "decision": {
            "direction": decision.direction,
            "entry_price": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "confidence": decision.confidence,
            "final_score": decision.final_score,
            "risk_reward": decision.risk_reward,
            "reasons": decision.reasons,
            "rejected_reasons": decision.rejected_reasons,
        },
        "uncertainty": {
            "score": unc.uncertainty_score,
            "signal_agreement": unc.signal_agreement,
            "simulation_stability": unc.simulation_stability,
            "should_reject": unc.should_reject,
            "reasons": unc.reasons,
        },
        "risk": {
            "position_size_pct": risk_result.position_size_pct,
            "is_allowed": risk_result.is_allowed,
            "daily_risk_used": risk_result.daily_risk_used,
            "consecutive_losses": risk_result.consecutive_losses,
            "reasons": risk_result.reasons,
        },
        "meta": {
            "health_status": meta.health_status,
            "performance_trend": meta.performance_trend,
            "regime_stable": meta.regime_stable,
            "overfitting_risk": meta.overfitting_risk,
            "recommended_actions": meta.recommended_actions,
        },
        "weights": weight_map,
    })

    # Fire-and-forget alert if the decision is actionable.
    # Done after _sanitize so the payload sent matches what the API returns.
    try:
        await maybe_alert({
            "symbol": response["symbol"],
            "timeframe": response["timeframe"],
            "current_price": response["current_price"],
            "decision": response["decision"],
            "context": response["context"],
        })
    except Exception as e:
        # Never let an alert failure break the analysis response.
        import logging
        logging.getLogger(__name__).warning(f"Alert dispatch failed: {e}")

    return response


@router.get("/context")
async def get_context(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
):
    """Get current context/regime state."""
    sym = symbol or settings.DEFAULT_SYMBOL
    df = data_engine.get_latest_features(sym, timeframe, lookback=100)
    if df.empty:
        return {"error": "No data available"}

    ctx = context_engine.analyze(df)
    return {
        "phase": ctx.phase, "regime": ctx.regime,
        "htf_bias": ctx.htf_bias, "zone": ctx.zone,
        "equilibrium": round(ctx.equilibrium, 2),
        "context_score": round(ctx.context_score, 4),
        "trade_permission": ctx.trade_permission,
        "details": ctx.details,
    }


@router.get("/behavior")
async def get_behavior(
    symbol: str = Query(default=None),
    timeframe: str = Query(default="1h"),
):
    """Get current behavioral patterns."""
    sym = symbol or settings.DEFAULT_SYMBOL
    df = data_engine.get_latest_features(sym, timeframe, lookback=100)
    if df.empty:
        return {"error": "No data available"}

    beh = behavior_engine.analyze(df)
    return {
        "behavior_score": round(beh.behavior_score, 4),
        "pattern_signature": beh.pattern_signature,
        "patterns": [
            {"name": p.name, "direction": p.direction, "strength": round(p.strength, 4),
             "details": p.details}
            for p in beh.patterns
        ],
        "confluence_count": beh.confluence_count,
    }


@router.get("/decision")
async def get_latest_decision(
    db: AsyncSession = Depends(get_db),
):
    """Get the latest trade decision from history."""
    from sqlalchemy import select
    from app.models.trades import Trade

    result = await db.execute(
        select(Trade).order_by(Trade.timestamp.desc()).limit(1)
    )
    trade = result.scalar_one_or_none()

    if not trade:
        return {"message": "No decisions recorded yet"}

    return trade.to_dict()
