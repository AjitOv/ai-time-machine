"""
Backtest engine — replays historical candles through the full engine stack
and produces a real equity curve, trade ledger, and performance stats.

Designed to be self-contained:
  - Reads the cached/historical DataFrame from data_engine
  - For each candle from `warmup` onward, runs Context → Behavior → Simulation
    → Scenario → Decision on the rolling window ending at that candle
  - Opens virtual trades on BUY/SELL, walks forward bar-by-bar checking SL/TP
  - Computes equity, drawdown, Sharpe, profit factor, by-direction / by-regime
    breakdowns

Does NOT touch the production trades table or the live DNA library — backtest
is read-only and isolated. A separate seed-from-backtest path can later push
winning patterns into the live DNA library if desired.
"""

import logging
import math
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.engines.behavior_engine import behavior_engine
from app.engines.context_engine import context_engine
from app.engines.data_engine import data_engine
from app.engines.decision_engine import decision_engine
from app.engines.dna_engine import DNAEngine
from app.engines.scenario_engine import scenario_engine
from app.engines.simulation_engine import simulation_engine
from app.engines.uncertainty_engine import uncertainty_engine

logger = logging.getLogger(__name__)


# Minimal stand-in for DNAResult so decision_engine can be called without
# requiring a populated DB. During backtest, DNA contributes 0 — first-pass
# baseline of "what would Time Machine do without memory".
@dataclass
class _NullDNAResult:
    dna_confidence: float = 0.0
    best_match: object = None
    details: dict = field(default_factory=dict)


@dataclass
class BacktestTrade:
    timestamp: str
    symbol: str
    timeframe: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    final_score: float
    # Filled when closed:
    exit_timestamp: Optional[str] = None
    exit_price: Optional[float] = None
    outcome: str = "OPEN"  # WIN | LOSS | OPEN
    pnl: float = 0.0
    pnl_pct: float = 0.0
    rr_realized: float = 0.0
    bars_held: int = 0
    # Engine attribution for analysis:
    context_score: float = 0.0
    behavior_score: float = 0.0
    sim_bullish: float = 0.0
    sim_bearish: float = 0.0
    regime: str = ""
    phase: str = ""
    zone: str = ""
    htf_bias: str = ""
    # DNA seeding fields — captured so winning trades can populate the DNA library
    feature_vector: List[float] = field(default_factory=list)
    pattern_signature: str = ""


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    bars_processed: int
    start_ts: str
    end_ts: str
    runtime_ms: int

    # Trades
    trades: List[Dict]
    total_trades: int
    wins: int
    losses: int
    open_trades: int

    # Performance
    win_rate: float
    avg_pnl_pct: float
    avg_rr: float
    profit_factor: float
    total_pnl_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float

    # Equity curve: [{t, equity, drawdown}]
    equity_curve: List[Dict]

    # Breakdowns
    by_direction: Dict
    by_regime: Dict


