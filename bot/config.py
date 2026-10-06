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
    BOT_USERNAME: str = "kinojdun_bot"
    TELEGRAM_CHANNEL_ID: str | None = None
    CHANNEL_POSTING_ENABLED: bool = False
    CHANNEL_AUTO_PUBLISH: bool = True
    CHANNEL_MIN_POST_INTERVAL_MINUTES: int = 15
    ADMIN_USER_IDS: list[int] = None  # type: ignore
    DAILY_DIGEST_ENABLED: bool = True
    DAILY_DIGEST_HOUR: int = 9
    WEEKLY_DIGEST_ENABLED: bool = True
    WEEKLY_DIGEST_DAY: int = 0  # 0 = Monday
    WEEKLY_DIGEST_HOUR: int = 10
    SITE_BASE_URL: str = "https://kinojdun.ru"
    SITE_ASIAN_MIN_VOTES: int = 1000
    SITE_ASIAN_MIN_POPULARITY: float = 20
    SITE_AUDIENCE_ALLOW_KEYS: tuple[str, ...] = ()

    def __post_init__(self):
        if self.ADMIN_USER_IDS is None:
            self.ADMIN_USER_IDS = []

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

        channel_enabled = os.getenv("CHANNEL_POSTING_ENABLED", "false").lower() in ("true", "1", "yes")

        # Поддерживаем оба имени: CHANNEL_AUTO_PUBLISH и TELEGRAM_CHANNEL_AUTO_PUBLISH
        raw_auto = os.getenv("CHANNEL_AUTO_PUBLISH")
        if raw_auto is None:
            raw_auto = os.getenv("TELEGRAM_CHANNEL_AUTO_PUBLISH", "true")
        channel_auto = raw_auto.lower() in ("true", "1", "yes")

        # Парсинг ID администраторов
        raw_admins = os.getenv("ADMIN_USER_IDS", "")
        admin_ids: list[int] = []
        if raw_admins:
            for part in raw_admins.split(","):
                part_clean = part.strip()
                if part_clean.isdigit():
                    admin_ids.append(int(part_clean))

        return cls(
            TELEGRAM_BOT_TOKEN=token,
            TMDB_API_KEY=api_key,
            TMDB_BASE_URL=os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3"),
            DATABASE_URL=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/kinozhdun.db"),
            CHECK_INTERVAL_HOURS=int(os.getenv("CHECK_INTERVAL_HOURS", "6")),
            ANNOUNCED_CHECK_INTERVAL_HOURS=int(os.getenv("ANNOUNCED_CHECK_INTERVAL_HOURS", "2")),
            MAX_ITEMS_PER_USER=int(os.getenv("MAX_ITEMS_PER_USER", "50")),
            TMDB_IMAGE_BASE_URL=os.getenv("TMDB_IMAGE_BASE_URL", "https://image.tmdb.org/t/p/w500"),
            BOT_USERNAME=os.getenv("BOT_USERNAME", "kinojdun_bot").lstrip("@"),
            TELEGRAM_CHANNEL_ID=os.getenv("TELEGRAM_CHANNEL_ID"),
            CHANNEL_POSTING_ENABLED=channel_enabled,
            CHANNEL_AUTO_PUBLISH=channel_auto,
            CHANNEL_MIN_POST_INTERVAL_MINUTES=int(os.getenv("CHANNEL_MIN_POST_INTERVAL_MINUTES", "15")),
            ADMIN_USER_IDS=admin_ids,
            DAILY_DIGEST_ENABLED=os.getenv("DAILY_DIGEST_ENABLED", "true").lower() in ("true", "1", "yes"),
            DAILY_DIGEST_HOUR=int(os.getenv("DAILY_DIGEST_HOUR", "9")),
            WEEKLY_DIGEST_ENABLED=os.getenv("WEEKLY_DIGEST_ENABLED", "true").lower() in ("true", "1", "yes"),
            WEEKLY_DIGEST_DAY=int(os.getenv("WEEKLY_DIGEST_DAY", "0")),
            WEEKLY_DIGEST_HOUR=int(os.getenv("WEEKLY_DIGEST_HOUR", "10")),
            SITE_BASE_URL=os.getenv("SITE_BASE_URL", "https://kinojdun.ru"),
            SITE_ASIAN_MIN_VOTES=max(50, int(os.getenv("SITE_ASIAN_MIN_VOTES", "1000"))),
            SITE_ASIAN_MIN_POPULARITY=max(0, float(os.getenv("SITE_ASIAN_MIN_POPULARITY", "20"))),
            SITE_AUDIENCE_ALLOW_KEYS=tuple(k.strip() for k in os.getenv("SITE_AUDIENCE_ALLOW_KEYS", "").split(',') if k.strip()),
        )

