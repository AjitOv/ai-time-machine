"""
Self-Learning Engine – reinforcement-based adaptation.

Implements:
- Trade logging with full feature capture
- Performance tracking
- Adaptive weight updates
- Reinforcement learning (reward/penalty)
- Pattern evolution
"""

import json
import logging
import math
import uuid
from datetime import datetime
from typing import Dict, Optional

import numpy as np
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.trades import Trade
from app.models.model_weights import ModelWeight
from app.models.performance_logs import PerformanceLog

logger = logging.getLogger(__name__)

# Default engine weights
DEFAULT_WEIGHTS = {
    "context_weight": settings.CONTEXT_WEIGHT,
    "behavior_weight": settings.BEHAVIOR_WEIGHT,
    "dna_weight": settings.DNA_WEIGHT,
    "simulation_weight": settings.SIMULATION_WEIGHT,
}


class LearningEngine:
    """Self-learning system with reinforcement signal."""

    # ──────────────────────────────────────────────
    # TRADE LOGGING
    # ──────────────────────────────────────────────

    async def log_trade(
        self,
        db: AsyncSession,
        symbol: str,
        timeframe: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        context_score: float,
        behavior_score: float,
        dna_confidence: float,
        simulation_bias: float,
        uncertainty: float,
        feature_snapshot: dict,
        dna_id: Optional[str] = None,
    ) -> Trade:
        """Log a trade decision with full feature capture."""
        trade_id = f"T_{uuid.uuid4().hex[:10]}"
        trade = Trade(
            trade_id=trade_id,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=datetime.utcnow(),
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            outcome="PENDING" if direction != "NO_TRADE" else "SKIPPED",
            confidence=confidence,
            context_score=context_score,
            behavior_score=behavior_score,
            dna_confidence=dna_confidence,
            simulation_bias=simulation_bias,
            uncertainty=uncertainty,
            feature_snapshot=json.dumps(feature_snapshot),
            dna_id=dna_id,
            is_active=direction != "NO_TRADE",
        )
        db.add(trade)
        await db.flush()
        logger.info(f"Logged trade {trade_id}: {direction} @ {entry_price}")
        return trade

    async def update_trade_outcome(
        self,
        db: AsyncSession,
        trade_id: str,
        outcome: str,
        exit_price: float,
    ):
        """Update a trade with its outcome."""
        result = await db.execute(
            select(Trade).where(Trade.trade_id == trade_id)
        )
        trade = result.scalar_one_or_none()
        if not trade:
            logger.warning(f"Trade {trade_id} not found")
            return

        trade.outcome = outcome
        trade.exit_price = exit_price
        trade.is_active = False

        # Calculate PnL
        if trade.direction == "BUY":
            trade.pnl = exit_price - trade.entry_price
        elif trade.direction == "SELL":
            trade.pnl = trade.entry_price - exit_price

        # Calculate realized RR
        if trade.stop_loss and trade.entry_price:
            risk = abs(trade.entry_price - trade.stop_loss)
            if risk > 0:
                trade.risk_reward = abs(trade.pnl) / risk if trade.pnl else 0

        await db.flush()
        logger.info(f"Updated trade {trade_id}: {outcome}, PnL={trade.pnl:.2f}")

        # Trigger learning after outcome
        await self._apply_reinforcement(db, trade)

    # ──────────────────────────────────────────────
    # REINFORCEMENT LEARNING
    # ──────────────────────────────────────────────

    async def _apply_reinforcement(self, db: AsyncSession, trade: Trade):
        """Apply reinforcement signal to adapt weights."""
        if trade.outcome not in ("WIN", "LOSS"):
            return

        # Reward/penalty signal
        reward = 1.0 if trade.outcome == "WIN" else -1.0

        # Feature importance: which engine scores contributed most?
        scores = {
            "context_weight": trade.context_score or 0,
            "behavior_weight": trade.behavior_score or 0,
            "dna_weight": trade.dna_confidence or 0,
            "simulation_weight": trade.simulation_bias or 0,
        }

        # Increase weights for engines that were aligned with outcome
        lr = settings.LEARNING_RATE
        for weight_name, engine_score in scores.items():
            aligned = (engine_score > 0 and trade.direction == "BUY") or \
                      (engine_score < 0 and trade.direction == "SELL")

            if trade.outcome == "WIN" and aligned:
                delta = lr * abs(engine_score)  # Reward aligned engines
            elif trade.outcome == "LOSS" and aligned:
                delta = -lr * abs(engine_score)  # Penalize false signals
            else:
                delta = 0

            await self._update_weight(db, weight_name, delta)

        # Log performance
        await self._log_performance(db, trade)

    async def _update_weight(self, db: AsyncSession, weight_name: str, delta: float):
        """Update a model weight with bounds checking."""
        result = await db.execute(
            select(ModelWeight).where(ModelWeight.weight_name == weight_name)
        )
        weight = result.scalar_one_or_none()

        if weight:
            new_val = weight.value + delta
            # Clamp between 0.05 and 0.6
            weight.value = max(0.05, min(0.6, new_val))
            weight.last_updated = datetime.utcnow()
            weight.update_count += 1
        else:
            # Create weight
            default_val = DEFAULT_WEIGHTS.get(weight_name, 0.25)
            weight = ModelWeight(
                weight_name=weight_name,
                value=max(0.05, min(0.6, default_val + delta)),
                last_updated=datetime.utcnow(),
                update_count=1,
                description=f"Adaptive weight for {weight_name}",
            )
            db.add(weight)

        await db.flush()

    async def _log_performance(self, db: AsyncSession, trade: Trade):
        """Log performance metrics."""
        # Rolling win rate (last 20 trades)
        result = await db.execute(
            select(Trade)
            .where(and_(
                Trade.symbol == trade.symbol,
                Trade.outcome.in_(["WIN", "LOSS"]),
            ))
            .order_by(Trade.timestamp.desc())
            .limit(20)
        )
        recent_trades = result.scalars().all()

        if recent_trades:
            wins = sum(1 for t in recent_trades if t.outcome == "WIN")
            win_rate = wins / len(recent_trades)

            log = PerformanceLog(
                timestamp=datetime.utcnow(),
                metric_name="win_rate_20",
                value=win_rate,
                window="last_20",
            )
            db.add(log)

            # Average RR
            rrs = [t.risk_reward for t in recent_trades if t.risk_reward and t.risk_reward > 0]
            if rrs:
                avg_rr = sum(rrs) / len(rrs)
                log_rr = PerformanceLog(
                    timestamp=datetime.utcnow(),
                    metric_name="avg_rr_20",
                    value=avg_rr,
                    window="last_20",
                )
                db.add(log_rr)

            await db.flush()

    # ──────────────────────────────────────────────
    # GET CURRENT WEIGHTS
    # ──────────────────────────────────────────────

    async def get_weights(self, db: AsyncSession) -> Dict[str, float]:
        """Get current engine weights, initializing defaults if needed."""
        result = await db.execute(select(ModelWeight))
        weights = result.scalars().all()

        weight_dict = {w.weight_name: w.value for w in weights}

        # Initialize missing weights
        for name, default in DEFAULT_WEIGHTS.items():
            if name not in weight_dict:
                w = ModelWeight(
                    weight_name=name,
                    value=default,
                    last_updated=datetime.utcnow(),
                    update_count=0,
                    description=f"Adaptive weight for {name}",
                )
                db.add(w)
                weight_dict[name] = default

        await db.flush()

        # Normalize to sum to 1
        total = sum(weight_dict.values())
        if total > 0:
            weight_dict = {k: v / total for k, v in weight_dict.items()}

        return weight_dict

    # ──────────────────────────────────────────────
    # PERFORMANCE STATS
    # ──────────────────────────────────────────────

    async def get_performance_stats(self, db: AsyncSession, symbol: str) -> dict:
        """Get overall performance statistics."""
        result = await db.execute(
            select(Trade).where(and_(
                Trade.symbol == symbol,
                Trade.outcome.in_(["WIN", "LOSS"]),
            ))
        )
        trades = result.scalars().all()

        if not trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "avg_rr": 0,
                "total_pnl": 0,
                "best_trade": 0,
                "worst_trade": 0,
            }

        wins = sum(1 for t in trades if t.outcome == "WIN")
        losses = sum(1 for t in trades if t.outcome == "LOSS")
        pnls = [t.pnl for t in trades if t.pnl is not None]
        rrs = [t.risk_reward for t in trades if t.risk_reward and t.risk_reward > 0]

        return {
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(trades), 4) if trades else 0,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "avg_rr": round(sum(rrs) / len(rrs), 2) if rrs else 0,
            "total_pnl": round(sum(pnls), 2) if pnls else 0,
            "best_trade": round(max(pnls), 2) if pnls else 0,
            "worst_trade": round(min(pnls), 2) if pnls else 0,
        }


# Singleton
learning_engine = LearningEngine()
