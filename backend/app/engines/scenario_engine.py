"""
Scenario Engine – combines simulation outputs into structured scenarios.

Always presents multiple futures:
- Scenario A: Bullish
- Scenario B: Bearish
- Scenario C: Neutral
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.engines.simulation_engine import SimulationResult

logger = logging.getLogger(__name__)


@dataclass
class Scenario:
    """A single future scenario."""
    label: str           # "BULLISH", "BEARISH", "NEUTRAL"
    name: str            # Human readable name
    probability: float   # 0 to 1
    expected_price: float
    price_range: tuple   # (low, high)
    key_risks: List[str]
    description: str


@dataclass
class ScenarioResult:
    """Output of the Scenario Engine."""
    scenarios: List[Scenario]
    dominant_scenario: str
    confidence_spread: float  # Difference between top and second scenario
    details: dict


class ScenarioEngine:
    """Constructs structured scenarios from simulation and analysis data."""

    def build_scenarios(
        self,
        sim_result: SimulationResult,
        context_score: float = 0.0,
        behavior_score: float = 0.0,
        current_price: float = 0.0,
    ) -> ScenarioResult:
        """Build 3 structured scenarios from simulation output."""

        # ── SCENARIO A: BULLISH ──
        bullish = Scenario(
            label="BULLISH",
            name="Upside Continuation",
            probability=sim_result.bullish_probability,
            expected_price=sim_result.price_95th_percentile,
            price_range=(current_price, sim_result.price_95th_percentile),
            key_risks=self._bullish_risks(sim_result, context_score),
            description=self._bullish_description(sim_result, context_score, behavior_score),
        )

        # ── SCENARIO B: BEARISH ──
        bearish = Scenario(
            label="BEARISH",
            name="Downside Reversal",
            probability=sim_result.bearish_probability,
            expected_price=sim_result.price_5th_percentile,
            price_range=(sim_result.price_5th_percentile, current_price),
            key_risks=self._bearish_risks(sim_result, context_score),
            description=self._bearish_description(sim_result, context_score, behavior_score),
        )

        # ── SCENARIO C: NEUTRAL ──
        neutral = Scenario(
            label="NEUTRAL",
            name="Sideways Consolidation",
            probability=sim_result.neutral_probability,
            expected_price=sim_result.median_final_price,
            price_range=(sim_result.price_5th_percentile, sim_result.price_95th_percentile),
            key_risks=["Range-bound chop", "No clear directional edge"],
            description="Market likely to consolidate within current range. "
                        "No significant directional move expected.",
        )

        scenarios = sorted([bullish, bearish, neutral],
                           key=lambda s: s.probability, reverse=True)

        dominant = scenarios[0].label
        spread = scenarios[0].probability - scenarios[1].probability if len(scenarios) > 1 else 0

        return ScenarioResult(
            scenarios=scenarios,
            dominant_scenario=dominant,
            confidence_spread=round(spread, 4),
            details={
                "bullish_prob": sim_result.bullish_probability,
                "bearish_prob": sim_result.bearish_probability,
                "neutral_prob": sim_result.neutral_probability,
            }
        )

    # ──────────────────────────────────────────────
    # RISK NARRATIVES
    # ──────────────────────────────────────────────

    @staticmethod
    def _bullish_risks(sim: SimulationResult, ctx_score: float) -> List[str]:
        risks = []
        if sim.stop_loss_risk > 0.3:
            risks.append(f"Stop loss risk at {sim.stop_loss_risk:.0%}")
        if ctx_score < 0:
            risks.append("Context engine shows bearish bias")
        if sim.bullish_probability < 0.5:
            risks.append("Less than 50% probability of upside")
        if not risks:
            risks.append("Standard market risk applies")
        return risks

    @staticmethod
    def _bearish_risks(sim: SimulationResult, ctx_score: float) -> List[str]:
        risks = []
        if sim.stop_loss_risk > 0.3:
            risks.append(f"Stop loss risk at {sim.stop_loss_risk:.0%}")
        if ctx_score > 0:
            risks.append("Context engine shows bullish bias")
        if sim.bearish_probability < 0.5:
            risks.append("Less than 50% probability of downside")
        if not risks:
            risks.append("Standard market risk applies")
        return risks

    @staticmethod
    def _bullish_description(sim: SimulationResult, ctx: float, beh: float) -> str:
        strength = "strong" if sim.bullish_probability > 0.6 else "moderate"
        ctx_note = "with contextual support" if ctx > 0.2 else "against context"
        return (f"Price shows {strength} bullish potential {ctx_note}. "
                f"Expected upside target near {sim.price_95th_percentile:.2f}.")

    @staticmethod
    def _bearish_description(sim: SimulationResult, ctx: float, beh: float) -> str:
        strength = "strong" if sim.bearish_probability > 0.6 else "moderate"
        ctx_note = "with contextual support" if ctx < -0.2 else "against context"
        return (f"Price shows {strength} bearish potential {ctx_note}. "
                f"Expected downside target near {sim.price_5th_percentile:.2f}.")


# Singleton
scenario_engine = ScenarioEngine()
