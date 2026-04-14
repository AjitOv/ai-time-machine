"""
Meta-Intelligence Engine – the system evaluates itself.

Detects:
- Performance degradation
- Regime changes
- Overfitting indicators

Actions:
- Reduce trading frequency
- Adjust thresholds
- Trigger recalibration
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

import numpy as np
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.trades import Trade
from app.models.performance_logs import PerformanceLog
from app.models.regime_states import RegimeState

logger = logging.getLogger(__name__)


@dataclass
class MetaResult:
    """Output of the Meta-Intelligence Engine."""
    health_status: str          # HEALTHY, DEGRADED, CRITICAL
    performance_trend: str      # IMPROVING, STABLE, DECLINING
    regime_stable: bool
    overfitting_risk: float     # 0 to 1
    recommended_actions: List[str]
    adjusted_thresholds: dict
    details: dict


class MetaEngine:
    """System self-evaluation and adaptation."""

    async def evaluate(self, db: AsyncSession, symbol: str) -> MetaResult:
        """Run meta-intelligence evaluation."""

        perf_trend = await self._assess_performance_trend(db, symbol)
        regime_stable = await self._check_regime_stability(db, symbol)
        overfit_risk = await self._estimate_overfitting(db, symbol)

        # Determine health status
        actions = []
        adjusted_thresholds = {}

        if perf_trend == "DECLINING":
            actions.append("Reduce trading frequency")
            actions.append("Increase confidence threshold")
            adjusted_thresholds["dna_confidence_threshold"] = min(
                0.9, settings.DNA_CONFIDENCE_THRESHOLD + 0.1
            )
            adjusted_thresholds["simulation_probability_threshold"] = min(
                0.8, settings.SIMULATION_PROBABILITY_THRESHOLD + 0.05
            )

        if not regime_stable:
            actions.append("Regime shift detected – consider recalibration")
            adjusted_thresholds["uncertainty_max_threshold"] = max(
                0.2, settings.UNCERTAINTY_MAX_THRESHOLD - 0.1
            )

        if overfit_risk > 0.6:
            actions.append("High overfitting risk – decay weak DNA patterns")
            actions.append("Reduce learning rate")

        # Health status
        if perf_trend == "DECLINING" and not regime_stable:
            health = "CRITICAL"
        elif perf_trend == "DECLINING" or not regime_stable or overfit_risk > 0.5:
            health = "DEGRADED"
        else:
            health = "HEALTHY"

        return MetaResult(
            health_status=health,
            performance_trend=perf_trend,
            regime_stable=regime_stable,
            overfitting_risk=round(overfit_risk, 4),
            recommended_actions=actions,
            adjusted_thresholds=adjusted_thresholds,
            details={
                "symbol": symbol,
                "evaluated_at": datetime.utcnow().isoformat(),
            }
        )

    # ──────────────────────────────────────────────
    # PERFORMANCE TREND
    # ──────────────────────────────────────────────

    async def _assess_performance_trend(self, db: AsyncSession, symbol: str) -> str:
        """Assess if performance is improving, stable, or declining."""
        result = await db.execute(
            select(PerformanceLog)
            .where(PerformanceLog.metric_name == "win_rate_20")
            .order_by(PerformanceLog.timestamp.desc())
            .limit(10)
        )
        logs = result.scalars().all()

        if len(logs) < 3:
            return "STABLE"  # Not enough data

        values = [log.value for log in reversed(logs)]

        # Simple trend: compare first half vs second half
        mid = len(values) // 2
        first_half = np.mean(values[:mid])
        second_half = np.mean(values[mid:])

        if second_half > first_half * 1.1:
            return "IMPROVING"
        elif second_half < first_half * 0.85:
            return "DECLINING"
        else:
            return "STABLE"

    # ──────────────────────────────────────────────
    # REGIME STABILITY
    # ──────────────────────────────────────────────

    async def _check_regime_stability(self, db: AsyncSession, symbol: str) -> bool:
        """Check if market regime has been stable recently."""
        result = await db.execute(
            select(RegimeState)
            .where(RegimeState.symbol == symbol)
            .order_by(RegimeState.timestamp.desc())
            .limit(10)
        )
        states = result.scalars().all()

        if len(states) < 3:
            return True  # Assume stable with little data

        regimes = [s.regime for s in states]
        # Count unique regimes
        unique = len(set(regimes))

        # More than 3 regime changes in 10 observations = unstable
        return unique <= 3

    # ──────────────────────────────────────────────
    # OVERFITTING ESTIMATION
    # ──────────────────────────────────────────────

    async def _estimate_overfitting(self, db: AsyncSession, symbol: str) -> float:
        """Estimate overfitting risk based on recent vs overall performance gap."""
        # Recent win rate
        result = await db.execute(
            select(Trade)
            .where(and_(
                Trade.symbol == symbol,
                Trade.outcome.in_(["WIN", "LOSS"]),
            ))
            .order_by(Trade.timestamp.desc())
            .limit(10)
        )
        recent = result.scalars().all()

        # All-time win rate
        result_all = await db.execute(
            select(Trade)
            .where(and_(
                Trade.symbol == symbol,
                Trade.outcome.in_(["WIN", "LOSS"]),
            ))
        )
        all_trades = result_all.scalars().all()

        if len(recent) < 5 or len(all_trades) < 10:
            return 0.0  # Not enough data to assess

        recent_wr = sum(1 for t in recent if t.outcome == "WIN") / len(recent)
        all_wr = sum(1 for t in all_trades if t.outcome == "WIN") / len(all_trades)

        # Large gap between recent and overall = potential overfit
        gap = abs(recent_wr - all_wr)
        return min(1.0, gap * 3)  # Scale gap to 0-1


# Singleton
meta_engine = MetaEngine()
