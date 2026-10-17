from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.db.connection import create_db_engine
from app.db.migrations import upgrade_database


class Base(DeclarativeBase):
    pass


engine = create_db_engine(settings.db_url)


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_database)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
