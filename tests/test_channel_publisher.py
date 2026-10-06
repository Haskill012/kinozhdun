"""Тесты автоматического Telegram-канала «Кинождун 🍿»: события, дедупликация, дайджесты и режимы публикации."""

import json
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.config import Settings
from bot.db.models import Base, TrackedItem, User
from bot.db.repositories import Repository
from bot.services.channel import (
    ChannelPublisher,
    generate_content_hash,
    generate_event_fingerprint,
    channel_post_keyboard,
    format_channel_post_text,
)


class TestChannelPublisher(unittest.IsolatedAsyncioTestCase):
    """Тестирование логики публикации, дедупликации, дайджестов и фильтрации новостей."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        self.settings = Settings(
            TELEGRAM_BOT_TOKEN="mock_token",
            TMDB_API_KEY="mock_key",
            BOT_USERNAME="kinojdun_bot",
            TELEGRAM_CHANNEL_ID="@kinojdun_test_channel",
            CHANNEL_POSTING_ENABLED=True,
            CHANNEL_AUTO_PUBLISH=True,
            CHANNEL_MIN_POST_INTERVAL_MINUTES=15,
            ADMIN_USER_IDS=[99999],
        )

        self.mock_bot = MagicMock()
        self.mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=777))
        self.mock_bot.send_photo = AsyncMock(return_value=MagicMock(message_id=888))

        self.publisher = ChannelPublisher(
            session_factory=self.session_factory,
            settings=self.settings,
            bot=self.mock_bot,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    def test_content_hash_consistency(self):
        """Проверка стабильности и уникальности хэшей дедупликации."""
        h1 = generate_content_hash(82856, "tv", "announced", 2, date(2027, 3, 15))
        h2 = generate_content_hash(82856, "tv", "announced", 2, date(2027, 3, 15))
        self.assertEqual(h1, h2)

        # Другая дата -> другой хэш
        h3 = generate_content_hash(82856, "tv", "announced", 2, date(2027, 4, 1))
        self.assertNotEqual(h1, h3)

        # Другой сезон -> другой хэш
        h4 = generate_content_hash(82856, "tv", "announced", 3, date(2027, 3, 15))
        self.assertNotEqual(h1, h4)

    def test_significance_and_credibility_filter(self):
        """Проверка критериев существенности новости и фильтрации слухов."""
        # Анонс с датой -> существенная
        self.assertTrue(self.publisher.is_significant_news("announced", date(2027, 5, 20)))

        # Анонс без даты -> не для публичного канала
        self.assertFalse(self.publisher.is_significant_news("announced", None))

        # Перенос даты -> существенная
        self.assertTrue(self.publisher.is_significant_news("date_postponed", date(2027, 4, 24)))

        # Продление на новый сезон -> существенная
        self.assertTrue(self.publisher.is_significant_news("renewed"))

        # Съёмки -> существенная
        self.assertTrue(self.publisher.is_significant_news("filming_started"))
        self.assertTrue(self.publisher.is_significant_news("filming_finished"))

        # Трейлер с ссылкой -> существенная
        self.assertTrue(self.publisher.is_significant_news("trailer", trailer_url="https://youtube.com/watch?v=123"))
        self.assertFalse(self.publisher.is_significant_news("trailer", trailer_url=None))

        # Слухи (rumor) -> строго отклоняются даже при совпадении типа события!
        self.assertFalse(self.publisher.is_significant_news("renewed", credibility="rumor"))
        self.assertFalse(self.publisher.is_significant_news("announced", next_air_date=date(2027, 1, 1), credibility="rumor"))

    async def test_deduplication_prevents_duplicate_posts(self):
        """Проверка защиты от повторной публикации одной и той же новости из разных источников."""
        post1 = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="announced",
            title="Фоллаут",
            season_number=2,
            air_date=date(2027, 3, 15),
            network="Prime Video",
        )
        self.assertIsNotNone(post1)
        self.assertEqual(post1.status, "published")
        self.assertEqual(self.mock_bot.send_message.call_count, 1)

        # Повторная попытка опубликовать то же событие
        post2 = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="announced",
            title="Фоллаут",
            season_number=2,
            air_date=date(2027, 3, 15),
            network="Prime Video",
        )
        # Бот НЕ должен отправлять повторное сообщение в канал
        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        self.assertEqual(post1.id, post2.id)

    async def test_date_postponed_creates_distinct_event(self):
        """Проверка сценария: перенос даты премьеры НЕ считается дублем анонса, а создаёт пост о переносе."""
        # 1. Сначала опубликован анонс на 17 апреля
        post_announcement = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="date_announced",
            title="Фоллаут",
            season_number=3,
            air_date=date(2027, 4, 17),
        )
        self.assertIsNotNone(post_announcement)

        # 2. Позже дату официально перенесли на 24 апреля
        post_postponed = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="date_postponed",
            title="Фоллаут",
            season_number=3,
            air_date=date(2027, 4, 24),
            old_air_date=date(2027, 4, 17),
        )
        self.assertIsNotNone(post_postponed)
        self.assertNotEqual(post_announcement.id, post_postponed.id)
        self.assertEqual(post_postponed.event_type, "date_postponed")
        self.assertIn("перенесли", post_postponed.post_text)
        self.assertIn("24.04.2027", post_postponed.post_text)
        self.assertIn("17.04.2027", post_postponed.post_text)

    async def test_renewed_event_formatting_and_cta(self):
        """Проверка публикации продления на новый сезон и контекстной кнопки."""
        post = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="renewed",
            title="Фоллаут",
            season_number=3,
            network="Amazon",
        )
        self.assertIsNotNone(post)
        self.assertIn("официально продлён на 3 сезон", post.post_text)
        self.assertIn("Amazon подтвердил продолжение", post.post_text)

        kb = channel_post_keyboard(post.id, "kinojdun_bot", "Фоллаут", event_type="renewed", season_number=3)
        btn = kb.inline_keyboard[0][0]
        self.assertEqual(btn.text, "🔔 Ждать 3 сезон")
        self.assertEqual(btn.url, f"https://t.me/kinojdun_bot?start=ch_{post.id}")

    async def test_trailer_event_has_two_buttons(self):
        """Проверка публикации официального трейлера: кнопка просмотра + кнопка отслеживания."""
        trailer_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        post = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="trailer",
            title="Фоллаут",
            season_number=2,
            air_date=date(2027, 4, 17),
            trailer_url=trailer_url,
        )
        self.assertIsNotNone(post)
        self.assertIn("Вышел официальный трейлер нового сезона «Фоллаут»", post.post_text)

        kb = channel_post_keyboard(
            post.id,
            "kinojdun_bot",
            "Фоллаут",
            event_type="trailer",
            season_number=2,
            trailer_url=trailer_url,
        )
        # Должно быть 2 ряда кнопок: 1) ▶️ Смотреть трейлер, 2) 🔔 Отслеживать премьеру
        self.assertEqual(len(kb.inline_keyboard), 2)
        watch_btn = kb.inline_keyboard[0][0]
        self.assertEqual(watch_btn.text, "▶️ Смотреть трейлер")
        self.assertEqual(watch_btn.url, trailer_url)

        track_btn = kb.inline_keyboard[1][0]
        self.assertEqual(track_btn.text, "🔔 Отслеживать премьеру")
        self.assertEqual(track_btn.url, f"https://t.me/kinojdun_bot?start=ch_{post.id}")

    async def test_safe_mode_queues_and_notifies_admins(self):
        """Проверка SAFE MODE: пост создаётся в pending и отправляет уведомление администратору."""
        self.settings.CHANNEL_AUTO_PUBLISH = False

        post = await self.publisher.process_update_for_channel(
            tmdb_id=82856,
            media_type="tv",
            event_type="filming_started",
            title="Фоллаут",
            season_number=3,
        )
        self.assertIsNotNone(post)
        self.assertEqual(post.status, "pending")
        # В канал пост НЕ отправлялся
        self.assertEqual(self.mock_bot.send_photo.call_count, 0)
        # Но администратору отправлено сообщение с кнопками модерации
        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        call_chat_id = self.mock_bot.send_message.call_args[1]["chat_id"]
        self.assertEqual(call_chat_id, 99999)

    async def test_automatic_queue_skips_legacy_news_without_blocking_digests(self):
        async with self.session_factory() as session:
            repo = Repository(session)
            news = await repo.create_channel_post(
                title="Legacy personal update", content_hash="legacy-news",
                event_type="announced", post_text="Personal update", status="pending",
            )
            digest = await repo.create_channel_post(
                title="Premiere collection", content_hash="collection",
                post_type="daily_digest", event_type="daily_digest",
                post_text="Today's premieres", status="pending",
            )
            await session.commit()

        self.assertEqual(await self.publisher.publish_pending_queue(), 1)
        self.mock_bot.send_message.assert_awaited_once()
        self.assertEqual(self.mock_bot.send_message.call_args.kwargs["text"], "Today's premieres")
        async with self.session_factory() as session:
            repo = Repository(session)
            self.assertEqual((await repo.get_channel_post(news.id)).status, "pending")
            self.assertEqual((await repo.get_channel_post(digest.id)).status, "published")

        self.settings.CHANNEL_MIN_POST_INTERVAL_MINUTES = 0
        self.assertEqual(await self.publisher.publish_pending_queue(), 0)
        self.assertEqual(self.mock_bot.send_message.await_count, 1)

    async def test_safe_mode_does_not_automatically_publish_collections(self):
        self.settings.CHANNEL_AUTO_PUBLISH = False
        async with self.session_factory() as session:
            await Repository(session).create_channel_post(
                title="Weekly collection", content_hash="safe-collection",
                post_type="weekly_digest", event_type="weekly_digest",
                post_text="Premieres", status="pending",
            )
            await session.commit()
        self.assertEqual(await self.publisher.publish_pending_queue(), 0)
        self.mock_bot.send_message.assert_not_awaited()

    async def test_daily_digest_generation_and_skip(self):
        """Проверка дайджеста «Что выходит сегодня»: пропуск при отсутствии релизов и публикация при их наличии."""
        today = date(2027, 4, 17)

        # 1. База пуста -> дайджест пропускается
        digest_none = await self.publisher.create_daily_digest(target_date=today)
        self.assertIsNone(digest_none)

        # 2. Добавляем релизы на сегодня в БД
        async with self.session_factory() as session:
            repo = Repository(session)
            u = await repo.get_or_create_user(telegram_id=123, username="test", first_name="User")
            await repo.add_tracked_item(
                user_id=u.id,
                tmdb_id=101,
                media_type="movie",
                title="Новый Фильм",
                original_title=None,
                poster_path=None,
                last_known_season=None,
                last_known_air_date=None,
                next_air_date=today,
                tmdb_url="https://tmdb.org/movie/101",
            )
            await repo.add_tracked_item(
                user_id=u.id,
                tmdb_id=202,
                media_type="tv",
                title="Крутой Сериал",
                original_title=None,
                poster_path=None,
                last_known_season=1,
                last_known_air_date=None,
                next_air_date=today,
                tmdb_url="https://tmdb.org/tv/202",
            )
            # Укажем сезон 2
            item = (await repo.get_user_items(123))[1]
            item.next_season_number = 2
            await session.commit()

        # 3. Теперь дайджест успешно создаётся
        digest = await self.publisher.create_daily_digest(target_date=today)
        self.assertIsNotNone(digest)
        self.assertEqual(digest.event_type, "daily_digest")
        self.assertIn("Сегодня на экране", digest.post_text)
        self.assertIn("Новый Фильм", digest.post_text)
        self.assertIn("премьера фильма", digest.post_text)
        self.assertIn("Крутой Сериал", digest.post_text)
        self.assertIn("старт 2 сезона", digest.post_text)


    async def test_weekly_digest_generation_and_skip(self):
        """Проверка дайджеста «Главные премьеры недели»: пропуск при < 2 релизов и публикация при наличии."""
        start_date = date(2027, 4, 19)

        # 1. Менее 2 релизов -> пропуск
        digest_none = await self.publisher.create_weekly_digest(start_date=start_date)
        self.assertIsNone(digest_none)

        # 2. Добавляем 2 релиза на эту неделю
        async with self.session_factory() as session:
            repo = Repository(session)
            u = await repo.get_or_create_user(telegram_id=123, username="test", first_name="User")
            await repo.add_tracked_item(
                user_id=u.id,
                tmdb_id=301,
                media_type="movie",
                title="Премьера Понедельника",
                original_title=None,
                poster_path=None,
                last_known_season=None,
                last_known_air_date=None,
                next_air_date=start_date,
                tmdb_url="https://tmdb.org/movie/301",
            )
            await repo.add_tracked_item(
                user_id=u.id,
                tmdb_id=302,
                media_type="movie",
                title="Премьера Четверга",
                original_title=None,
                poster_path=None,
                last_known_season=None,
                last_known_air_date=None,
                next_air_date=start_date + timedelta(days=3),
                tmdb_url="https://tmdb.org/movie/302",
            )
            await session.commit()

        # 3. Еженедельный дайджест создаётся
        digest = await self.publisher.create_weekly_digest(start_date=start_date)
        self.assertIsNotNone(digest)
        self.assertEqual(digest.event_type, "weekly_digest")
        self.assertIn("Главные премьеры недели", digest.post_text)
        self.assertIn("Премьера Понедельника", digest.post_text)
        self.assertIn("Премьера Четверга", digest.post_text)


if __name__ == "__main__":
    unittest.main()
