"""System health & management API endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.trades import Trade
from app.models.model_weights import ModelWeight
from app.engines.learning_engine import learning_engine
from app.engines.meta_engine import meta_engine

router = APIRouter()


@router.get("/health")
async def health_check():
    """System health check."""
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "default_symbol": settings.DEFAULT_SYMBOL,
    }


@router.get("/performance")
async def get_performance(
    symbol: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get performance metrics."""
    sym = symbol or settings.DEFAULT_SYMBOL
    stats = await learning_engine.get_performance_stats(db, sym)
    meta = await meta_engine.evaluate(db, sym)

    return {
        "symbol": sym,
        "performance": stats,
        "meta": {
            "health_status": meta.health_status,
            "performance_trend": meta.performance_trend,
            "regime_stable": meta.regime_stable,
            "overfitting_risk": meta.overfitting_risk,
            "recommended_actions": meta.recommended_actions,
        },
    }


@router.get("/weights")
async def get_weights(
    db: AsyncSession = Depends(get_db),
):
    """Get current adaptive model weights."""
    weights = await learning_engine.get_weights(db)
    return {"weights": weights}


@router.get("/trades")
async def get_trade_history(
    symbol: str = Query(default=None),
    limit: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
):
    """Get trade history log."""
    sym = symbol or settings.DEFAULT_SYMBOL
    query = select(Trade).order_by(Trade.timestamp.desc()).limit(limit)
    if sym:
        query = query.where(Trade.symbol == sym)

    result = await db.execute(query)
    trades = result.scalars().all()

    return {
        "symbol": sym,
        "count": len(trades),
        "trades": [t.to_dict() for t in trades],
    }


@router.get("/dna")
async def get_dna_library(
    symbol: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Get DNA library."""
    from app.models.setup_dna import SetupDNA

    sym = symbol or settings.DEFAULT_SYMBOL
    result = await db.execute(
        select(SetupDNA)
        .where(SetupDNA.symbol == sym)
        .order_by(SetupDNA.reliability_score.desc())
        .limit(20)
    )
    records = result.scalars().all()

    return {
        "symbol": sym,
        "count": len(records),
        "dna_library": [r.to_dict() for r in records],
    }
