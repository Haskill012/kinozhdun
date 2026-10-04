"""Тесты минимальной аналитики воронок органического роста."""

import json
import unittest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.db.models import Base, AnalyticsEvent
from bot.services.analytics import AnalyticsService


class TestAnalytics(unittest.IsolatedAsyncioTestCase):
    """Тестирование логирования всех 9 событий роста."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.analytics = AnalyticsService(self.session_factory)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_all_nine_growth_events(self):
        """Проверка фиксации каждого из 9 требуемых событий в БД."""
        user_id = 999111

        # 1. content_shared
        await self.analytics.log_content_shared(user_id, "tv", 82856, "Фоллаут")

        # 2. share_link_opened
        await self.analytics.log_share_link_opened(user_id, "tv", 82856, referrer_id=123)

        # 3. content_followed_from_share
        await self.analytics.log_content_followed_from_share(user_id, "tv", 82856, referrer_id=123)

        # 4. watchlist_shared
        await self.analytics.log_watchlist_shared(user_id, "token123", 5)

        # 5. watchlist_link_opened
        await self.analytics.log_watchlist_link_opened(user_id, "token123")

        # 6. watchlist_item_followed
        await self.analytics.log_watchlist_item_followed(user_id, "token123", "tv", 82856)

        # 7. watchlist_follow_all
        await self.analytics.log_watchlist_follow_all(user_id, "token123", items_added=4)

        # 8. channel_link_opened
        await self.analytics.log_channel_link_opened(user_id, post_id=15, tmdb_id=82856)

        # 9. content_followed_from_channel
        await self.analytics.log_content_followed_from_channel(user_id, post_id=15, media_type="tv", tmdb_id=82856)

        # Проверяем записи в БД
        async with self.session_factory() as session:
            stmt = select(AnalyticsEvent).order_by(AnalyticsEvent.id)
            result = await session.execute(stmt)
            events = list(result.scalars().all())

            self.assertEqual(len(events), 9)

            event_names = [e.event_name for e in events]
            expected_names = [
                "content_shared",
                "share_link_opened",
                "content_followed_from_share",
                "watchlist_shared",
                "watchlist_link_opened",
                "watchlist_item_followed",
                "watchlist_follow_all",
                "channel_link_opened",
                "content_followed_from_channel",
            ]
            self.assertEqual(event_names, expected_names)

            # Проверяем детализированный payload
            shared_event = events[0]
            self.assertEqual(shared_event.source, "share_content")
            self.assertEqual(shared_event.reference_id, "tv:82856")
            p = json.loads(shared_event.payload)
            self.assertEqual(p["title"], "Фоллаут")

    async def test_channel_funnel_analytics_summary(self):
        """Проверка расчёта метрик и конверсии воронки канала."""
        # 1. Записываем переходы и добавления
        await self.analytics.log_channel_link_opened(telegram_id=1, post_id=10, tmdb_id=82856)
        await self.analytics.log_channel_link_opened(telegram_id=2, post_id=10, tmdb_id=82856)
        await self.analytics.log_channel_link_opened(telegram_id=2, post_id=10, tmdb_id=82856)  # повторный переход того же юзера
        await self.analytics.log_content_followed_from_channel(telegram_id=1, post_id=10, media_type="tv", tmdb_id=82856)

        async with self.session_factory() as session:
            from bot.db.repositories import Repository
            repo = Repository(session)
            await repo.create_channel_post(
                tmdb_id=82856,
                media_type="tv",
                title="Фоллаут",
                content_hash="post_hash_1",
                event_type="date_announced",
                status="published",
            )
            await session.commit()

            summary = await repo.get_channel_analytics_summary()
            self.assertEqual(summary["posts_count"], 1)
            self.assertEqual(summary["opens_count"], 3)
            self.assertEqual(summary["unique_users"], 2)
            self.assertEqual(summary["follows_count"], 1)
            self.assertAlmostEqual(summary["conversion_rate"], 33.3, places=1)


if __name__ == "__main__":
    unittest.main()

