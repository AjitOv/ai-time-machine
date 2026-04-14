"""SetupDNA ORM model – stores structured pattern memory for similarity matching."""

import json
from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from app.database import Base


class SetupDNA(Base):
    __tablename__ = "setup_dna"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dna_id = Column(String(50), unique=True, nullable=False, index=True)
    pattern_signature = Column(String(100), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(5), nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    # Context features (JSON)
    context_features = Column(Text, nullable=False)

    # Behavior features (JSON)
    behavior_features = Column(Text, nullable=False)

    # Feature vector for similarity matching (JSON array of floats)
    feature_vector = Column(Text, nullable=False)

    # Entry conditions (JSON)
    entry_conditions = Column(Text, nullable=True)

    # Performance
    direction = Column(String(10), nullable=False)  # BUY or SELL
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    avg_risk_reward = Column(Float, default=0.0)

    # Confidence & scoring
    reliability_score = Column(Float, default=0.0)  # win_rate * log(sample_size + 1)
    is_active = Column(Integer, default=1)  # 1 = active, 0 = decayed/eliminated

    def __repr__(self):
        return f"<SetupDNA {self.dna_id} WR={self.win_rate:.0%} N={self.total_trades}>"

    def get_context(self):
        return json.loads(self.context_features)

    def get_behavior(self):
        return json.loads(self.behavior_features)

    def get_vector(self):
        return json.loads(self.feature_vector)

    def to_dict(self):
        return {
            "id": self.id,
            "dna_id": self.dna_id,
            "pattern_signature": self.pattern_signature,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "avg_risk_reward": self.avg_risk_reward,
            "reliability_score": self.reliability_score,
            "is_active": self.is_active,
            "context_features": self.get_context(),
            "behavior_features": self.get_behavior(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
