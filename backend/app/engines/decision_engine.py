"""
Decision Engine – the final arbiter.

Combines all engine outputs into a single trade decision:
- Direction (BUY / SELL / NO_TRADE)
- Entry, Stop Loss, Take Profit
- Confidence %
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.config import settings
from app.engines.context_engine import ContextResult
from app.engines.behavior_engine import BehaviorResult
from app.engines.dna_engine import DNAResult
from app.engines.simulation_engine import SimulationResult
from app.engines.scenario_engine import ScenarioResult

logger = logging.getLogger(__name__)


@dataclass
class TradeDecision:
    """Final trade decision output."""
    direction: str        # BUY, SELL, NO_TRADE
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float     # 0 to 1
    final_score: float    # -1 to +1
    risk_reward: float
    reasons: list
    rejected_reasons: list
    details: dict


class DecisionEngine:
    """Combines all engine outputs into a final trade decision."""

    def decide(
        self,
        df: pd.DataFrame,
        context: ContextResult,
        behavior: BehaviorResult,
        dna: DNAResult,
        simulation: SimulationResult,
        scenarios: ScenarioResult,
        uncertainty: float = 0.0,
        weights: Optional[dict] = None,
    ) -> TradeDecision:
        """Make a trade decision based on all engine outputs."""

        if df.empty:
            return self._no_trade("No market data available")

        current_price = float(df["close"].iloc[-1])
        atr = float(df["atr_14"].iloc[-1]) if "atr_14" in df else current_price * 0.01

        # ── COMPUTE FINAL SCORE ──
        w = weights or {
            "context": settings.CONTEXT_WEIGHT,
            "behavior": settings.BEHAVIOR_WEIGHT,
            "dna": settings.DNA_WEIGHT,
            "simulation": settings.SIMULATION_WEIGHT,
        }

        # Normalize DNA confidence to -1..+1 based on direction
        dna_directional = 0.0
        if dna.best_match:
            sign = 1.0 if dna.best_match.direction == "BUY" else -1.0
            dna_directional = sign * dna.dna_confidence

        final_score = (
            w["context"] * context.context_score
            + w["behavior"] * behavior.behavior_score
            + w["dna"] * dna_directional
            + w["simulation"] * simulation.simulation_bias
        )

        # ── GATE CHECKS ──
        rejected_reasons = []
        reasons = []

        # Gate 1: Context must allow trading
        if not context.trade_permission:
            rejected_reasons.append(f"Context denied trade: phase={context.phase}, regime={context.regime}")

        # Gate 2: DNA confidence threshold
        if dna.dna_confidence < settings.DNA_CONFIDENCE_THRESHOLD and dna.best_match:
            rejected_reasons.append(f"DNA confidence too low: {dna.dna_confidence:.2f} < {settings.DNA_CONFIDENCE_THRESHOLD}")

        # Gate 3: Simulation probability
        dominant_prob = max(simulation.bullish_probability, simulation.bearish_probability)
        if dominant_prob < settings.SIMULATION_PROBABILITY_THRESHOLD:
            rejected_reasons.append(f"Simulation probability too low: {dominant_prob:.2%} < {settings.SIMULATION_PROBABILITY_THRESHOLD:.0%}")

        # Gate 4: Uncertainty check
        if uncertainty > settings.UNCERTAINTY_MAX_THRESHOLD:
            rejected_reasons.append(f"Uncertainty too high: {uncertainty:.2f} > {settings.UNCERTAINTY_MAX_THRESHOLD}")

        # Gate 5: Score must be decisive
        if abs(final_score) < 0.15:
            rejected_reasons.append(f"Score not decisive: {final_score:.3f}")

        # ── DETERMINE DIRECTION ──
        if rejected_reasons:
            return TradeDecision(
                direction="NO_TRADE",
                entry_price=current_price,
                stop_loss=0.0,
                take_profit=0.0,
                confidence=0.0,
                final_score=final_score,
                risk_reward=0.0,
                reasons=[],
                rejected_reasons=rejected_reasons,
                details=self._build_details(context, behavior, dna, simulation, final_score, uncertainty)
            )

        direction = "BUY" if final_score > 0 else "SELL"

        # ── COMPUTE LEVELS ──
        sl_distance = atr * 1.5  # 1.5 ATR stop loss
        tp_distance = sl_distance * settings.MIN_RISK_REWARD  # Minimum 2:1 RR

        if direction == "BUY":
            entry = current_price
            stop_loss = entry - sl_distance
            take_profit = entry + tp_distance
        else:
            entry = current_price
            stop_loss = entry + sl_distance
            take_profit = entry - tp_distance

        risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0

        # ── CONFIDENCE ──
        confidence = min(1.0, (abs(final_score) + dominant_prob) / 2)

        # ── REASONS ──
        reasons = self._build_reasons(context, behavior, dna, simulation, direction)

        return TradeDecision(
            direction=direction,
            entry_price=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            confidence=round(confidence, 4),
            final_score=round(final_score, 4),
            risk_reward=round(risk_reward, 2),
            reasons=reasons,
            rejected_reasons=[],
            details=self._build_details(context, behavior, dna, simulation, final_score, uncertainty)
        )

    def _no_trade(self, reason: str) -> TradeDecision:
        return TradeDecision(
            direction="NO_TRADE", entry_price=0, stop_loss=0, take_profit=0,
            confidence=0, final_score=0, risk_reward=0,
            reasons=[], rejected_reasons=[reason], details={}
        )

    @staticmethod
    def _build_reasons(context, behavior, dna, simulation, direction) -> list:
        reasons = []
        if context.context_score > 0.2 and direction == "BUY":
            reasons.append(f"Context bullish ({context.phase} phase, {context.htf_bias} HTF)")
        elif context.context_score < -0.2 and direction == "SELL":
            reasons.append(f"Context bearish ({context.phase} phase, {context.htf_bias} HTF)")

        if behavior.patterns:
            aligned = [p for p in behavior.patterns
                       if (p.direction == "BULLISH" and direction == "BUY")
                       or (p.direction == "BEARISH" and direction == "SELL")]
            if aligned:
                reasons.append(f"Behavioral patterns detected: {', '.join(p.name for p in aligned)}")

        if dna.best_match:
            reasons.append(f"DNA match: {dna.best_match.pattern_signature} "
                           f"(WR={dna.best_match.win_rate:.0%}, N={dna.best_match.total_trades})")

        if direction == "BUY":
            reasons.append(f"Simulation: {simulation.bullish_probability:.0%} bullish probability")
        else:
            reasons.append(f"Simulation: {simulation.bearish_probability:.0%} bearish probability")

        return reasons

    @staticmethod
    def _build_details(context, behavior, dna, simulation, score, uncertainty) -> dict:
        return {
            "context_score": context.context_score,
            "behavior_score": behavior.behavior_score,
            "dna_confidence": dna.dna_confidence,
            "simulation_bias": simulation.simulation_bias,
            "final_score": score,
            "uncertainty": uncertainty,
            "phase": context.phase,
            "regime": context.regime,
            "htf_bias": context.htf_bias,
            "zone": context.zone,
            "patterns": [p.name for p in behavior.patterns],
            "dominant_scenario": None,
        }


# Singleton
decision_engine = DecisionEngine()
