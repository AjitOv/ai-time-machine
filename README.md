# 🕰️ AI Time Machine

> A self-evolving intelligence system that models market behavior and reveals probable futures.

## Architecture

| Engine | Purpose |
|---|---|
| **Data Engine** | Ingests OHLCV data via yfinance, computes RSI/EMA/ATR |
| **Context Engine** | Gatekeeper – evaluates market phase, regime, HTF bias |
| **Behavior Engine** | Detects liquidity sweeps, traps, momentum shifts |
| **DNA Engine** | Pattern memory with cosine similarity matching |
| **Simulation Engine** | Monte Carlo GBM with DNA-biased drift |
| **Scenario Engine** | Constructs Bullish/Bearish/Neutral future scenarios |
| **Decision Engine** | Multi-gate trade decisions with Entry/SL/TP |
| **Uncertainty Engine** | Signal agreement & conflict detection |
| **Risk Engine** | Position sizing & daily risk limits |
| **Learning Engine** | Reinforcement-based weight adaptation |
| **Meta Engine** | Self-evaluation: overfitting, regime stability |

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
python run.py
# → http://localhost:8000

# Frontend
cd frontend
python -m http.server 3005
# → http://localhost:3005
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/analysis/run` | Run full intelligence pipeline |
| GET | `/api/v1/analysis/context` | Get market context |
| GET | `/api/v1/analysis/behavior` | Get behavioral patterns |
| POST | `/api/v1/simulation/run` | Run Monte Carlo simulation |
| GET | `/api/v1/simulation/scenarios` | Get future scenarios |
| GET | `/api/v1/market/data` | Get OHLCV + indicators |
| GET | `/api/v1/system/health` | Health check |
| GET | `/api/v1/system/performance` | Performance metrics |
| GET | `/api/v1/system/weights` | Adaptive model weights |
| GET | `/api/v1/system/trades` | Trade history |

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy (async) + SQLite
- **Frontend**: Vanilla HTML/CSS/JS + TradingView Lightweight Charts
- **Data**: yfinance (multi-timeframe OHLCV)
- **Deployment**: Docker / Render / Vercel
