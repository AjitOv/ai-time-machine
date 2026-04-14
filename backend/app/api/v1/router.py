"""Main API router – includes all sub-routers."""

from fastapi import APIRouter
from app.api.v1.market import router as market_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.simulation import router as simulation_router
from app.api.v1.system import router as system_router

router = APIRouter(prefix="/api/v1")

router.include_router(market_router, prefix="/market", tags=["Market Data"])
router.include_router(analysis_router, prefix="/analysis", tags=["Analysis"])
router.include_router(simulation_router, prefix="/simulation", tags=["Simulation"])
router.include_router(system_router, prefix="/system", tags=["System"])
