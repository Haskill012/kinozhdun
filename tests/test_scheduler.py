import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

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
