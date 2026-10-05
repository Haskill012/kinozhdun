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
    connect_args = {}
    if database_url.startswith("sqlite"):
        db_path = database_url.replace("sqlite+aiosqlite:///", "")
        if db_path.startswith("./"):
            db_path = db_path[2:]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"timeout": 30}

    return create_async_engine(database_url, echo=False, connect_args=connect_args)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создаёт фабрику сессий для работы с БД."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Инициализация базы данных — создание всех таблиц и безопасная миграция колонок."""
    async with engine.begin() as conn:
        try:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA busy_timeout=30000"))
        except Exception:
            pass

        await conn.run_sync(Base.metadata.create_all)

        # Проверяем, требует ли channel_posts миграции (снятия NOT NULL с tmdb_id и media_type)
        try:
            info_res = await conn.execute(text("PRAGMA table_info(channel_posts)"))
            cols = {row[1]: row[3] for row in info_res.fetchall()}
            if cols.get("tmdb_id") == 1 or cols.get("media_type") == 1:
                await conn.execute(text("ALTER TABLE channel_posts RENAME TO _channel_posts_old"))
                await conn.run_sync(Base.metadata.tables["channel_posts"].create)
                # Копируем существующие данные если они есть
                old_cols_res = await conn.execute(text("PRAGMA table_info(_channel_posts_old)"))
                old_col_names = [r[1] for r in old_cols_res.fetchall()]
                new_cols_res = await conn.execute(text("PRAGMA table_info(channel_posts)"))
                new_col_names = [r[1] for r in new_cols_res.fetchall()]
                common_cols = [c for c in old_col_names if c in new_col_names]
                if common_cols:
                    cols_str = ", ".join(common_cols)
                    await conn.execute(text(f"INSERT INTO channel_posts ({cols_str}) SELECT {cols_str} FROM _channel_posts_old"))
                await conn.execute(text("DROP TABLE _channel_posts_old"))
        except Exception:
            pass

        # Безопасно добавляем колонки в существующие таблицы
        for alter_sql in [
            "ALTER TABLE tracked_items ADD COLUMN network TEXT",
            "ALTER TABLE users ADD COLUMN referral_source TEXT",
            "ALTER TABLE users ADD COLUMN referrer_id BIGINT",
            "ALTER TABLE channel_posts ADD COLUMN post_type TEXT DEFAULT 'news'",
            "ALTER TABLE channel_posts ADD COLUMN source TEXT DEFAULT 'tmdb'",
            "ALTER TABLE channel_posts ADD COLUMN credibility TEXT DEFAULT 'confirmed'",
            "ALTER TABLE channel_posts ADD COLUMN post_text TEXT",
            "ALTER TABLE channel_posts ADD COLUMN trailer_url TEXT",
            "ALTER TABLE channel_posts ADD COLUMN payload TEXT",
            "ALTER TABLE channel_posts ADD COLUMN is_sponsored BOOLEAN DEFAULT 0",
            "ALTER TABLE channel_posts ADD COLUMN partner_url TEXT",
            "ALTER TABLE channel_posts ADD COLUMN sponsored_label TEXT",
        ]:
            try:
                await conn.execute(text(alter_sql))
            except Exception:
                pass

