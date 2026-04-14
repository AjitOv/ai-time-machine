"""Pydantic schemas for analysis endpoints."""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class ContextResponse(BaseModel):
    phase: str
    regime: str
    htf_bias: str
    zone: str
    equilibrium: float
    context_score: float
    trade_permission: bool
    details: Dict[str, Any] = {}


class PatternItem(BaseModel):
    name: str
    direction: str
    strength: float
    details: Dict[str, Any] = {}


class BehaviorResponse(BaseModel):
    behavior_score: float
    pattern_signature: str
    patterns: List[PatternItem]
    confluence_count: int
    details: Dict[str, Any] = {}


class DNAMatchItem(BaseModel):
    dna_id: str
    pattern_signature: str
    similarity: float
    direction: str
    win_rate: float
    total_trades: int
    reliability_score: float
    avg_risk_reward: float


class DNAResponse(BaseModel):
    best_match: Optional[DNAMatchItem] = None
    top_matches: List[DNAMatchItem] = []
    dna_confidence: float
    details: Dict[str, Any] = {}


class DecisionResponse(BaseModel):
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    final_score: float
    risk_reward: float
    reasons: List[str]
    rejected_reasons: List[str]
    details: Dict[str, Any] = {}


class AnalysisRequest(BaseModel):
    symbol: Optional[str] = None
    timeframe: str = "1h"


class FullAnalysisResponse(BaseModel):
    symbol: str
    timeframe: str
    timestamp: str
    context: ContextResponse
    behavior: BehaviorResponse
    dna: DNAResponse
    decision: DecisionResponse
    scenarios: List[Dict[str, Any]]
    uncertainty: Dict[str, Any]
    risk: Dict[str, Any]
    meta: Dict[str, Any]
