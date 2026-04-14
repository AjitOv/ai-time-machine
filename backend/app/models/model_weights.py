"""ModelWeight ORM model – stores adaptive engine weights."""

from sqlalchemy import Column, Integer, String, Float, DateTime
from app.database import Base


class ModelWeight(Base):
    __tablename__ = "model_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    weight_name = Column(String(50), unique=True, nullable=False, index=True)
    value = Column(Float, nullable=False, default=0.25)
    last_updated = Column(DateTime, nullable=False)
    update_count = Column(Integer, default=0)
    description = Column(String(200), nullable=True)

    def __repr__(self):
        return f"<ModelWeight {self.weight_name}={self.value:.4f}>"

    def to_dict(self):
        return {
            "id": self.id,
            "weight_name": self.weight_name,
            "value": self.value,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "update_count": self.update_count,
            "description": self.description,
        }