class BacktestEngine:
    """Vectorless replay — clarity over speed for the first pass."""

    def __init__(self, starting_equity: float = 100_000.0):
        self.starting_equity = starting_equity

    def run(
        self,
        symbol: str,
        timeframe: str = "1h",
        warmup: int = 100,
        max_bars: Optional[int] = None,
    ) -> BacktestResult:
        t0 = datetime.utcnow()
        df_full = data_engine.get_cached(symbol, timeframe)
        if df_full is None or df_full.empty:
            return self._empty(symbol, timeframe, "no data available")
        df_full = data_engine.compute_all_features(df_full)

        if len(df_full) < warmup + 5:
            return self._empty(symbol, timeframe, f"need at least {warmup + 5} candles, have {len(df_full)}")

        # Optionally limit replay length to keep big runs snappy.
        if max_bars is not None and max_bars < len(df_full):
            df_full = df_full.iloc[-max_bars:]
            warmup = min(warmup, max(50, len(df_full) // 4))

        # ── MULTI-TIMEFRAME CONFLUENCE ──
        # For intraday backtests, also load the daily frame so context_engine
        # can compute its htf_bias from the *real* higher timeframe instead of
        # reusing the intraday window. Cleanly enforces "trade with the daily
        # trend" without tuning intraday-specific thresholds.
        df_daily: Optional[pd.DataFrame] = None
        if timeframe != "1d":
            cached_daily = data_engine.get_cached(symbol, "1d")
            if cached_daily is not None and not cached_daily.empty and len(cached_daily) >= 60:
                df_daily = data_engine.compute_all_features(cached_daily)
                logger.info(f"backtest: using daily HTF confluence ({len(df_daily)} daily bars available)")

        trades: List[BacktestTrade] = []
        open_trades: List[BacktestTrade] = []
        equity = self.starting_equity
        peak_equity = equity
        equity_curve: List[Dict] = [{
            "t": int(df_full.index[warmup - 1].value // 10**9),
            "equity": equity,
            "drawdown": 0.0,
        }]

        # Walk forward one candle at a time.
        n = len(df_full)
        for i in range(warmup, n - 1):
            window = df_full.iloc[max(0, i - warmup):i + 1]
            current_candle = df_full.iloc[i]
            next_candle = df_full.iloc[i + 1]
            ts = df_full.index[i]

            # ── 1. Resolve open trades against the current candle's high/low ──
            still_open: List[BacktestTrade] = []
            for tr in open_trades:
                outcome, exit_price = self._check_hit(tr, current_candle)
                tr.bars_held += 1
                if outcome:
                    tr.exit_timestamp = ts.isoformat()
                    tr.exit_price = round(float(exit_price), 2)
                    tr.outcome = outcome
                    if tr.direction == "BUY":
                        tr.pnl = exit_price - tr.entry_price
                    else:
                        tr.pnl = tr.entry_price - exit_price
                    tr.pnl_pct = round(tr.pnl / tr.entry_price * 100, 4) if tr.entry_price else 0.0
                    risk = abs(tr.entry_price - tr.stop_loss)
                    tr.rr_realized = round(abs(tr.pnl) / risk, 3) if risk > 0 else 0.0
                    # Equity update: apply pnl_pct to a fixed-fraction of equity
                    # (1% risk per trade by convention, scaled by confidence).
                    risk_pct = 0.01 * (0.5 + tr.confidence)  # 0.5x → 1.5x of base
                    equity_delta = (tr.pnl_pct / 100.0) * (equity * risk_pct * 100)  # naive: 1% risk = 100 units
                    # Simpler: just track pnl_pct cumulative
                    equity *= (1 + (tr.pnl_pct / 100.0) * risk_pct)
                else:
                    still_open.append(tr)
            open_trades = still_open

            # Track equity peak + drawdown after resolutions
            if equity > peak_equity:
                peak_equity = equity
            dd = (equity - peak_equity) / peak_equity * 100 if peak_equity > 0 else 0.0
            equity_curve.append({
                "t": int(ts.value // 10**9),
                "equity": round(equity, 2),
                "drawdown": round(dd, 4),
            })

            # ── 2. Run engines on window, decide if a new trade opens ──
            # For intraday TFs: slice the daily frame up to today so the
            # context engine derives htf_bias from real higher-timeframe data,
            # and so the decision engine can size stops from the daily ATR
            # (which sits outside intraday noise).
            htf_window = None
            stop_atr_value = None
            if df_daily is not None:
                # ts is the intraday candle's timestamp; we want all daily
                # candles strictly *before* the start of this intraday day so
                # we don't peek at the same day's daily close (look-ahead).
                day_cutoff = ts.normalize()  # midnight of this candle's day
                htf_slice = df_daily.loc[df_daily.index < day_cutoff]
                if len(htf_slice) >= 50:
                    htf_window = htf_slice.tail(150)  # enough for EMA50 + slope
                    # Use prior-day's daily ATR as the stop sizer for intraday.
                    # Scale down to an "intraday-equivalent" ATR — daily ATR
                    # over a session ≈ 6× the typical 1h ATR — so we divide by
                    # a session-step factor so SL stays sensible per-TF.
                    # Only override stop ATR for sub-hourly timeframes where
                    # local ATR(14) captures pure noise. For 1h+ the local ATR
                    # already reflects meaningful structural volatility.
                    fraction_map = {"1m": 0.18, "5m": 0.28, "15m": 0.40, "30m": 0.55}
                    if timeframe in fraction_map and "atr_14" in htf_slice and not htf_slice["atr_14"].empty:
                        last_daily_atr = float(htf_slice["atr_14"].iloc[-1])
                        stop_atr_value = last_daily_atr * fraction_map[timeframe]

            try:
                decision_pkt = self._run_pipeline(window, symbol, timeframe, htf_window, stop_atr_value)
            except Exception as e:
                logger.debug(f"backtest pipeline error at {ts}: {e}")
                continue
            if decision_pkt is None:
                continue
            decision = decision_pkt["decision"]
            if decision.direction not in ("BUY", "SELL"):
                continue

            # Open a new trade. Entry at next bar's open (realistic — no fill on signal bar).
            entry_price = float(next_candle["open"])
            ctx = decision_pkt["ctx"]
            beh = decision_pkt["beh"]

            # Build the 7-dim feature vector — same logic as analysis_router so
            # winning trades can be seeded into the live DNA library verbatim.
            latest = window.iloc[-1]
            rsi_val = float(latest.get("rsi_14", 50)) if latest.get("rsi_14") == latest.get("rsi_14") else 50
            atr_val = float(latest.get("atr_14", 0)) if latest.get("atr_14") == latest.get("atr_14") else 0
            atr_mean = float(window["atr_14"].mean()) if "atr_14" in window else 1
            ema_alignment = 0.0
            if "ema_11" in latest and "ema_50" in latest:
                if latest["ema_11"] == latest["ema_11"] and latest["ema_50"] == latest["ema_50"] and latest["ema_50"] != 0:
                    ema_alignment = max(-1, min(1, (float(latest["ema_11"]) - float(latest["ema_50"])) / float(latest["ema_50"]) * 100))
            zone_val = {"DISCOUNT": -1, "EQUILIBRIUM": 0, "PREMIUM": 1}.get(ctx.zone, 0)
            phase_val = {"RANGE": 0.2, "TREND": 0.8, "EXHAUSTION": 0.4, "CHAOTIC": 0.1}.get(ctx.phase, 0.5)
            feature_vec = DNAEngine.build_feature_vector(
                ctx.context_score, beh.behavior_score,
                rsi_val, ema_alignment,
                atr_val / atr_mean if atr_mean > 0 else 1,
                zone_val, phase_val,
            )

            tr = BacktestTrade(
                timestamp=ts.isoformat(),
                symbol=symbol,
                timeframe=timeframe,
                direction=decision.direction,
                entry_price=round(entry_price, 2),
                stop_loss=round(float(decision.stop_loss), 2) if decision.stop_loss else 0.0,
                take_profit=round(float(decision.take_profit), 2) if decision.take_profit else 0.0,
                confidence=round(float(decision.confidence), 4),
                final_score=round(float(decision.final_score), 4),
                context_score=round(ctx.context_score, 4),
                behavior_score=round(beh.behavior_score, 4),
                sim_bullish=round(decision_pkt["sim"].bullish_probability, 4),
                sim_bearish=round(decision_pkt["sim"].bearish_probability, 4),
                regime=ctx.regime,
                phase=ctx.phase,
                zone=ctx.zone,
                htf_bias=ctx.htf_bias,
                feature_vector=[round(float(v), 6) for v in feature_vec],
                pattern_signature=beh.pattern_signature or "",
            )
            if not (tr.stop_loss and tr.take_profit):
                continue  # skip ill-formed signals
            open_trades.append(tr)
            trades.append(tr)

        # Close any still-open trades at the last candle's close
        last_close = float(df_full.iloc[-1]["close"])
        last_ts = df_full.index[-1].isoformat()
        for tr in open_trades:
            if tr.outcome == "OPEN":
                tr.exit_timestamp = last_ts
                tr.exit_price = round(last_close, 2)
                if tr.direction == "BUY":
                    tr.pnl = last_close - tr.entry_price
                else:
                    tr.pnl = tr.entry_price - last_close
                tr.pnl_pct = round(tr.pnl / tr.entry_price * 100, 4) if tr.entry_price else 0.0
                tr.outcome = "WIN" if tr.pnl > 0 else "LOSS"
                risk = abs(tr.entry_price - tr.stop_loss)
                tr.rr_realized = round(abs(tr.pnl) / risk, 3) if risk > 0 else 0.0

        runtime_ms = int((datetime.utcnow() - t0).total_seconds() * 1000)
        return self._summarize(symbol, timeframe, df_full, trades, equity_curve, runtime_ms)

    # ──────────────────────────────────────────────
    # PIPELINE (subset of analysis_router, no DB)
    # ──────────────────────────────────────────────

    def _run_pipeline(self, window: pd.DataFrame, symbol: str, timeframe: str,
                       htf_window: Optional[pd.DataFrame] = None,
                       stop_atr: Optional[float] = None):
        # When htf_window is provided, context_engine derives htf_bias from
        # the real higher timeframe instead of the intraday window itself.
        # When stop_atr is provided, decision_engine sizes SL/TP from that
        # value instead of the local ATR(14) — used on intraday TFs to put
        # stops outside intraday noise.
        ctx = context_engine.analyze(window, htf_window)
        beh = behavior_engine.analyze(window, ctx.htf_bias, ctx.zone)

        returns = np.diff(np.log(window["close"].values))
        returns = returns[~np.isnan(returns)]
        if len(returns) < 10:
            return None

        sim = simulation_engine.simulate(
            current_price=float(window["close"].iloc[-1]),
            historical_returns=returns,
            num_sims=80,           # smaller for speed during backtest
            forecast_steps=30,
            regime=ctx.regime,
        )
        scenarios = scenario_engine.build_scenarios(
            sim, ctx.context_score, beh.behavior_score, float(window["close"].iloc[-1])
        )

        rough_conf = abs(
            ctx.context_score * 0.25 + beh.behavior_score * 0.25
            + 0.0 * 0.25 + sim.simulation_bias * 0.25
        )
        unc = uncertainty_engine.evaluate(ctx, beh, _NullDNAResult(), sim, rough_conf)

        weights = {"context": 0.25, "behavior": 0.25, "dna": 0.25, "simulation": 0.25}
        decision = decision_engine.decide(
            window, ctx, beh, _NullDNAResult(), sim, scenarios,
            uncertainty=unc.uncertainty_score, weights=weights,
            stop_atr=stop_atr,
        )
        return {"ctx": ctx, "beh": beh, "sim": sim, "decision": decision}

    # ──────────────────────────────────────────────
    # TRADE RESOLUTION
    # ──────────────────────────────────────────────

    @staticmethod
    def _check_hit(tr: BacktestTrade, candle):
        """Return (outcome, exit_price) or (None, None) if neither SL nor TP hit
        within this candle. Conservative tie-break: if both hit in same candle,
        SL fires first (worst case for the trader)."""
        high = float(candle["high"])
        low = float(candle["low"])
        if tr.direction == "BUY":
            sl_hit = low <= tr.stop_loss
            tp_hit = high >= tr.take_profit
        else:
            sl_hit = high >= tr.stop_loss
            tp_hit = low <= tr.take_profit
        if sl_hit and tp_hit: return "LOSS", tr.stop_loss
        if tp_hit:            return "WIN", tr.take_profit
        if sl_hit:            return "LOSS", tr.stop_loss
        return None, None

    # ──────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────

    def _summarize(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        trades: List[BacktestTrade],
        equity_curve: List[Dict],
        runtime_ms: int,
    ) -> BacktestResult:
        wins = [t for t in trades if t.outcome == "WIN"]
        losses = [t for t in trades if t.outcome == "LOSS"]

        total = len(trades)
        wr = (len(wins) / total) if total else 0.0
        avg_pct = (sum(t.pnl_pct for t in trades) / total) if total else 0.0
        avg_rr = (sum(t.rr_realized for t in wins) / len(wins)) if wins else 0.0

        gross_win = sum(t.pnl_pct for t in wins)
        gross_loss = abs(sum(t.pnl_pct for t in losses)) or 1e-9
        profit_factor = gross_win / gross_loss

        # Sharpe on equity-curve returns (approximate, per-bar)
        eq = np.array([p["equity"] for p in equity_curve])
        if len(eq) > 2:
            eq_returns = np.diff(eq) / eq[:-1]
            mu_r = float(np.mean(eq_returns))
            sd_r = float(np.std(eq_returns))
            # Annualise — bars-per-year depends on timeframe; rough scaling factor
            scale_map = {"1m": 60 * 6 * 252, "5m": 12 * 6 * 252, "15m": 4 * 6 * 252,
                         "1h": 6 * 252, "4h": 252 * 1.5, "1d": 252}
            scale = scale_map.get(timeframe, 252)
            sharpe = (mu_r / sd_r) * math.sqrt(scale) if sd_r > 0 else 0.0
        else:
            sharpe = 0.0

        max_dd = min((p["drawdown"] for p in equity_curve), default=0.0)

        total_pnl_pct = (eq[-1] / eq[0] - 1) * 100 if len(eq) >= 2 else 0.0

        # By-direction breakdown
        by_dir: Dict[str, Dict] = {}
        for d in ("BUY", "SELL"):
            sub = [t for t in trades if t.direction == d]
            sub_wins = sum(1 for t in sub if t.outcome == "WIN")
            by_dir[d] = {
                "count": len(sub),
                "wins": sub_wins,
                "win_rate": round(sub_wins / len(sub), 4) if sub else 0.0,
                "avg_pnl_pct": round(sum(t.pnl_pct for t in sub) / len(sub), 4) if sub else 0.0,
            }

        # By-regime breakdown
        by_reg: Dict[str, Dict] = {}
        regimes = sorted({t.regime for t in trades if t.regime})
        for r in regimes:
            sub = [t for t in trades if t.regime == r]
            sub_wins = sum(1 for t in sub if t.outcome == "WIN")
            by_reg[r] = {
                "count": len(sub),
                "wins": sub_wins,
                "win_rate": round(sub_wins / len(sub), 4) if sub else 0.0,
                "avg_pnl_pct": round(sum(t.pnl_pct for t in sub) / len(sub), 4) if sub else 0.0,
            }

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            bars_processed=len(df),
            start_ts=df.index[0].isoformat(),
            end_ts=df.index[-1].isoformat(),
            runtime_ms=runtime_ms,
            trades=[asdict(t) for t in trades],
            total_trades=total,
            wins=len(wins),
            losses=len(losses),
            open_trades=0,
            win_rate=round(wr, 4),
            avg_pnl_pct=round(avg_pct, 4),
            avg_rr=round(avg_rr, 3),
            profit_factor=round(profit_factor, 3),
            total_pnl_pct=round(total_pnl_pct, 3),
            max_drawdown_pct=round(max_dd, 3),
            sharpe_ratio=round(sharpe, 3),
            equity_curve=equity_curve,
            by_direction=by_dir,
            by_regime=by_reg,
        )

    def _empty(self, symbol: str, timeframe: str, reason: str) -> BacktestResult:
        return BacktestResult(
            symbol=symbol, timeframe=timeframe, bars_processed=0,
            start_ts="", end_ts="", runtime_ms=0,
            trades=[], total_trades=0, wins=0, losses=0, open_trades=0,
            win_rate=0.0, avg_pnl_pct=0.0, avg_rr=0.0, profit_factor=0.0,
            total_pnl_pct=0.0, max_drawdown_pct=0.0, sharpe_ratio=0.0,
            equity_curve=[], by_direction={}, by_regime={"_error": {"reason": reason}},
        )


backtest_engine = BacktestEngine()
