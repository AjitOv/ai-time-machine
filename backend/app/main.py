"""
AI Time Machine – FastAPI Application Entry Point.

A self-evolving intelligence system that models market behavior
and reveals probable futures.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.api.v1.router import router as v1_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("timemachine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # ── STARTUP ──
    logger.info("=" * 60)
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  Default symbol: {settings.DEFAULT_SYMBOL}")
    logger.info("=" * 60)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Pre-fetch data for default symbol
    from app.engines.data_engine import data_engine
    logger.info(f"Pre-fetching data for {settings.DEFAULT_SYMBOL}...")
    try:
        data_engine.fetch_historical(settings.DEFAULT_SYMBOL, "1h")
        data_engine.fetch_historical(settings.DEFAULT_SYMBOL, "4h")
        logger.info("Data pre-fetch complete")
    except Exception as e:
        logger.warning(f"Data pre-fetch failed (non-fatal): {e}")

    # Auto-start the paper-trading loop if enabled in settings
    if settings.PAPER_LOOP_ENABLED:
        from app.engines.paper_loop import paper_loop
        await paper_loop.start()
        logger.info("Paper-trading loop auto-started (PAPER_LOOP_ENABLED=true)")

    yield

    # ── SHUTDOWN ──
    logger.info("Shutting down AI Time Machine")
    try:
        from app.engines.paper_loop import paper_loop
        await paper_loop.stop()
    except Exception as e:
        logger.debug(f"paper_loop stop error: {e}")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="A self-evolving intelligence system that models market behavior and reveals probable futures.",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(v1_router)


# Root endpoint
@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "A self-evolving intelligence system that models market behavior and reveals probable futures.",
        "endpoints": {
            "api_docs": "/docs",
            "health": "/api/v1/system/health",
            "analysis": "/api/v1/analysis/run",
            "simulation": "/api/v1/simulation/run",
        }
    }
