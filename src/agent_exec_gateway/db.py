from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base, Host

settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        existing = await session.scalar(select(Host).where(Host.name == "local"))
        if existing is None:
            session.add(Host(name="local", transport="local"))
            await session.commit()
