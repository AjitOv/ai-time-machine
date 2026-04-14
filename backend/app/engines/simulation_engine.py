"""
Monte Carlo Simulation Engine – models multiple probabilistic futures.

Uses Geometric Brownian Motion (GBM) with:
- DNA-biased drift
- Regime-adjusted volatility
- Vectorized NumPy implementation
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    """Output of the Monte Carlo Simulation Engine."""
    bullish_probability: float   # 0 to 1
    bearish_probability: float   # 0 to 1
    neutral_probability: float   # 0 to 1
    target_hit_probability: float
    stop_loss_risk: float
    mean_final_price: float
    median_final_price: float
    price_5th_percentile: float
    price_95th_percentile: float
    simulation_bias: float       # -1 to +1
    paths: Optional[np.ndarray]  # Shape: (steps+1, num_sims)
    details: dict


class SimulationEngine:
    """Monte Carlo price path simulation using Geometric Brownian Motion."""

    def simulate(
        self,
        current_price: float,
        historical_returns: np.ndarray,
        num_sims: int = None,
        forecast_steps: int = None,
        dna_direction: Optional[str] = None,
        dna_confidence: float = 0.0,
        regime: str = "RANGING",
        target_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
    ) -> SimulationResult:
        """Run Monte Carlo simulation.

        Args:
            current_price: Current market price
            historical_returns: Array of historical log returns
            num_sims: Number of simulation paths
            forecast_steps: Number of steps to simulate
            dna_direction: BUY/SELL from DNA engine (for drift bias)
            dna_confidence: 0-1 DNA confidence score
            regime: Current market regime
            target_price: Optional target for hit probability
            stop_loss_price: Optional stop loss for risk calculation
        """
        n_sims = num_sims or settings.MC_NUM_SIMULATIONS
        n_steps = forecast_steps or settings.MC_FORECAST_STEPS

        if len(historical_returns) < 10 or current_price <= 0:
            return self._empty_result(current_price)

        # Base drift and volatility from historical data
        mu = float(np.mean(historical_returns))
        sigma = float(np.std(historical_returns))

        if sigma == 0:
            sigma = 0.001  # Prevent div by zero

        # ── DNA BIAS: adjust drift based on DNA direction & confidence ──
        if dna_direction and dna_confidence > 0:
            bias_factor = dna_confidence * 0.3  # Max 30% drift adjustment
            if dna_direction == "BUY":
                mu += abs(mu) * bias_factor
            elif dna_direction == "SELL":
                mu -= abs(mu) * bias_factor

        # ── REGIME ADJUSTMENT: adjust volatility ──
        regime_multipliers = {
            "TRENDING": 0.9,
            "RANGING": 1.0,
            "VOLATILE": 1.4,
            "NEWS_DRIVEN": 1.8,
        }
        sigma *= regime_multipliers.get(regime, 1.0)

        # ── VECTORIZED GBM SIMULATION ──
        dt = 1.0  # Each step = 1 candle period
        z = np.random.standard_normal((n_steps, n_sims))

        drift = (mu - 0.5 * sigma ** 2) * dt
        diffusion = sigma * np.sqrt(dt) * z

        log_returns = drift + diffusion
        price_paths = current_price * np.exp(np.cumsum(log_returns, axis=0))

        # Prepend initial price
        initial_row = np.full((1, n_sims), current_price)
        price_paths = np.vstack([initial_row, price_paths])

        # ── COMPUTE PROBABILITIES ──
        final_prices = price_paths[-1, :]
        mean_final = float(np.mean(final_prices))
        median_final = float(np.median(final_prices))

        pct_change = (final_prices - current_price) / current_price

        bullish_threshold = 0.005   # +0.5%
        bearish_threshold = -0.005  # -0.5%

        bullish_prob = float(np.mean(pct_change > bullish_threshold))
        bearish_prob = float(np.mean(pct_change < bearish_threshold))
        neutral_prob = 1.0 - bullish_prob - bearish_prob

        # ── TARGET HIT PROBABILITY ──
        target_hit = 0.0
        if target_price is not None:
            if target_price > current_price:
                # Bullish target: check if path ever reaches target
                target_hit = float(np.mean(np.any(price_paths >= target_price, axis=0)))
            else:
                target_hit = float(np.mean(np.any(price_paths <= target_price, axis=0)))

        # ── STOP LOSS RISK ──
        sl_risk = 0.0
        if stop_loss_price is not None:
            if stop_loss_price < current_price:
                sl_risk = float(np.mean(np.any(price_paths <= stop_loss_price, axis=0)))
            else:
                sl_risk = float(np.mean(np.any(price_paths >= stop_loss_price, axis=0)))

        # ── SIMULATION BIAS ──
        sim_bias = bullish_prob - bearish_prob  # -1 to +1

        return SimulationResult(
            bullish_probability=round(bullish_prob, 4),
            bearish_probability=round(bearish_prob, 4),
            neutral_probability=round(neutral_prob, 4),
            target_hit_probability=round(target_hit, 4),
            stop_loss_risk=round(sl_risk, 4),
            mean_final_price=round(mean_final, 2),
            median_final_price=round(median_final, 2),
            price_5th_percentile=round(float(np.percentile(final_prices, 5)), 2),
            price_95th_percentile=round(float(np.percentile(final_prices, 95)), 2),
            simulation_bias=round(sim_bias, 4),
            paths=price_paths,
            details={
                "mu": round(mu, 6),
                "sigma": round(sigma, 6),
                "num_simulations": n_sims,
                "forecast_steps": n_steps,
                "dna_bias_applied": dna_direction is not None,
                "regime": regime,
            }
        )

    @staticmethod
    def _empty_result(price: float) -> SimulationResult:
        return SimulationResult(
            bullish_probability=0.33, bearish_probability=0.33,
            neutral_probability=0.34, target_hit_probability=0.0,
            stop_loss_risk=0.0, mean_final_price=price,
            median_final_price=price,
            price_5th_percentile=price, price_95th_percentile=price,
            simulation_bias=0.0, paths=None,
            details={"reason": "Insufficient data for simulation"}
        )


# Singleton
simulation_engine = SimulationEngine()
