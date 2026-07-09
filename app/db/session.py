"""Async database session management."""
import time
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import Base

logger = get_logger(__name__)
settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for async database session."""
    start = time.perf_counter()
    logger.info("db_session_opened")
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
            logger.info(
                "db_session_committed",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "db_session_rolled_back",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise
        finally:
            await session.close()
            logger.info(
                "db_session_closed",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def init_db() -> None:
    """Create tables only when explicitly enabled."""
    start = time.perf_counter()
    if not settings.create_db_on_startup:
        logger.info("db_init_skipped", create_db_on_startup=False)
        return

    logger.info("db_init_started", create_db_on_startup=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db_init_finished", duration_ms=round((time.perf_counter() - start) * 1000, 2))
