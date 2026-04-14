"""Feature ORM model – stores computed technical indicators per candle."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from app.database import Base


class Feature(Base):
    __tablename__ = "features"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(5), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)

    # RSI
    rsi_14 = Column(Float, nullable=True)

    # EMAs
    ema_11 = Column(Float, nullable=True)
    ema_21 = Column(Float, nullable=True)
    ema_50 = Column(Float, nullable=True)

    # ATR
    atr_14 = Column(Float, nullable=True)

    # Derived
    close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_features_symbol_tf_ts", "symbol", "timeframe", "timestamp", unique=True),
    )

    def __repr__(self):
        return f"<Feature {self.symbol} {self.timeframe} {self.timestamp} RSI={self.rsi_14}>"

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "rsi_14": self.rsi_14,
            "ema_11": self.ema_11,
            "ema_21": self.ema_21,
            "ema_50": self.ema_50,
            "atr_14": self.atr_14,
            "close": self.close,
            "volume": self.volume,
        }
