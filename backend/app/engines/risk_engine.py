"""
Risk Engine – manages position sizing and risk limits.

Implements:
- Dynamic position sizing based on confidence
- Daily risk limits
- Auto-stop after consecutive losses
- Risk-reward optimization
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.trades import Trade

logger = logging.getLogger(__name__)


@dataclass
class RiskResult:
    """Output of the Risk Engine."""
    position_size_pct: float    # % of capital to risk
    is_allowed: bool
    daily_risk_used: float      # % of daily limit used
    consecutive_losses: int
    reasons: list
    details: dict


class RiskEngine:
    """Manages risk parameters and position sizing."""

    async def evaluate(
        self,
        db: AsyncSession,
        confidence: float,
        risk_reward: float,
        symbol: str,
        account_balance: float = 100000.0,
    ) -> RiskResult:
        """Evaluate risk and compute position size."""

        reasons = []
        is_allowed = True

        # ── CONSECUTIVE LOSSES ──
        consecutive_losses = await self._count_consecutive_losses(db, symbol)
        if consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            is_allowed = False
            reasons.append(f"Auto-stop: {consecutive_losses} consecutive losses "
                           f"(max {settings.MAX_CONSECUTIVE_LOSSES})")

        # ── DAILY RISK LIMIT ──
        daily_risk = await self._compute_daily_risk(db, symbol)
        if daily_risk >= settings.MAX_DAILY_RISK_PCT:
            is_allowed = False
            reasons.append(f"Daily risk limit reached: {daily_risk:.1f}% / {settings.MAX_DAILY_RISK_PCT:.1f}%")

        # ── RISK-REWARD CHECK ──
        if risk_reward < settings.MIN_RISK_REWARD:
            is_allowed = False
            reasons.append(f"Risk-reward too low: {risk_reward:.1f} < {settings.MIN_RISK_REWARD:.1f}")

        # ── DYNAMIC POSITION SIZING ──
        # Higher confidence → larger position
        base_size = settings.BASE_POSITION_SIZE_PCT
        confidence_multiplier = 0.5 + confidence  # 0.5x to 1.5x
        position_size = base_size * confidence_multiplier

        # Cap at remaining daily risk
        remaining_risk = max(0, settings.MAX_DAILY_RISK_PCT - daily_risk)
        position_size = min(position_size, remaining_risk)

        if not is_allowed:
            position_size = 0.0

        return RiskResult(
            position_size_pct=round(position_size, 4),
            is_allowed=is_allowed,
            daily_risk_used=round(daily_risk, 4),
            consecutive_losses=consecutive_losses,
            reasons=reasons,
            details={
                "confidence": confidence,
                "risk_reward": risk_reward,
                "base_size": base_size,
                "confidence_multiplier": round(confidence_multiplier, 2),
                "remaining_daily_risk": round(remaining_risk, 4),
            }
        )

    async def _count_consecutive_losses(self, db: AsyncSession, symbol: str) -> int:
        """Count current streak of consecutive losses."""
        result = await db.execute(
            select(Trade)
            .where(and_(Trade.symbol == symbol, Trade.outcome.in_(["WIN", "LOSS"])))
            .order_by(Trade.timestamp.desc())
            .limit(settings.MAX_CONSECUTIVE_LOSSES + 1)
        )
        trades = result.scalars().all()

        count = 0
        for trade in trades:
            if trade.outcome == "LOSS":
                count += 1
            else:
                break
        return count

    async def _compute_daily_risk(self, db: AsyncSession, symbol: str) -> float:
        """Compute total risk deployed today."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        result = await db.execute(
            select(func.count(Trade.id))
            .where(and_(
                Trade.symbol == symbol,
                Trade.timestamp >= today_start,
                Trade.direction.in_(["BUY", "SELL"]),
            ))
        )
        trade_count = result.scalar() or 0

        # Approximate: each trade uses base position size
        return trade_count * settings.BASE_POSITION_SIZE_PCT


# Singleton
risk_engine = RiskEngine()
