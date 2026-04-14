"""MarketData ORM model – stores OHLCV candles across multiple timeframes."""

from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from app.database import Base


class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(5), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0)

    __table_args__ = (
        Index("ix_market_data_symbol_tf_ts", "symbol", "timeframe", "timestamp", unique=True),
    )

    def __repr__(self):
        return f"<MarketData {self.symbol} {self.timeframe} {self.timestamp} C={self.close}>"

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }
