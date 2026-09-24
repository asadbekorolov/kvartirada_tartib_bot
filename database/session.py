from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database.base import Base

# Engine configuration
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# Session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables in the database if they do not exist, and migrate missing columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def migrate_schema(sync_conn):
            # Check and add assigned_day and telegram_id if not present in users table
            try:
                sync_conn.exec_driver_sql("ALTER TABLE users ADD COLUMN assigned_day INTEGER")
            except Exception:
                pass
            try:
                sync_conn.exec_driver_sql("ALTER TABLE users ADD COLUMN telegram_id BIGINT")
            except Exception:
                pass

        await conn.run_sync(migrate_schema)

