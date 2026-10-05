import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from bot.config import Settings
from bot.scheduler.jobs import setup_scheduler


class SchedulerTests(unittest.TestCase):
    def test_digests_use_moscow_time(self):
        settings = Settings(TELEGRAM_BOT_TOKEN="test", TMDB_API_KEY="test")
        scheduler = setup_scheduler(Mock(), Mock(), Mock(), settings)
        # Monday, before both Moscow morning digests.
        now = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        daily = scheduler.get_job("channel_daily_digest").trigger.get_next_fire_time(None, now)
        weekly = scheduler.get_job("channel_weekly_digest").trigger.get_next_fire_time(None, now)
        self.assertEqual(daily.astimezone(timezone.utc), datetime(2026, 10, 5, 6, 30, tzinfo=timezone.utc))
        self.assertEqual(weekly.astimezone(timezone.utc), datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc))


class PersonalNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_tracking_updates_only_reach_their_subscribers(self):
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from bot.db.models import Base, ChannelPost, NotificationLog, TrackedItem
        from bot.db.repositories import Repository
        from bot.scheduler.jobs import check_updates_job

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            updates = []
            async with factory() as session:
                repo = Repository(session)
                for index, kind in enumerate(("announced", "released", "status_change")):
                    user = await repo.get_or_create_user(100 + index, None, "User")
                    item = await repo.add_tracked_item(
                        user_id=user.id, tmdb_id=200 + index,
                        media_type="movie" if kind == "released" else "tv",
                        title=f"Title {index}", original_title=None, poster_path=None,
                        last_known_season=1, last_known_air_date=None,
                        next_air_date=date(2027, 4, 17),
                        tmdb_url=f"https://www.themoviedb.org/tv/{200 + index}",
                    )
                    updates.append({"telegram_id": user.telegram_id, "item": item,
                                    "type": kind, "info": {"next_air_date": date(2027, 4, 17),
                                    "status": "Ended", "channel_event_type": "renewed"}})
                await session.commit()

            bot = Mock(send_message=AsyncMock())
            tmdb = Mock(get_official_trailer=AsyncMock())
            settings = Settings(TELEGRAM_BOT_TOKEN="test", TMDB_API_KEY="test",
                                TELEGRAM_CHANNEL_ID="@public", CHANNEL_POSTING_ENABLED=True,
                                CHANNEL_AUTO_PUBLISH=True)
            with patch("bot.scheduler.jobs.TrackerService") as tracker:
                tracker.return_value.check_all_updates = AsyncMock(return_value=updates)
                await check_updates_job(bot, factory, tmdb, settings)

            self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [100, 101, 102])
            tmdb.get_official_trailer.assert_not_awaited()
            async with factory() as session:
                self.assertEqual(list((await session.scalars(select(ChannelPost))).all()), [])
                logs = list((await session.scalars(select(NotificationLog))).all())
                self.assertEqual([log.notification_type for log in logs],
                                 ["announced", "released", "status_change"])
                repo = Repository(session)
                items = [await session.get(TrackedItem, update["item"].id) for update in updates]
                self.assertTrue(items[0].notified_announced)
                self.assertTrue(items[1].notified_released)
        finally:
            await engine.dispose()
