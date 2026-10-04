"""Подключение к базе данных и управление сессиями."""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.db.models import Base


def create_db_engine(database_url: str) -> AsyncEngine:
    """Создаёт асинхронный движок SQLAlchemy.

    Если используется SQLite, автоматически создаёт директорию для файла БД.
    """
    if database_url.startswith("sqlite+aiosqlite:///"):
        db_path = database_url.replace("sqlite+aiosqlite:///", "")
        if db_path.startswith("./"):
            db_path = db_path[2:]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    return create_async_engine(database_url, echo=False)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику сессий для работы с БД."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Инициализация базы данных — создание всех таблиц и безопасная миграция колонок."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Безопасно добавляем колонку network, если база уже существовала
        try:
            await conn.execute(text("ALTER TABLE tracked_items ADD COLUMN network TEXT"))
        except Exception:
            pass
