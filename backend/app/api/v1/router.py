"""Main API router – includes all sub-routers."""

from fastapi import APIRouter
from app.api.v1.market import router as market_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.simulation import router as simulation_router
from app.api.v1.system import router as system_router
from app.api.v1.scanner import router as scanner_router
from app.api.v1.symbols import router as symbols_router
from app.api.v1.feed import router as feed_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.data import router as data_router

router = APIRouter(prefix="/api/v1")

router.include_router(market_router, prefix="/market", tags=["Market Data"])
router.include_router(analysis_router, prefix="/analysis", tags=["Analysis"])
router.include_router(simulation_router, prefix="/simulation", tags=["Simulation"])
router.include_router(system_router, prefix="/system", tags=["System"])
router.include_router(scanner_router, prefix="/scanner", tags=["Scanner"])
router.include_router(symbols_router, prefix="/symbols", tags=["Symbols"])
router.include_router(feed_router, prefix="/feed", tags=["Live Feed"])
router.include_router(backtest_router, prefix="/backtest", tags=["Backtest"])
router.include_router(data_router, prefix="/data", tags=["Data Import"])
