"""
Database session management with async SQLAlchemy.

Provides:
- Async engine with connection pooling
- Session factory for creating database sessions
- FastAPI dependency injection helper
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings


def create_engine():
    """
    Create an async SQLAlchemy engine with connection pooling.
    
    Pool settings explained:
    - pool_size=5: Maintain 5 connections ready in the pool
    - max_overflow=10: Allow up to 10 extra connections under heavy load
    - pool_pre_ping=True: Verify connections are alive before use (prevents stale connection errors)
    - pool_recycle=3600: Recreate connections after 1 hour (prevents timeout issues)
    
    Why these values?
    - 5 base connections handles typical concurrent requests
    - 10 overflow handles traffic spikes
    - Pre-ping adds ~1ms latency but prevents "connection closed" errors
    - 1-hour recycle prevents issues with PostgreSQL connection timeouts
    """
    settings = get_settings()
    
    return create_async_engine(
        settings.database_url,
        echo=settings.log_level == "DEBUG",  # SQL logging in debug mode
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


# Global engine instance (created on import)
engine = create_engine()

# Session factory - creates new sessions
# expire_on_commit=False is CRITICAL for async to prevent lazy loading issues
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Objects remain accessible after commit
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.
    
    Usage in routes:
        @app.post("/v1/agent-runs")
        async def create_run(session: AsyncSession = Depends(get_session)):
            # Use session here
            ...
    
    The session is:
    - Automatically committed on success
    - Automatically rolled back on error
    - Automatically closed when request ends
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions (for use outside FastAPI).
    
    Usage in scripts or background tasks:
        async with get_session_context() as session:
            result = await session.execute(...)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Initialize database connection.
    
    Called during application startup to verify connectivity.
    Note: Table creation is handled by Alembic migrations, not here.
    
    Why separate from migrations?
    - Migrations are run explicitly (alembic upgrade head)
    - This just verifies the connection works
    - Fail fast on startup if DB is unreachable
    """
    async with engine.begin() as conn:
        # Just test the connection
        await conn.run_sync(lambda _: None)
    print("     🫙  Database connection verified")


async def close_db() -> None:
    """
    Close database connections.
    
    Called during application shutdown to clean up resources.
    Important for graceful shutdown - ensures connections are properly closed.
    """
    await engine.dispose()
    print("     🫙  Database connections closed")
