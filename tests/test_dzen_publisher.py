"""Тесты сервиса автопостинга в Дзен и DzenPublisher."""

import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp.test_utils import AioHTTPTestCase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.config import Settings
from bot.db.models import Base, DzenPost
from bot.db.repositories import Repository
from bot.services.dzen_publisher import (
    DzenPublisher,
    build_dzen_hashtags,
    format_dzen_post_text,
    format_dzen_daily_digest,
    format_dzen_weekly_digest,
)
import unittest


class TestDzenFormatting(unittest.TestCase):
    """Тестирование текстового форматирования и генерации хэштегов для Дзена."""

    def test_build_dzen_hashtags(self):
        tags_tv = build_dzen_hashtags(media_type="tv", genres=["фантастика", "триллер"])
        self.assertIn("#кино", tags_tv)
        self.assertIn("#сериалы", tags_tv)
        self.assertNotIn("2026", tags_tv)
        self.assertLessEqual(len(tags_tv.split()), 4)
        self.assertIn("#фантастика", tags_tv)
        self.assertIn("#кинождун", tags_tv)

        tags_movie = build_dzen_hashtags(media_type="movie", genres=["боевик"])
        self.assertIn("#фильмы", tags_movie)
        self.assertIn("#боевики", tags_movie)

    def test_format_dzen_post_text_movie_announced(self):
        text = format_dzen_post_text(
            title="Дюна: Часть третья",
            media_type="movie",
            event_type="date_announced",
            air_date=datetime.date(2027, 6, 3),
            genres=["фантастика", "приключения"],
            network="Warner Bros.",
            overview="Продолжение эпической саги Дени Вильнёва.",
            tmdb_id=12345,
            site_url="https://kinojdun.ru",
            bot_username="kinojdun_bot",
        )
        self.assertIn("Дюна: Часть третья", text)
        self.assertIn("03.06.2027", text)
        self.assertIn("Warner Bros.", text)
        self.assertIn("Продолжение эпической саги", text)
        self.assertIn("https://www.themoviedb.org/movie/12345", text)
        self.assertIn("https://kinojdun.ru/title/movie/12345", text)
        self.assertNotIn("#кино", text)
        self.assertIn("Источник:", text)

    def test_format_dzen_post_text_series_renewed(self):
        text = format_dzen_post_text(
            title="Очень странные дела",
            media_type="tv",
            event_type="renewed",
            season_number=5,
            air_date=datetime.date(2027, 1, 4),
            genres=["ужасы", "детектив"],
            network="Netflix",
            tmdb_id=66732,
        )
        self.assertIn("Очень странные дела", text)
        self.assertIn("5 сезон", text)
        self.assertIn("Netflix", text)
        self.assertIn("https://kinojdun.ru/title/tv/66732", text)
        self.assertNotIn("#сериалы", text)
        self.assertIn("Источник:", text)

    def test_format_dzen_post_text_with_trailer(self):
        text = format_dzen_post_text(
            title="Гладиатор 2",
            media_type="movie",
            event_type="trailer",
            trailer_url="https://youtube.com/watch?v=sample",
            tmdb_id=558449,
        )
        self.assertIn("Трейлер:", text)
        self.assertNotIn("Официальный", text)
        self.assertIn("https://youtube.com/watch?v=sample", text)

    def test_format_dzen_daily_digest(self):
        items = [
            {
                "title": "Дом Дракона",
                "tag": "старт 3 сезона",
                "network": "HBO Max",
                "media_type": "tv",
                "tmdb_id": 94997,
            },
            {
                "title": "Гладиатор 2",
                "tag": "премьера фильма",
                "network": "Paramount",
                "media_type": "movie",
                "tmdb_id": 558449,
            },
        ]
        text = format_dzen_daily_digest(
            items=items,
            date_label="15 октября 2026",
            site_url="https://kinojdun.ru",
            bot_username="kinojdun_bot",
        )
        self.assertIn("Фильмы и новые серии сегодня — 15 октября 2026", text)
        self.assertIn("1. «Дом Дракона»", text)
        self.assertIn("старт 3 сезона", text)
        self.assertIn("2. «Гладиатор 2»", text)
        self.assertIn("премьера фильма", text)
        self.assertIn("https://www.themoviedb.org/tv/94997", text)
        self.assertIn("https://kinojdun.ru/calendar", text)

    def test_format_dzen_weekly_digest(self):
        items = [
            {
                "title": "Бэтмен 2",
                "tag": "премьера фильма",
                "date_str": "18.10.2026",
                "network": "Warner Bros.",
                "media_type": "movie",
                "tmdb_id": 414906,
            },
            {
                "title": "Разделение",
                "tag": "старт 2 сезона",
                "date_str": "20.10.2026",
                "network": "Apple TV+",
                "media_type": "tv",
                "tmdb_id": 93405,
            },
        ]
        text = format_dzen_weekly_digest(
            items=items,
            range_label="15.10.2026 – 21.10.2026",
            site_url="https://kinojdun.ru",
            bot_username="kinojdun_bot",
        )
        self.assertIn("Главные премьеры недели", text)
        self.assertIn("«Бэтмен 2»", text)
        self.assertIn("«Разделение»", text)
        self.assertIn("https://kinojdun.ru/calendar", text)


