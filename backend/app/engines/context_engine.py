"""
Context Engine – the Gatekeeper.

Determines WHETHER trading should occur by analyzing:
- Market phase (RANGE, TREND, EXHAUSTION, CHAOTIC)
- Higher timeframe bias
- Premium/Discount zones
- Regime classification
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """Output of the Context Engine."""
    phase: str           # RANGE, TREND, EXHAUSTION, CHAOTIC
    regime: str          # TRENDING, RANGING, VOLATILE, NEWS_DRIVEN
    htf_bias: str        # BULLISH, BEARISH, NEUTRAL
    zone: str            # PREMIUM, DISCOUNT, EQUILIBRIUM
    equilibrium: float   # Midpoint of range
    context_score: float # -1 to +1
    trade_permission: bool
    details: dict


class ContextEngine:
    """Analyzes market context and decides trade permission."""

    def analyze(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None) -> ContextResult:
        """Run full context analysis on enriched DataFrame."""
        if df.empty or len(df) < 50:
            return ContextResult(
                phase="UNKNOWN", regime="UNKNOWN", htf_bias="NEUTRAL",
                zone="EQUILIBRIUM", equilibrium=0.0, context_score=0.0,
                trade_permission=False, details={"reason": "Insufficient data"}
            )

        phase = self._detect_phase(df)
        regime = self._classify_regime(df, phase)
        htf_bias = self._compute_htf_bias(htf_df if htf_df is not None else df)
        equilibrium = self._compute_equilibrium(df)
        zone = self._compute_zone(df, equilibrium)
        context_score = self._compute_score(phase, regime, htf_bias, zone, df)
        trade_permission = self._evaluate_permission(phase, regime, context_score)

        return ContextResult(
            phase=phase,
            regime=regime,
            htf_bias=htf_bias,
            zone=zone,
            equilibrium=equilibrium,
            context_score=context_score,
            trade_permission=trade_permission,
            details={
                "atr_current": float(df["atr_14"].iloc[-1]) if "atr_14" in df else 0,
                "atr_mean": float(df["atr_14"].mean()) if "atr_14" in df else 0,
                "price": float(df["close"].iloc[-1]),
            }
        )

    # ──────────────────────────────────────────────
    # MARKET PHASE DETECTION
    # ──────────────────────────────────────────────

    def _detect_phase(self, df: pd.DataFrame) -> str:
        """Detect current market phase."""
        close = df["close"].values
        atr = df["atr_14"].values if "atr_14" in df else np.zeros(len(df))

        # ATR ratio: current vs average
        atr_current = atr[-1] if len(atr) > 0 and not np.isnan(atr[-1]) else 0
        atr_mean = np.nanmean(atr[-50:]) if len(atr) >= 50 else np.nanmean(atr)
        atr_ratio = atr_current / atr_mean if atr_mean > 0 else 1.0

        # Structure detection (last 20 candles)
        recent = close[-20:]
        highs = df["high"].values[-20:]
        lows = df["low"].values[-20:]

        # Higher highs / higher lows
        swing_highs = self._find_swing_points(highs, is_high=True)
        swing_lows = self._find_swing_points(lows, is_high=False)

        hh = self._is_trending_up(swing_highs)
        ll = self._is_trending_down(swing_lows)

        # Exhaustion: high ATR + rejection wick
        last_candle = df.iloc[-1]
        body_size = abs(last_candle["close"] - last_candle["open"])
        upper_wick = last_candle["high"] - max(last_candle["close"], last_candle["open"])
        lower_wick = min(last_candle["close"], last_candle["open"]) - last_candle["low"]
        total_range = last_candle["high"] - last_candle["low"]
        wick_ratio = max(upper_wick, lower_wick) / total_range if total_range > 0 else 0

        if atr_ratio > 2.0:
            return "CHAOTIC"
        elif atr_ratio > 1.5 and wick_ratio > 0.5:
            return "EXHAUSTION"
        elif hh or ll:
            return "TREND"
        else:
            return "RANGE"

    # ──────────────────────────────────────────────
    # REGIME CLASSIFICATION
    # ──────────────────────────────────────────────

    def _classify_regime(self, df: pd.DataFrame, phase: str) -> str:
        """Classify market regime."""
        atr = df["atr_14"].values if "atr_14" in df else np.zeros(len(df))
        atr_current = atr[-1] if len(atr) > 0 and not np.isnan(atr[-1]) else 0
        atr_mean = np.nanmean(atr[-50:]) if len(atr) >= 50 else np.nanmean(atr)
        atr_ratio = atr_current / atr_mean if atr_mean > 0 else 1.0

        if phase == "CHAOTIC":
            return "NEWS_DRIVEN"
        elif atr_ratio > 1.3 and phase in ("TREND", "EXHAUSTION"):
            return "VOLATILE"
        elif phase == "TREND":
            return "TRENDING"
        else:
            return "RANGING"

    # ──────────────────────────────────────────────
    # HIGHER TIMEFRAME BIAS
    # ──────────────────────────────────────────────

    def _compute_htf_bias(self, df: pd.DataFrame) -> str:
        """Determine directional bias from EMA 50 slope, with regime-transition
        guards to avoid the lagging-indicator trap. (E.g. April 2020: EMA50 still
        bearish from the COVID crash while price had already rallied 30%; the old
        logic kept firing SELLs and got every one stopped out.)"""
        if "ema_50" not in df or len(df) < 10:
            return "NEUTRAL"

        ema_50 = df["ema_50"].values
        # Slope of last 10 periods
        recent_slope = (ema_50[-1] - ema_50[-10]) / ema_50[-10] if ema_50[-10] != 0 else 0

        price = df["close"].values[-1]
        above_ema = price > ema_50[-1]

        # Guard 1: fast/slow EMA disagreement → regime transition → no side.
        if "ema_11" in df:
            ema_11 = df["ema_11"].values
            if len(ema_11) >= 6 and ema_11[-5] != 0:
                fast_slope = (ema_11[-1] - ema_11[-5]) / ema_11[-5]
                slow_bullish = recent_slope > 0.002
                slow_bearish = recent_slope < -0.002
                fast_bullish = fast_slope > 0.001
                fast_bearish = fast_slope < -0.001
                if (slow_bullish and fast_bearish) or (slow_bearish and fast_bullish):
                    return "NEUTRAL"

        # Guard 2: strong recent counter-momentum invalidates the slow verdict.
        # If EMA50 says BEARISH but price has rallied >3% in the last 5 bars,
        # we're past the turn. (Symmetric for the bullish-then-selloff case.)
        if len(df) >= 6:
            recent_close = float(df["close"].iloc[-1])
            prior_close = float(df["close"].iloc[-6])
            if prior_close != 0:
                five_bar_return = (recent_close - prior_close) / prior_close
                if recent_slope < -0.002 and five_bar_return > 0.03:
                    return "NEUTRAL"
                if recent_slope > 0.002 and five_bar_return < -0.03:
                    return "NEUTRAL"

        if recent_slope > 0.002 and above_ema:
            return "BULLISH"
        elif recent_slope < -0.002 and not above_ema:
            return "BEARISH"
        else:
            return "NEUTRAL"

    # ──────────────────────────────────────────────
    # LOCATION ENGINE
    # ──────────────────────────────────────────────

    def _compute_equilibrium(self, df: pd.DataFrame, lookback: int = 50) -> float:
        """Compute equilibrium (midpoint of range)."""
        recent = df.tail(lookback)
        range_high = recent["high"].max()
        range_low = recent["low"].min()
        return float((range_high + range_low) / 2)

    def _compute_zone(self, df: pd.DataFrame, equilibrium: float) -> str:
        """Determine if price is in premium, discount, or at equilibrium."""
        price = df["close"].iloc[-1]
        range_high = df.tail(50)["high"].max()
        range_low = df.tail(50)["low"].min()
        total_range = range_high - range_low

        if total_range == 0:
            return "EQUILIBRIUM"

        position = (price - range_low) / total_range

        if position > 0.618:
            return "PREMIUM"
        elif position < 0.382:
            return "DISCOUNT"
        else:
            return "EQUILIBRIUM"

    # ──────────────────────────────────────────────
    # SCORING
    # ──────────────────────────────────────────────

    def _compute_score(self, phase: str, regime: str, htf_bias: str,
                       zone: str, df: pd.DataFrame) -> float:
        """Compute context score from -1 (strongly bearish) to +1 (strongly bullish)."""
        score = 0.0

        # Phase contribution
        if phase == "TREND":
            score += 0.3
        elif phase == "RANGE":
            score += 0.0
        elif phase == "EXHAUSTION":
            score -= 0.2
        elif phase == "CHAOTIC":
            score -= 0.5

        # HTF bias
        if htf_bias == "BULLISH":
            score += 0.3
        elif htf_bias == "BEARISH":
            score -= 0.3

        # Zone (discount is bullish opportunity, premium is bearish)
        if zone == "DISCOUNT" and htf_bias == "BULLISH":
            score += 0.2
        elif zone == "PREMIUM" and htf_bias == "BEARISH":
            score -= 0.2

        # Regime penalty
        if regime == "NEWS_DRIVEN":
            score *= 0.3  # Heavy dampen
        elif regime == "VOLATILE":
            score *= 0.7

        return max(-1.0, min(1.0, score))

    def _evaluate_permission(self, phase: str, regime: str, score: float) -> bool:
        """Determine if trading should be allowed."""
        if phase in ("CHAOTIC",):
            return False
        if regime == "NEWS_DRIVEN":
            return False
        if abs(score) < 0.1:
            return False  # No edge
        return True

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    @staticmethod
    def _find_swing_points(data: np.ndarray, is_high: bool = True, lookback: int = 3) -> list:
        """Find swing highs or lows in a price array."""
        swings = []
        for i in range(lookback, len(data) - lookback):
            window = data[i - lookback:i + lookback + 1]
            if is_high and data[i] == window.max():
                swings.append(data[i])
            elif not is_high and data[i] == window.min():
                swings.append(data[i])
        return swings

    @staticmethod
    def _is_trending_up(swing_points: list) -> bool:
        """Check if swing points form higher highs."""
        if len(swing_points) < 3:
            return False
        recent = swing_points[-3:]
        return recent[-1] > recent[-2] > recent[-3]

    @staticmethod
    def _is_trending_down(swing_points: list) -> bool:
        """Check if swing points form lower lows."""
        if len(swing_points) < 3:
            return False
        recent = swing_points[-3:]
        return recent[-1] < recent[-2] < recent[-3]


# Singleton
context_engine = ContextEngine()
