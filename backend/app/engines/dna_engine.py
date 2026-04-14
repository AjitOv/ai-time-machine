"""
DNA Engine – the Memory System.

Stores trade setups as structured patterns and matches current conditions
to historical winning setups using cosine similarity.
"""

import hashlib
import json
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import numpy as np
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.setup_dna import SetupDNA

logger = logging.getLogger(__name__)


@dataclass
class DNAMatch:
    """A single DNA match result."""
    dna_id: str
    pattern_signature: str
    similarity: float     # 0 to 1
    direction: str
    win_rate: float
    total_trades: int
    reliability_score: float
    avg_risk_reward: float


@dataclass
class DNAResult:
    """Output of the DNA Engine."""
    best_match: Optional[DNAMatch]
    top_matches: List[DNAMatch]
    dna_confidence: float  # 0 to 1
    details: dict


class DNAEngine:
    """Setup DNA memory system with similarity matching."""

    # ──────────────────────────────────────────────
    # FEATURE VECTOR CONSTRUCTION
    # ──────────────────────────────────────────────

    @staticmethod
    def build_feature_vector(context_score: float, behavior_score: float,
                              rsi: float, ema_alignment: float,
                              atr_ratio: float, zone_val: float,
                              phase_val: float) -> List[float]:
        """Build a normalized feature vector for similarity matching.

        Args:
            context_score: -1 to +1
            behavior_score: -1 to +1
            rsi: 0 to 100 (normalized to 0-1)
            ema_alignment: -1 to +1 (bullish/bearish alignment)
            atr_ratio: 0+ (current ATR / average ATR)
            zone_val: -1 (discount) to +1 (premium)
            phase_val: 0 to 1 (trend strength)
        """
        return [
            context_score,
            behavior_score,
            (rsi - 50) / 50,  # Normalize RSI to -1..+1
            ema_alignment,
            min(atr_ratio, 3.0) / 3.0,  # Cap and normalize ATR ratio
            zone_val,
            phase_val,
        ]

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        a_arr = np.array(a, dtype=float)
        b_arr = np.array(b, dtype=float)
        dot = np.dot(a_arr, b_arr)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    # ──────────────────────────────────────────────
    # MATCHING
    # ──────────────────────────────────────────────

    async def find_matches(self, db: AsyncSession, current_vector: List[float],
                           symbol: str, top_k: int = 5) -> DNAResult:
        """Find the most similar historical DNA setups."""
        result = await db.execute(
            select(SetupDNA).where(
                and_(
                    SetupDNA.symbol == symbol,
                    SetupDNA.is_active == 1,
                    SetupDNA.total_trades >= settings.MIN_DNA_SAMPLE_SIZE,
                )
            )
        )
        dna_records = result.scalars().all()

        if not dna_records:
            return DNAResult(
                best_match=None, top_matches=[], dna_confidence=0.0,
                details={"reason": "No DNA records found", "records_searched": 0}
            )

        matches = []
        for record in dna_records:
            stored_vector = record.get_vector()
            sim = self.cosine_similarity(current_vector, stored_vector)

            matches.append(DNAMatch(
                dna_id=record.dna_id,
                pattern_signature=record.pattern_signature,
                similarity=sim,
                direction=record.direction,
                win_rate=record.win_rate,
                total_trades=record.total_trades,
                reliability_score=record.reliability_score,
                avg_risk_reward=record.avg_risk_reward,
            ))

        # Sort by reliability-weighted similarity
        matches.sort(key=lambda m: m.similarity * m.reliability_score, reverse=True)
        top_matches = matches[:top_k]

        best = top_matches[0] if top_matches else None
        dna_confidence = best.similarity * best.win_rate if best else 0.0

        return DNAResult(
            best_match=best,
            top_matches=top_matches,
            dna_confidence=min(1.0, dna_confidence),
            details={
                "records_searched": len(dna_records),
                "matches_found": len([m for m in matches if m.similarity > 0.5]),
            }
        )

    # ──────────────────────────────────────────────
    # DNA CREATION & UPDATE
    # ──────────────────────────────────────────────

    async def store_dna(self, db: AsyncSession, symbol: str, timeframe: str,
                         direction: str, pattern_signature: str,
                         feature_vector: List[float],
                         context_features: dict, behavior_features: dict,
                         entry_conditions: dict, outcome: str,
                         risk_reward: float):
        """Store a new DNA record or update existing matching pattern."""

        # Check for existing similar DNA
        result = await db.execute(
            select(SetupDNA).where(
                and_(
                    SetupDNA.symbol == symbol,
                    SetupDNA.pattern_signature == pattern_signature,
                    SetupDNA.direction == direction,
                )
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.utcnow()

        if existing:
            # Update existing DNA
            existing.total_trades += 1
            if outcome == "WIN":
                existing.wins += 1
            else:
                existing.losses += 1
            existing.win_rate = existing.wins / existing.total_trades
            existing.avg_risk_reward = (
                (existing.avg_risk_reward * (existing.total_trades - 1) + risk_reward)
                / existing.total_trades
            )
            existing.reliability_score = existing.win_rate * math.log(existing.total_trades + 1)
            existing.updated_at = now

            # Update feature vector (exponential moving average)
            old_vec = existing.get_vector()
            alpha = 0.1
            new_vec = [alpha * n + (1 - alpha) * o for o, n in zip(old_vec, feature_vector)]
            existing.feature_vector = json.dumps(new_vec)

            logger.info(f"Updated DNA {existing.dna_id}: WR={existing.win_rate:.2%} N={existing.total_trades}")
        else:
            # Create new DNA
            dna_id = f"DNA_{uuid.uuid4().hex[:8]}"
            new_dna = SetupDNA(
                dna_id=dna_id,
                pattern_signature=pattern_signature,
                symbol=symbol,
                timeframe=timeframe,
                created_at=now,
                updated_at=now,
                context_features=json.dumps(context_features),
                behavior_features=json.dumps(behavior_features),
                feature_vector=json.dumps(feature_vector),
                entry_conditions=json.dumps(entry_conditions),
                direction=direction,
                total_trades=1,
                wins=1 if outcome == "WIN" else 0,
                losses=0 if outcome == "WIN" else 1,
                win_rate=1.0 if outcome == "WIN" else 0.0,
                avg_risk_reward=risk_reward,
                reliability_score=0.0,  # Need more samples
                is_active=1,
            )
            db.add(new_dna)
            logger.info(f"Created new DNA {dna_id}: {pattern_signature} {direction}")

        await db.flush()

    # ──────────────────────────────────────────────
    # DNA DECAY
    # ──────────────────────────────────────────────

    async def decay_weak_setups(self, db: AsyncSession):
        """Deactivate DNA setups with poor performance."""
        result = await db.execute(
            select(SetupDNA).where(SetupDNA.is_active == 1)
        )
        records = result.scalars().all()

        deactivated = 0
        for record in records:
            if (record.total_trades >= settings.MIN_DNA_SAMPLE_SIZE
                    and record.win_rate < 0.3):
                record.is_active = 0
                deactivated += 1

        if deactivated > 0:
            await db.flush()
            logger.info(f"Deactivated {deactivated} weak DNA setups")


# Singleton
dna_engine = DNAEngine()
