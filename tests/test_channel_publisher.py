"""Тесты автоматического Telegram-канала «Кинождун»: фильтрация, дедупликация и deep links."""

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.config import Settings
from bot.db.models import Base
from bot.db.repositories import Repository
from bot.services.channel import (
    ChannelPublisher,
    generate_content_hash,
    channel_post_keyboard,
    format_channel_post_text,
)


class TestChannelPublisher(unittest.IsolatedAsyncioTestCase):
    """Тестирование логики публикации, дедупликации и фильтрации новостей."""

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

    def test_significance_filter(self):
        """Проверка критериев существенности новости для канала."""
        # Анонс с датой -> существенная
        self.assertTrue(self.publisher.is_significant_news("announced", date(2027, 5, 20)))

        # Анонс без даты -> не для публичного канала
        self.assertFalse(self.publisher.is_significant_news("announced", None))

        # Премьера тайтла -> существенная
        self.assertTrue(self.publisher.is_significant_news("released", None))

        # Продление или отмена сериала -> существенная
        self.assertTrue(self.publisher.is_significant_news("status_change", None, status="Returning Series"))
        self.assertTrue(self.publisher.is_significant_news("status_change", None, status="Canceled"))

        # Незначительное изменение статуса -> игнорируется
        self.assertFalse(self.publisher.is_significant_news("status_change", None, status="Rumored"))

    async def test_deduplication_prevents_duplicate_posts(self):
        """Проверка защиты от повторной публикации одной и той же новости."""
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
        # Бот НЕ должен отправлять повторное сообщение в канал!
        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        self.assertEqual(post1.id, post2.id)

    async def test_anti_spam_rate_limiting(self):
        """Проверка антиспам-интервала: второй пост откладывается в очередь pending."""
        # Первый пост публикуется сразу
        post1 = await self.publisher.process_update_for_channel(
            tmdb_id=1,
            media_type="movie",
            event_type="announced",
            title="Фильм 1",
            air_date=date(2026, 12, 1),
        )
        self.assertIsNotNone(post1)

        # Выключаем автопостинг без очереди, чтобы проверить поведение очереди
        self.settings.CHANNEL_AUTO_PUBLISH = False

        # Второй пост через 1 минуту (меньше 15 минут)
        post2 = await self.publisher.process_update_for_channel(
            tmdb_id=2,
            media_type="movie",
            event_type="announced",
            title="Фильм 2",
            air_date=date(2026, 12, 15),
        )
        self.assertIsNotNone(post2)
        self.assertEqual(post2.status, "pending")

    def test_channel_keyboard_deep_link(self):
        """Проверка формирования инлайн-кнопки с deep link обратно в бота."""
        kb = channel_post_keyboard(post_id=42, bot_username="kinojdun_bot", title="Фоллаут")
        button = kb.inline_keyboard[0][0]
        self.assertIn("🔔 Отслеживать «Фоллаут»", button.text)
        self.assertEqual(button.url, "https://t.me/kinojdun_bot?start=ch_42")


if __name__ == "__main__":
    unittest.main()
