from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_all_tables() -> None:
    from app.models import (  # noqa: F401  – import side-effects register models
        instruments,
        options_snapshot,
        chain_snapshot,
        commodity_snapshot,
        positioning_signal,
        gamma_levels,
        max_pain_levels,
        options_flow,
        user,
        alert,
        user_events,
        trading_signal,
        buy_signal_history,
        underlying_bar,
        signal_feature_snapshot,
        dashboard_snapshot_cache,
        market_summary_cache,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
