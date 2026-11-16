import os
from dataclasses import dataclass, field
from dotenv import load_dotenv


@dataclass
class VKBotSettings:
    VK_BOT_TOKEN: str
    TMDB_API_KEY: str
    VK_BOT_GROUP_ID: int = 242087163
    VK_DATABASE_URL: str = 'sqlite+aiosqlite:///./data/kinozhdun_vk.db'
    TMDB_BASE_URL: str = 'https://api.themoviedb.org/3'
    TMDB_IMAGE_BASE_URL: str = 'https://image.tmdb.org/t/p/w500'
    SITE_BASE_URL: str = 'https://kinojdun.ru'
    CHECK_INTERVAL_HOURS: int = 6
    MAX_ITEMS_PER_USER: int = 50
    ADMIN_USER_IDS: list[int] = field(default_factory=list)

    @classmethod
    def from_env(cls):
        load_dotenv()
        token = os.getenv('VK_BOT_TOKEN', '').strip()
        tmdb = os.getenv('TMDB_API_KEY', '').strip()
        if not token or not tmdb:
            raise ValueError('VK_BOT_TOKEN and TMDB_API_KEY are required')
        return cls(
            VK_BOT_TOKEN=token, TMDB_API_KEY=tmdb,
            VK_BOT_GROUP_ID=int(os.getenv('VK_BOT_GROUP_ID', '242087163')),
            VK_DATABASE_URL=os.getenv('VK_DATABASE_URL', 'sqlite+aiosqlite:///./data/kinozhdun_vk.db'),
            TMDB_BASE_URL=os.getenv('TMDB_BASE_URL', 'https://api.themoviedb.org/3'),
            TMDB_IMAGE_BASE_URL=os.getenv('TMDB_IMAGE_BASE_URL', 'https://image.tmdb.org/t/p/w500'),
            SITE_BASE_URL=os.getenv('SITE_BASE_URL', 'https://kinojdun.ru'),
            CHECK_INTERVAL_HOURS=max(1, int(os.getenv('CHECK_INTERVAL_HOURS', '6'))),
            MAX_ITEMS_PER_USER=max(1, int(os.getenv('MAX_ITEMS_PER_USER', '50'))),
        )
