import unittest
from datetime import datetime, date, timezone
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from bot.config import Settings
from bot.db.models import Base, NotificationLog, TrackedItem
from bot.db.repositories import Repository
from bot.scheduler.jobs import check_episode_reminders_job, setup_scheduler
from bot.services.episode_reminders import episodes_on_date


class EpisodeReminderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.settings = Settings(TELEGRAM_BOT_TOKEN="test", TMDB_API_KEY="test")
        self.bot = Mock(send_message=AsyncMock())
        self.episode = {"season_number": 2, "episode_number": 4, "air_date": "2026-10-09"}
        self.tmdb = Mock(get_tv_details=AsyncMock(return_value={"next_episode_to_air": self.episode}),
                         get_tv_season=AsyncMock(return_value={"episodes": [self.episode]}))
        self.now = datetime(2026, 10, 8, 10)
        async with self.factory() as session:
            repo = Repository(session)
            for n, media in enumerate(("tv", "tv", "movie")):
                user = await repo.get_or_create_user(100 + n, None, "User")
                item = await repo.add_tracked_item(user.id, 247718, media, "Tom & Jerry", None, None,
                                                   2, None, None, "https://www.themoviedb.org/tv/247718")
                item.status = "Returning Series"
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def run_job(self):
        with patch("bot.scheduler.jobs.episode_reminder_now", return_value=self.now):
            await check_episode_reminders_job(self.bot, self.factory, self.tmdb, self.settings)

    async def test_subscribers_only_persistent_dedup_and_season_dates_unchanged(self):
        await self.run_job()
        await self.run_job()  # New DB session, same persisted notification history.
        self.assertEqual([c.args[0] for c in self.bot.send_message.await_args_list], [100, 101])
        self.assertEqual(self.tmdb.get_tv_details.await_count, 2)  # Once per title per cycle.
        text = self.bot.send_message.await_args_list[0].args[1]
        self.assertIn("Уже завтра выходит новая серия!", text)
        self.assertIn("2 сезон, 4 серия", text)
        self.assertIn("Tom &amp; Jerry", text)
        self.assertIn("09.10.2026", text)
        async with self.factory() as session:
            logs = list(await session.scalars(select(NotificationLog)))
            self.assertEqual(len(logs), 2)
            self.assertTrue(all(log.notification_type == "episode_tomorrow:2:4:2026-10-09" for log in logs))
            items = list(await session.scalars(select(TrackedItem)))
            self.assertTrue(all(i.next_air_date is None and not i.notified_reminder for i in items))

    async def test_failed_send_retries_without_resending_successes(self):
        self.bot.send_message.side_effect = [RuntimeError("Unavailable"), None]
        await self.run_job()
        self.bot.send_message.side_effect = None
        await self.run_job()
        self.assertEqual([c.args[0] for c in self.bot.send_message.await_args_list], [100, 101, 100])

    async def test_only_tomorrow_and_no_night_sends(self):
        self.now = datetime(2026, 10, 8, 23)
        await self.run_job()
        self.tmdb.get_tv_details.assert_not_awaited()
        self.now = datetime(2026, 10, 9, 10)
        await self.run_job()
        self.bot.send_message.assert_not_awaited()

    async def test_missing_or_invalid_dates_do_not_send(self):
        self.episode["air_date"] = "invalid"
        await self.run_job()
        self.bot.send_message.assert_not_awaited()

    async def test_multiple_episodes_and_daily_series_while_next_episode_is_today(self):
        self.tmdb.get_tv_details.return_value = {"next_episode_to_air":
            {"season_number": 2, "episode_number": 3, "air_date": "2026-10-08"}}
        other = {**self.episode, "episode_number": 5}
        self.tmdb.get_tv_season.return_value = {"episodes": [self.episode, other]}
        await self.run_job()
        await self.run_job()
        self.assertEqual(self.bot.send_message.await_count, 4)
        self.assertTrue(any("5 серия" in c.args[1] for c in self.bot.send_message.await_args_list))

    async def test_unknown_next_episode_uses_current_season(self):
        result = await episodes_on_date(self.tmdb, 247718,
            {"seasons": [{"season_number": 2, "air_date": "2026-09-18"}]}, date(2026, 10, 9))
        self.assertEqual(result, [self.episode])

    def test_schedule_uses_moscow_and_prevents_overlap(self):
        scheduler = setup_scheduler(self.bot, self.factory, self.tmdb, self.settings)
        job = scheduler.get_job("check_episode_reminders")
        fire = job.trigger.get_next_fire_time(None, datetime(2026, 10, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(fire.astimezone(timezone.utc), datetime(2026, 10, 8, 7, tzinfo=timezone.utc))
        self.assertEqual(job.max_instances, 1)
