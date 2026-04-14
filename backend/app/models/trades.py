"""Trade ORM model – logs every trade decision and its outcome."""

import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from app.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(50), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(5), nullable=False)
    timestamp = Column(DateTime, nullable=False)

    # Direction
    direction = Column(String(10), nullable=False)  # BUY, SELL, NO_TRADE

    # Price levels
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)

    # Outcome
    outcome = Column(String(10), nullable=True)  # WIN, LOSS, PENDING, SKIPPED
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True, default=0.0)
    risk_reward = Column(Float, nullable=True)

    # Scores
    confidence = Column(Float, nullable=True)
    context_score = Column(Float, nullable=True)
    behavior_score = Column(Float, nullable=True)
    dna_confidence = Column(Float, nullable=True)
    simulation_bias = Column(Float, nullable=True)
    uncertainty = Column(Float, nullable=True)

    # Features snapshot (JSON)
    feature_snapshot = Column(Text, nullable=True)

    # DNA reference
    dna_id = Column(String(50), nullable=True)

    # Flags
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<Trade {self.trade_id} {self.direction} {self.outcome}>"

    def get_features(self):
        if self.feature_snapshot:
            return json.loads(self.feature_snapshot)
        return {}

    def to_dict(self):
        return {
            "id": self.id,
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "outcome": self.outcome,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "risk_reward": self.risk_reward,
            "confidence": self.confidence,
            "context_score": self.context_score,
            "behavior_score": self.behavior_score,
            "dna_confidence": self.dna_confidence,
            "simulation_bias": self.simulation_bias,
            "uncertainty": self.uncertainty,
            "dna_id": self.dna_id,
            "is_active": self.is_active,
        }
