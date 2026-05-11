"""
Database engine and session management.

Supports two backends transparently:
  - SQLite (default for local dev) — file in ./data/timemachine.db
  - Postgres (production / Render)  — set DATABASE_URL env var

Render Postgres gives URLs as `postgres://user:pass@host:port/db` (legacy
prefix). SQLAlchemy 2.x wants `postgresql+asyncpg://...`, so we normalise
on the way in.
"""

import logging
import os

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


def _normalize_db_url(url: str) -> str:
    """Coerce a Render-style `postgres://` URL (or bare `postgresql://`) to
    the async driver form SQLAlchemy 2.x expects."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+" not in url.split("://", 1)[0]:
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


_RAW_URL = settings.DATABASE_URL
DB_URL = _normalize_db_url(_RAW_URL)

# Only create the local data/ directory when we're actually using SQLite.
# Postgres URLs make this irrelevant (and on Render the directory may be RO).
if _is_sqlite(DB_URL):
    _db_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
    )
    os.makedirs(_db_dir, exist_ok=True)
    logger.info(f"Database backend: SQLite at {_db_dir}/timemachine.db")
else:
    # Don't log the password — mask it.
    _safe = DB_URL
    if "@" in _safe and "//" in _safe:
        scheme_split = _safe.split("//", 1)
        host_part = scheme_split[1]
        if "@" in host_part:
            _safe = f"{scheme_split[0]}//*****@{host_part.split('@', 1)[1]}"
    logger.info(f"Database backend: Postgres at {_safe}")


# Engine kwargs differ by backend — Postgres benefits from connection
# pooling + pre-ping (Render naps idle DBs); SQLite needs neither.
_engine_kwargs: dict = {
    "echo": settings.DEBUG,
    "future": True,
}
if not _is_sqlite(DB_URL):
    _engine_kwargs.update({
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,        # detect & replace dead connections
        "pool_recycle": 1800,         # recycle every 30 min
    })

engine = create_async_engine(DB_URL, **_engine_kwargs)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def init_db():
    """Create all tables if they don't exist. Idempotent — safe to call
    on every boot, whether the DB is fresh or already populated."""
    async with engine.begin() as conn:
        from app.models import (  # noqa: F401 – import to register models
            market_data,
            features,
            trades,
            setup_dna,
            model_weights,
            performance_logs,
            regime_states,
        )
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """Dependency injection for database sessions."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
