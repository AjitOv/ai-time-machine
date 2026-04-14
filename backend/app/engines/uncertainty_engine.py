"""
Uncertainty Engine – measures model reliability.

Detects:
- Conflicting signals across engines
- Unstable predictions
- High variance in simulation outcomes
"""

import logging
from dataclasses import dataclass

import numpy as np

from app.engines.context_engine import ContextResult
from app.engines.behavior_engine import BehaviorResult
from app.engines.dna_engine import DNAResult
from app.engines.simulation_engine import SimulationResult

logger = logging.getLogger(__name__)


@dataclass
class UncertaintyResult:
    """Output of the Uncertainty Engine."""
    uncertainty_score: float    # 0 (certain) to 1 (very uncertain)
    signal_agreement: float     # 0 (all disagree) to 1 (all agree)
    simulation_stability: float # 0 (unstable) to 1 (stable)
    should_reject: bool
    reasons: list
    details: dict


class UncertaintyEngine:
    """Evaluates model reliability and detects conflicting signals."""

    def evaluate(
        self,
        context: ContextResult,
        behavior: BehaviorResult,
        dna: DNAResult,
        simulation: SimulationResult,
        confidence: float = 0.0,
    ) -> UncertaintyResult:
        """Compute uncertainty score."""

        # ── SIGNAL AGREEMENT ──
        signals = []

        # Context direction
        if context.context_score > 0.1:
            signals.append(1)
        elif context.context_score < -0.1:
            signals.append(-1)
        else:
            signals.append(0)

        # Behavior direction
        if behavior.behavior_score > 0.1:
            signals.append(1)
        elif behavior.behavior_score < -0.1:
            signals.append(-1)
        else:
            signals.append(0)

        # DNA direction
        if dna.best_match:
            signals.append(1 if dna.best_match.direction == "BUY" else -1)
        else:
            signals.append(0)

        # Simulation direction
        if simulation.simulation_bias > 0.1:
            signals.append(1)
        elif simulation.simulation_bias < -0.1:
            signals.append(-1)
        else:
            signals.append(0)

        # Agreement: how much do signals agree?
        non_zero = [s for s in signals if s != 0]
        if non_zero:
            agreement = abs(sum(non_zero)) / len(non_zero)
        else:
            agreement = 0.0

        # ── SIMULATION STABILITY ──
        # Based on spread between bullish/bearish probabilities
        prob_spread = abs(simulation.bullish_probability - simulation.bearish_probability)
        sim_stability = min(1.0, prob_spread * 2)  # Wider spread = more stable

        # Price range stability
        if simulation.price_5th_percentile > 0 and simulation.price_95th_percentile > 0:
            price_range_pct = (
                (simulation.price_95th_percentile - simulation.price_5th_percentile)
                / simulation.mean_final_price
            )
            # Narrow range = more stable
            range_stability = max(0, 1 - price_range_pct * 5)
        else:
            range_stability = 0.5

        sim_stability = (sim_stability + range_stability) / 2

        # ── CONFLICTING SIGNALS ──
        conflicts = []
        if context.context_score > 0.2 and behavior.behavior_score < -0.2:
            conflicts.append("Context bullish but behavior bearish")
        if context.context_score < -0.2 and behavior.behavior_score > 0.2:
            conflicts.append("Context bearish but behavior bullish")
        if dna.best_match and context.context_score > 0.2 and dna.best_match.direction == "SELL":
            conflicts.append("Context bullish but DNA points sell")
        if dna.best_match and context.context_score < -0.2 and dna.best_match.direction == "BUY":
            conflicts.append("Context bearish but DNA points buy")

        # ── OVERALL UNCERTAINTY ──
        uncertainty = 1.0 - (0.4 * agreement + 0.3 * sim_stability + 0.3 * (1 - len(conflicts) * 0.2))
        uncertainty = max(0.0, min(1.0, uncertainty))

        # ── REJECTION CHECK ──
        # High confidence + high uncertainty → reject
        should_reject = confidence > 0.5 and uncertainty > 0.6

        reasons = []
        if should_reject:
            reasons.append("High confidence but high uncertainty – contradictory signals")
        if conflicts:
            reasons.extend(conflicts)
        if sim_stability < 0.3:
            reasons.append("Simulation outcomes highly unstable")

        return UncertaintyResult(
            uncertainty_score=round(uncertainty, 4),
            signal_agreement=round(agreement, 4),
            simulation_stability=round(sim_stability, 4),
            should_reject=should_reject,
            reasons=reasons,
            details={
                "signals": signals,
                "conflicts": conflicts,
                "range_stability": round(range_stability, 4),
                "prob_spread": round(prob_spread, 4),
            }
        )


# Singleton
uncertainty_engine = UncertaintyEngine()
