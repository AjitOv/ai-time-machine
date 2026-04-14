"""RegimeState ORM model – logs market regime classifications over time."""

from sqlalchemy import Column, Integer, String, Float, DateTime
from app.database import Base


class RegimeState(Base):
    __tablename__ = "regime_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(5), nullable=False)

    # Classification
    regime = Column(String(20), nullable=False)  # TRENDING, RANGING, VOLATILE, NEWS_DRIVEN
    phase = Column(String(20), nullable=False)    # RANGE, TREND, EXHAUSTION, CHAOTIC
    htf_bias = Column(String(10), nullable=True)  # BULLISH, BEARISH, NEUTRAL

    # Scores
    context_score = Column(Float, nullable=False, default=0.0)
    trade_permission = Column(Integer, default=0)  # 1 = allowed, 0 = not

    # Location
    equilibrium = Column(Float, nullable=True)
    zone = Column(String(20), nullable=True)  # PREMIUM, DISCOUNT, EQUILIBRIUM

    def __repr__(self):
        return f"<RegimeState {self.symbol} {self.regime} {self.phase} CS={self.context_score:.2f}>"

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "regime": self.regime,
            "phase": self.phase,
            "htf_bias": self.htf_bias,
            "context_score": self.context_score,
            "trade_permission": bool(self.trade_permission),
            "equilibrium": self.equilibrium,
            "zone": self.zone,
        }
