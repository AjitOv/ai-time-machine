"""Pydantic schemas for simulation endpoints."""

from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class SimulationRequest(BaseModel):
    symbol: Optional[str] = None
    timeframe: str = "1h"
    num_simulations: int = 100
    forecast_steps: int = 50


class ScenarioItem(BaseModel):
    label: str
    name: str
    probability: float
    expected_price: float
    price_range: List[float]
    key_risks: List[str]
    description: str


class SimulationResponse(BaseModel):
    symbol: str
    current_price: float
    bullish_probability: float
    bearish_probability: float
    neutral_probability: float
    target_hit_probability: float
    stop_loss_risk: float
    mean_final_price: float
    median_final_price: float
    price_5th_percentile: float
    price_95th_percentile: float
    simulation_bias: float
    scenarios: List[ScenarioItem]
    paths_sample: List[List[float]]  # First 10 paths for visualization
    details: Dict[str, Any] = {}
