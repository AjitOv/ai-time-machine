"""PerformanceLog ORM model – tracks system performance metrics over time."""

from sqlalchemy import Column, Integer, String, Float, DateTime
from app.database import Base


class PerformanceLog(Base):
    __tablename__ = "performance_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    metric_name = Column(String(50), nullable=False, index=True)
    value = Column(Float, nullable=False)
    window = Column(String(20), nullable=True)  # e.g., "last_20", "daily", "weekly"
    notes = Column(String(200), nullable=True)

    def __repr__(self):
        return f"<PerformanceLog {self.metric_name}={self.value:.4f}>"

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metric_name": self.metric_name,
            "value": self.value,
            "window": self.window,
            "notes": self.notes,
        }
