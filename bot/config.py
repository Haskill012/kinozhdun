"""Конфигурация бота КиноЖдун."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class Settings:
    """Настройки приложения, загружаемые из переменных окружения."""

    TELEGRAM_BOT_TOKEN: str
    TMDB_API_KEY: str
    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/kinozhdun.db"
    CHECK_INTERVAL_HOURS: int = 6
    ANNOUNCED_CHECK_INTERVAL_HOURS: int = 2
    MAX_ITEMS_PER_USER: int = 50
    TMDB_IMAGE_BASE_URL: str = "https://image.tmdb.org/t/p/w500"

    @classmethod
    def from_env(cls) -> "Settings":
        """Загрузка конфигурации из переменных окружения (.env файла)."""
        load_dotenv()

        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env файле")

        api_key = os.getenv("TMDB_API_KEY", "")
        if not api_key:
            raise ValueError("TMDB_API_KEY не задан в .env файле")

        return cls(
            TELEGRAM_BOT_TOKEN=token,
            TMDB_API_KEY=api_key,
            TMDB_BASE_URL=os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3"),
            DATABASE_URL=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/kinozhdun.db"),
            CHECK_INTERVAL_HOURS=int(os.getenv("CHECK_INTERVAL_HOURS", "6")),
            ANNOUNCED_CHECK_INTERVAL_HOURS=int(os.getenv("ANNOUNCED_CHECK_INTERVAL_HOURS", "2")),
            MAX_ITEMS_PER_USER=int(os.getenv("MAX_ITEMS_PER_USER", "50")),
            TMDB_IMAGE_BASE_URL=os.getenv("TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p/w500"),
        )
