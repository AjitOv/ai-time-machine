"""
Behavior Engine – detects behavioral patterns in price action.

Detects:
- Liquidity sweeps (stop hunts)
- Trap detection (false breakouts)
- Momentum shifts
- Volatility expansion
- Feature interaction / confluence modeling
"""

import hashlib
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PatternDetection:
    """A single detected behavioral pattern."""
    name: str
    direction: str         # BULLISH or BEARISH
    strength: float        # 0 to 1
    candle_index: int      # Index in the DataFrame
    details: dict = field(default_factory=dict)


@dataclass
class BehaviorResult:
    """Output of the Behavior Engine."""
    behavior_score: float       # -1 to +1
    pattern_signature: str      # Hash of detected patterns
    patterns: List[PatternDetection]
    confluence_count: int
    details: dict


class BehaviorEngine:
    """Detects behavioral patterns and confluence."""

    def analyze(self, df: pd.DataFrame, htf_bias: str = "NEUTRAL",
                zone: str = "EQUILIBRIUM") -> BehaviorResult:
        """Run full behavioral analysis."""
        if df.empty or len(df) < 20:
            return BehaviorResult(
                behavior_score=0.0, pattern_signature="none",
                patterns=[], confluence_count=0,
                details={"reason": "Insufficient data"}
            )

        patterns: List[PatternDetection] = []

        # Detect each pattern type
        patterns.extend(self._detect_liquidity_sweeps(df))
        patterns.extend(self._detect_traps(df))
        patterns.extend(self._detect_momentum_shifts(df))
        patterns.extend(self._detect_volatility_expansion(df))

        # Confluence modeling
        confluence_score, confluence_count = self._compute_confluence(
            patterns, htf_bias, zone
        )

        # Compute overall score
        behavior_score = self._compute_score(patterns, confluence_score)

        # Generate pattern signature
        sig = self._generate_signature(patterns)

        return BehaviorResult(
            behavior_score=behavior_score,
            pattern_signature=sig,
            patterns=patterns,
            confluence_count=confluence_count,
            details={
                "num_patterns": len(patterns),
                "confluence_score": confluence_score,
                "pattern_names": [p.name for p in patterns],
            }
        )

    # ──────────────────────────────────────────────
    # LIQUIDITY SWEEP DETECTION
    # ──────────────────────────────────────────────

    def _detect_liquidity_sweeps(self, df: pd.DataFrame) -> List[PatternDetection]:
        """Detect liquidity sweeps (price pierces swing level then reverses)."""
        patterns = []
        highs = df["high"].values
        lows = df["low"].values
        close = df["close"].values
        open_ = df["open"].values

        lookback = min(20, len(df) - 5)
        if lookback < 5:
            return patterns

        # Find swing high/low in previous candles
        recent_high = np.max(highs[-lookback:-3])
        recent_low = np.min(lows[-lookback:-3])

        # Check last 3 candles for sweep
        for i in range(-3, 0):
            # Bullish sweep (sweep lows then reverse up)
            if lows[i] < recent_low and close[i] > open_[i]:
                patterns.append(PatternDetection(
                    name="LIQUIDITY_SWEEP",
                    direction="BULLISH",
                    strength=min(1.0, abs(recent_low - lows[i]) / (recent_high - recent_low + 0.001)),
                    candle_index=len(df) + i,
                    details={"sweep_level": float(recent_low), "wick_low": float(lows[i])}
                ))

            # Bearish sweep (sweep highs then reverse down)
            if highs[i] > recent_high and close[i] < open_[i]:
                patterns.append(PatternDetection(
                    name="LIQUIDITY_SWEEP",
                    direction="BEARISH",
                    strength=min(1.0, abs(highs[i] - recent_high) / (recent_high - recent_low + 0.001)),
                    candle_index=len(df) + i,
                    details={"sweep_level": float(recent_high), "wick_high": float(highs[i])}
                ))

        return patterns

    # ──────────────────────────────────────────────
    # TRAP DETECTION (FALSE BREAKOUTS)
    # ──────────────────────────────────────────────

    def _detect_traps(self, df: pd.DataFrame) -> List[PatternDetection]:
        """Detect false breakouts / traps."""
        patterns = []
        close = df["close"].values
        open_ = df["open"].values
        high = df["high"].values
        low = df["low"].values

        if len(df) < 10:
            return patterns

        # Resistance / Support from recent range
        lookback = min(30, len(df) - 3)
        resistance = np.max(high[-lookback:-3])
        support = np.min(low[-lookback:-3])

        # Check last 2 candles
        for i in range(-2, 0):
            # Bull trap: breaks above resistance but closes below
            if high[i] > resistance and close[i] < resistance:
                patterns.append(PatternDetection(
                    name="TRAP",
                    direction="BEARISH",
                    strength=0.7,
                    candle_index=len(df) + i,
                    details={"level": float(resistance), "type": "bull_trap"}
                ))

            # Bear trap: breaks below support but closes above
            if low[i] < support and close[i] > support:
                patterns.append(PatternDetection(
                    name="TRAP",
                    direction="BULLISH",
                    strength=0.7,
                    candle_index=len(df) + i,
                    details={"level": float(support), "type": "bear_trap"}
                ))

        return patterns

    # ──────────────────────────────────────────────
    # MOMENTUM SHIFT DETECTION
    # ──────────────────────────────────────────────

    def _detect_momentum_shifts(self, df: pd.DataFrame) -> List[PatternDetection]:
        """Detect strong opposing candles indicating momentum change."""
        patterns = []
        close = df["close"].values
        open_ = df["open"].values
        volume = df["volume"].values if "volume" in df else np.ones(len(df))

        if len(df) < 10:
            return patterns

        avg_body = np.mean(np.abs(close[-20:] - open_[-20:])) if len(df) >= 20 else np.mean(np.abs(close - open_))
        avg_vol = np.mean(volume[-20:]) if len(df) >= 20 else np.mean(volume)

        # Check last 3 candles
        for i in range(-3, 0):
            body = abs(close[i] - open_[i])
            is_bullish = close[i] > open_[i]
            prev_bearish = i > -len(close) and close[i - 1] < open_[i - 1]
            prev_bullish = i > -len(close) and close[i - 1] > open_[i - 1]
            vol_spike = volume[i] > avg_vol * 1.5 if avg_vol > 0 else False

            # Bullish momentum shift: previous bearish + current strong bullish + volume
            if body > avg_body * 1.5 and is_bullish and prev_bearish and vol_spike:
                patterns.append(PatternDetection(
                    name="MOMENTUM_SHIFT",
                    direction="BULLISH",
                    strength=min(1.0, body / (avg_body * 2)),
                    candle_index=len(df) + i,
                    details={"body_ratio": float(body / avg_body) if avg_body > 0 else 0}
                ))

            # Bearish momentum shift
            if body > avg_body * 1.5 and not is_bullish and prev_bullish and vol_spike:
                patterns.append(PatternDetection(
                    name="MOMENTUM_SHIFT",
                    direction="BEARISH",
                    strength=min(1.0, body / (avg_body * 2)),
                    candle_index=len(df) + i,
                    details={"body_ratio": float(body / avg_body) if avg_body > 0 else 0}
                ))

        return patterns

    # ──────────────────────────────────────────────
    # VOLATILITY EXPANSION
    # ──────────────────────────────────────────────

    def _detect_volatility_expansion(self, df: pd.DataFrame) -> List[PatternDetection]:
        """Detect volatility expansion after compression."""
        patterns = []

        if "atr_14" not in df or len(df) < 20:
            return patterns

        atr = df["atr_14"].values
        close = df["close"].values
        open_ = df["open"].values

        # Check for compression followed by expansion
        atr_recent_avg = np.nanmean(atr[-5:])
        atr_prior_avg = np.nanmean(atr[-20:-5])

        if atr_prior_avg > 0 and atr_recent_avg / atr_prior_avg > 1.5:
            direction = "BULLISH" if close[-1] > open_[-1] else "BEARISH"
            patterns.append(PatternDetection(
                name="VOLATILITY_EXPANSION",
                direction=direction,
                strength=min(1.0, atr_recent_avg / atr_prior_avg - 1),
                candle_index=len(df) - 1,
                details={
                    "atr_ratio": float(atr_recent_avg / atr_prior_avg),
                    "compression_atr": float(atr_prior_avg),
                    "expansion_atr": float(atr_recent_avg),
                }
            ))

        return patterns

    # ──────────────────────────────────────────────
    # CONFLUENCE MODELING
    # ──────────────────────────────────────────────

    def _compute_confluence(self, patterns: List[PatternDetection],
                            htf_bias: str, zone: str) -> tuple:
        """Score confluence of patterns with context."""
        if not patterns:
            return 0.0, 0

        confluence_count = 0
        confluence_score = 0.0

        # Count aligned bullish patterns
        bullish = [p for p in patterns if p.direction == "BULLISH"]
        bearish = [p for p in patterns if p.direction == "BEARISH"]

        # Bullish confluence
        if bullish and htf_bias == "BULLISH" and zone == "DISCOUNT":
            confluence_count = len(bullish) + 2  # +2 for HTF + zone alignment
            confluence_score = min(1.0, 0.3 * confluence_count)

        # Bearish confluence
        elif bearish and htf_bias == "BEARISH" and zone == "PREMIUM":
            confluence_count = len(bearish) + 2
            confluence_score = min(1.0, -0.3 * confluence_count)

        # Partial confluence
        elif bullish and htf_bias == "BULLISH":
            confluence_count = len(bullish) + 1
            confluence_score = min(1.0, 0.2 * confluence_count)
        elif bearish and htf_bias == "BEARISH":
            confluence_count = len(bearish) + 1
            confluence_score = min(1.0, -0.2 * confluence_count)

        return confluence_score, confluence_count

    def _compute_score(self, patterns: List[PatternDetection],
                       confluence_score: float) -> float:
        """Compute overall behavior score."""
        if not patterns:
            return 0.0

        # Weighted average of pattern strengths (directional)
        directional_sum = 0.0
        for p in patterns:
            sign = 1.0 if p.direction == "BULLISH" else -1.0
            directional_sum += sign * p.strength

        pattern_score = directional_sum / max(len(patterns), 1)

        # Blend with confluence
        score = 0.6 * pattern_score + 0.4 * confluence_score
        return max(-1.0, min(1.0, score))

    @staticmethod
    def _generate_signature(patterns: List[PatternDetection]) -> str:
        """Generate a hash signature for the detected patterns."""
        if not patterns:
            return "no_pattern"
        sig_str = "|".join(sorted(f"{p.name}_{p.direction}" for p in patterns))
        return hashlib.md5(sig_str.encode()).hexdigest()[:12]


# Singleton
behavior_engine = BehaviorEngine()
