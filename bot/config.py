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
    DAILY_DIGEST_SKIP_WEEKLY_DAY: bool = True
    WEEKLY_DIGEST_ENABLED: bool = True
    WEEKLY_DIGEST_DAY: int = 0  # 0 = Monday
    WEEKLY_DIGEST_HOUR: int = 10
    SITE_BASE_URL: str = "https://kinojdun.ru"
    SITE_ASIAN_MIN_VOTES: int = 1000
    SITE_ASIAN_MIN_POPULARITY: float = 20
    SITE_AUDIENCE_ALLOW_KEYS: tuple[str, ...] = ()
    VK_ACCESS_TOKEN: str | None = None
    VK_USER_TOKEN: str | None = None
    VK_GROUP_ID: int | None = None

    VK_POSTING_ENABLED: bool = False
    VK_AUTO_PUBLISH: bool = True
    VK_ATTACHMENT_MODE: str = "photo"
    VK_LINK_IN_COMMENT: bool = False
    VK_CREATE_POLL: bool = True
    VK_POST_HOUR: int = 18
    VK_POST_MINUTE: int = 30
    VK_POST_DAYS: str = "mon-sat"

    DZEN_CHANNEL_URL: str | None = None
    DZEN_CHANNEL_ID: str | None = None
    DZEN_POSTING_ENABLED: bool = False
    DZEN_AUTO_PUBLISH: bool = True
    DZEN_MIN_POST_INTERVAL_MINUTES: int = 15
    DZEN_WEBHOOK_URL: str | None = None
    DZEN_SESSION_TOKEN: str | None = None
    DZEN_SYNC_MODE: str = "telegram_sync"
    DZEN_POST_HOUR: int = 18
    DZEN_POST_MINUTE: int = 30
    DZEN_POST_DAYS: str = "mon,wed,fri,sun"
    SHORTS_ENABLED: bool = True
    SHORTS_AUTO_PUBLISH: bool = True
    SHORTS_DAILY_HOUR: int = 12
    SHORTS_DAILY_MINUTE: int = 0
    YANDEX_SPEECHKIT_API_KEY: str | None = None
    YANDEX_SPEECHKIT_FOLDER_ID: str | None = None
    YANDEX_SPEECHKIT_VOICE: str = "filipp"
    YANDEX_SPEECHKIT_SPEED: str = "1.08"
    YOUTUBE_POSTING_ENABLED: bool = False
    YOUTUBE_CLIENT_ID: str | None = None
    YOUTUBE_CLIENT_SECRET: str | None = None
    YOUTUBE_REFRESH_TOKEN: str | None = None
    YOUTUBE_PRIVACY_STATUS: str = "private"
    YOUTUBE_CATEGORY_ID: str = "1"
    MAX_BOT_TOKEN: str | None = None
    MAX_CHANNEL_ID: int | None = None
    MAX_CHANNEL_POSTING_ENABLED: bool = False

    def __post_init__(self):
        for hour in (self.DAILY_DIGEST_HOUR, self.WEEKLY_DIGEST_HOUR, self.VK_POST_HOUR, self.DZEN_POST_HOUR, self.SHORTS_DAILY_HOUR):
            if not 0 <= hour <= 23:
                raise ValueError("Час публикации должен быть от 0 до 23")
        for minute in (self.VK_POST_MINUTE, self.DZEN_POST_MINUTE, self.SHORTS_DAILY_MINUTE):
            if not 0 <= minute <= 59:
                raise ValueError("Минута публикации должна быть от 0 до 59")
        if not 0 <= self.WEEKLY_DIGEST_DAY <= 6:
            raise ValueError("WEEKLY_DIGEST_DAY должен быть от 0 до 6")
        if self.VK_ATTACHMENT_MODE not in ("community_photo", "photo", "text", "link"):
            raise ValueError("VK_ATTACHMENT_MODE должен быть community_photo, photo, text или link")
        if self.DZEN_SYNC_MODE not in ("telegram_sync", "webhook", "direct", "rss"):
            raise ValueError("DZEN_SYNC_MODE должен быть telegram_sync, webhook, direct или rss")
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
            DAILY_DIGEST_SKIP_WEEKLY_DAY=os.getenv("DAILY_DIGEST_SKIP_WEEKLY_DAY", "true").lower() in ("true", "1", "yes"),
            WEEKLY_DIGEST_ENABLED=os.getenv("WEEKLY_DIGEST_ENABLED", "true").lower() in ("true", "1", "yes"),
            WEEKLY_DIGEST_DAY=int(os.getenv("WEEKLY_DIGEST_DAY", "0")),
            WEEKLY_DIGEST_HOUR=int(os.getenv("WEEKLY_DIGEST_HOUR", "10")),
            SITE_BASE_URL=os.getenv("SITE_BASE_URL", "https://kinojdun.ru"),
            SITE_ASIAN_MIN_VOTES=max(50, int(os.getenv("SITE_ASIAN_MIN_VOTES", "1000"))),
            SITE_ASIAN_MIN_POPULARITY=max(0, float(os.getenv("SITE_ASIAN_MIN_POPULARITY", "20"))),
            SITE_AUDIENCE_ALLOW_KEYS=tuple(k.strip() for k in os.getenv("SITE_AUDIENCE_ALLOW_KEYS", "").split(',') if k.strip()),
            VK_ACCESS_TOKEN=os.getenv("VK_ACCESS_TOKEN") or None,
            VK_USER_TOKEN=os.getenv("VK_USER_TOKEN") or None,
            VK_GROUP_ID=int(os.getenv("VK_GROUP_ID", "").strip()) if os.getenv("VK_GROUP_ID", "").strip().lstrip("-").isdigit() else None,
            VK_POSTING_ENABLED=os.getenv("VK_POSTING_ENABLED", "false").lower() in ("true", "1", "yes"),
            VK_AUTO_PUBLISH=os.getenv("VK_AUTO_PUBLISH", "true").lower() in ("true", "1", "yes"),
            VK_ATTACHMENT_MODE=os.getenv("VK_ATTACHMENT_MODE", "photo").strip().lower(),
            VK_LINK_IN_COMMENT=os.getenv("VK_LINK_IN_COMMENT", "false").lower() in ("true", "1", "yes"),
            VK_CREATE_POLL=os.getenv("VK_CREATE_POLL", "true").lower() in ("true", "1", "yes"),
            VK_POST_HOUR=int(os.getenv("VK_POST_HOUR", "18")),
            VK_POST_MINUTE=int(os.getenv("VK_POST_MINUTE", "30")),
            VK_POST_DAYS=os.getenv("VK_POST_DAYS", "mon-sat"),
            DZEN_CHANNEL_URL=os.getenv("DZEN_CHANNEL_URL") or None,
            DZEN_CHANNEL_ID=os.getenv("DZEN_CHANNEL_ID") or None,
            DZEN_POSTING_ENABLED=os.getenv("DZEN_POSTING_ENABLED", "false").lower() in ("true", "1", "yes"),
            DZEN_AUTO_PUBLISH=os.getenv("DZEN_AUTO_PUBLISH", "true").lower() in ("true", "1", "yes"),
            DZEN_MIN_POST_INTERVAL_MINUTES=int(os.getenv("DZEN_MIN_POST_INTERVAL_MINUTES", "15")),
            DZEN_WEBHOOK_URL=os.getenv("DZEN_WEBHOOK_URL") or None,
            DZEN_SESSION_TOKEN=os.getenv("DZEN_SESSION_TOKEN") or None,
            DZEN_SYNC_MODE=os.getenv("DZEN_SYNC_MODE", "telegram_sync").strip().lower(),
            DZEN_POST_HOUR=int(os.getenv("DZEN_POST_HOUR", "18")),
            DZEN_POST_MINUTE=int(os.getenv("DZEN_POST_MINUTE", "30")),
            DZEN_POST_DAYS=os.getenv("DZEN_POST_DAYS", "mon,wed,fri,sun"),
            SHORTS_ENABLED=os.getenv("SHORTS_ENABLED", "true").lower() in ("true", "1", "yes"),
            SHORTS_AUTO_PUBLISH=os.getenv("SHORTS_AUTO_PUBLISH", "true").lower() in ("true", "1", "yes"),
            SHORTS_DAILY_HOUR=int(os.getenv("SHORTS_DAILY_HOUR", "12")),
            SHORTS_DAILY_MINUTE=int(os.getenv("SHORTS_DAILY_MINUTE", "0")),
            YANDEX_SPEECHKIT_API_KEY=os.getenv("YANDEX_SPEECHKIT_API_KEY") or None,
            YANDEX_SPEECHKIT_FOLDER_ID=os.getenv("YANDEX_SPEECHKIT_FOLDER_ID") or None,
            YANDEX_SPEECHKIT_VOICE=(os.getenv("YANDEX_SPEECHKIT_VOICE") or "filipp").strip(),
            YANDEX_SPEECHKIT_SPEED=(os.getenv("YANDEX_SPEECHKIT_SPEED") or "1.08").strip(),
            YOUTUBE_POSTING_ENABLED=os.getenv("YOUTUBE_POSTING_ENABLED", "false").lower() in ("true", "1", "yes"),
            YOUTUBE_CLIENT_ID=os.getenv("YOUTUBE_CLIENT_ID") or None,
            YOUTUBE_CLIENT_SECRET=os.getenv("YOUTUBE_CLIENT_SECRET") or None,
            YOUTUBE_REFRESH_TOKEN=os.getenv("YOUTUBE_REFRESH_TOKEN") or None,
            YOUTUBE_PRIVACY_STATUS=(os.getenv("YOUTUBE_PRIVACY_STATUS") or "private").strip().lower(),
            YOUTUBE_CATEGORY_ID=(os.getenv("YOUTUBE_CATEGORY_ID") or "1").strip(),
            MAX_BOT_TOKEN=os.getenv("MAX_BOT_TOKEN") or None,
            MAX_CHANNEL_ID=int(os.getenv("MAX_CHANNEL_ID", "").strip()) if os.getenv("MAX_CHANNEL_ID", "").strip().lstrip("-").isdigit() else None,
            MAX_CHANNEL_POSTING_ENABLED=os.getenv("MAX_CHANNEL_POSTING_ENABLED", "false").lower() in ("true", "1", "yes"),
        )