class TestDzenPublisherAsync(unittest.IsolatedAsyncioTestCase):
    """Асинхронные тесты работы DzenPublisher с БД и дедупликацией."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        self.settings = Settings(
            TELEGRAM_BOT_TOKEN="fake_token",
            TMDB_API_KEY="fake_key",
            DZEN_POSTING_ENABLED=True,
            DZEN_AUTO_PUBLISH=True,
            DZEN_SYNC_MODE="rss",
            DZEN_MIN_POST_INTERVAL_MINUTES=15,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_publisher_disabled_skips(self):
        self.settings.DZEN_POSTING_ENABLED = False
        publisher = DzenPublisher(self.session_factory, self.settings)
        post = await publisher.publish_event(title="Тест", media_type="movie", tmdb_id=123)
        self.assertIsNone(post)
        await publisher.close()

    async def test_publish_event_and_deduplication(self):
        publisher = DzenPublisher(self.session_factory, self.settings)

        # 1. Первая публикация — успешно создаётся
        post1 = await publisher.publish_event(
            title="Дюна 3",
            media_type="movie",
            event_type="date_announced",
            air_date=datetime.date(2027, 5, 1),
            tmdb_id=999,
        )
        self.assertIsNotNone(post1)
        self.assertEqual(post1.title, "Дюна 3")
        self.assertEqual(post1.status, "prepared")
        self.assertIsNone(post1.dzen_publication_id)

        # 2. Повторная публикация того же события — дедуплицируется
        post2 = await publisher.publish_event(
            title="Дюна 3",
            media_type="movie",
            event_type="date_announced",
            air_date=datetime.date(2027, 5, 1),
            tmdb_id=999,
        )
        self.assertIsNone(post2)

        # 3. Проверка записи в БД
        async with self.session_factory() as session:
            repo = Repository(session)
            last = await repo.get_last_published_dzen_post()
            self.assertIsNotNone(last)
            self.assertEqual(last.title, "Дюна 3")

        await publisher.close()

    async def test_publish_pending_queue(self):
        # Отключаем автопубликацию (SAFE MODE)
        self.settings.DZEN_AUTO_PUBLISH = False
        publisher = DzenPublisher(self.session_factory, self.settings)

        post = await publisher.publish_event(
            title="Отложенный фильм",
            media_type="movie",
            tmdb_id=888,
        )
        self.assertIsNotNone(post)
        self.assertEqual(post.status, "pending")

        # Теперь включаем автопубликацию и досылаем очередь
        self.settings.DZEN_AUTO_PUBLISH = True
        published_count = await publisher.publish_pending_queue()
        self.assertEqual(published_count, 1)

        async with self.session_factory() as session:
            repo = Repository(session)
            pending = await repo.get_pending_dzen_posts()
            self.assertEqual(len(pending), 0)

        await publisher.close()

    async def test_publish_test_post(self):
        publisher = DzenPublisher(self.session_factory, self.settings)
        res = await publisher.publish_test_post()
        self.assertIn("Тестовое подключение", res["title"])
        self.assertFalse(res["result"]["success"])
        self.assertEqual(res["result"]["error"], "production_test_disabled")
        await publisher.close()
