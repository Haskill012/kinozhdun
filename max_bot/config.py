"""Конфигурация бота КиноЖдун для мессенджера Макс (MAX Messenger)."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class MaxBotSettings:
    """Настройки бота MAX, загружаемые из переменных окружения."""

    MAX_BOT_TOKEN: str
    TMDB_API_KEY: str
    TMDB_BASE_URL: str = "https://api.themoviedb.org/3"
    TMDB_IMAGE_BASE_URL: str = "https://image.tmdb.org/t/p/w500"
    MAX_DATABASE_URL: str = "sqlite+aiosqlite:///./data/kinozhdun_max.db"
    CHECK_INTERVAL_HOURS: int = 6
    MAX_ITEMS_PER_USER: int = 50
    SITE_BASE_URL: str = "https://kinojdun.ru"
    POLL_TIMEOUT_SECONDS: int = 25
    ADMIN_USER_IDS: list[int] = None  # type: ignore

    def __post_init__(self):
        if self.ADMIN_USER_IDS is None:
            self.ADMIN_USER_IDS = []

    @classmethod
    def from_env(cls) -> "MaxBotSettings":
        """Загрузка конфигурации из переменных окружения."""
        load_dotenv()

        token = os.getenv("MAX_BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("MAX_BOT_TOKEN не задан в .env файле")

        tmdb_api_key = os.getenv("TMDB_API_KEY", "").strip()
        if not tmdb_api_key:
            raise ValueError("TMDB_API_KEY не задан в .env файле")

        raw_admins = os.getenv("ADMIN_USER_IDS", "")
        admin_ids: list[int] = []
        if raw_admins:
            for admin_str in raw_admins.split(","):
                admin_str = admin_str.strip()
                if admin_str.isdigit():
                    admin_ids.append(int(admin_str))

        return cls(
            MAX_BOT_TOKEN=token,
            TMDB_API_KEY=tmdb_api_key,
            TMDB_BASE_URL=os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3").strip(),
            TMDB_IMAGE_BASE_URL=os.getenv("TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p/w500").strip(),
            MAX_DATABASE_URL=os.getenv("MAX_DATABASE_URL", "sqlite+aiosqlite:///./data/kinozhdun_max.db").strip(),
            CHECK_INTERVAL_HOURS=int(os.getenv("CHECK_INTERVAL_HOURS", "6")),
            MAX_ITEMS_PER_USER=int(os.getenv("MAX_ITEMS_PER_USER", "50")),
            SITE_BASE_URL=os.getenv("SITE_BASE_URL", "https://kinojdun.ru").strip(),
            POLL_TIMEOUT_SECONDS=int(os.getenv("MAX_POLL_TIMEOUT", "25")),
            ADMIN_USER_IDS=admin_ids,
        )
