"""
Тесты сервиса автоматической генерации и публикации шортсов для КиноЖдуна.
"""

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bot.config import Settings
from bot.db.models import ChannelPost
from bot.services.shorts_publisher import ShortsPublisher, format_ass_time


class TestShortsPublisher(unittest.IsolatedAsyncioTestCase):
    """Проверка определения премьерных событий, оверлея и каналов дистрибуции."""

    def setUp(self):
        self.settings = Settings(
            TELEGRAM_BOT_TOKEN="mock_token",
            TMDB_API_KEY="mock_key",
            BOT_USERNAME="kinojdun_bot",
            TELEGRAM_CHANNEL_ID="@kinojdun_test_channel",
            CHANNEL_POSTING_ENABLED=True,
            VK_ACCESS_TOKEN="mock_vk_token",
            VK_GROUP_ID=242059739,
            MAX_BOT_TOKEN="mock_max_token",
            MAX_CHANNEL_ID=-79850172292508,
            MAX_CHANNEL_POSTING_ENABLED=True,
        )
        self.mock_bot = MagicMock()
        self.mock_bot.send_video = AsyncMock(return_value=MagicMock(message_id=999))
        self.publisher = ShortsPublisher(self.settings, self.mock_bot)

    def test_is_premiere_event_detection(self):
        """Проверяет распознавание премьер фильмов, сериалов и новых сезонов."""
        # 1. Фильм - премьера
        movie_post = ChannelPost(
            id=1, media_type="movie", event_type="announced",
            title="Тестовый Фильм", air_date=date(2026, 10, 15), content_hash="hash1"
        )
        self.assertTrue(self.publisher.is_premiere_event(movie_post))

        # 2. Сериал - премьера 1 сезона
        series_p1 = ChannelPost(
            id=2, media_type="tv", event_type="date_announced", season_number=1,
            title="Тестовый Сериал", air_date=date(2026, 10, 20), content_hash="hash2"
        )
        self.assertTrue(self.publisher.is_premiere_event(series_p1))

        # 3. Сериал - новый сезон (2 сезон)
        series_s2 = ChannelPost(
            id=3, media_type="tv", event_type="season_announced", season_number=2,
            title="Тестовый Сериал 2", air_date=date(2026, 11, 1), content_hash="hash3"
        )
        self.assertTrue(self.publisher.is_premiere_event(series_s2))

        # 4. Дайджест - не должен создавать шортс
        digest_post = ChannelPost(
            id=4, post_type="daily_digest", event_type="daily_digest",
            title="Дайджест", content_hash="hash4"
        )
        self.assertFalse(self.publisher.is_premiere_event(digest_post))

        # 5. Отменённый сериал - не создает шортс
        canceled_post = ChannelPost(
            id=5, media_type="tv", event_type="canceled",
            title="Отменённый проект", content_hash="hash5"
        )
        self.assertFalse(self.publisher.is_premiere_event(canceled_post))

    def test_ass_time_formatting(self):
        """Проверка форматирования таймкодов субтитров ASS."""
        self.assertEqual(format_ass_time(0.0), "0:00:00.00")
        self.assertEqual(format_ass_time(25.5), "0:00:25.50")
        self.assertEqual(format_ass_time(65.12), "0:01:05.12")

    def test_render_overlay_creates_valid_image(self):
        """Проверяет создание оверлея без надписи хронометража."""
        test_out = Path("test_overlay_tmp.png")
        try:
            self.publisher.render_overlay(
                badge="🍿 КИНОЖДУН | ПРЕМЬЕРА",
                hook="ТЕСТОВЫЙ ХУК ДЛЯ ШОРТСА",
                title="ТЕСТОВЫЙ ФИЛЬМ (2026)",
                meta="NETFLIX • ПРЕМЬЕРА 15 ОКТЯБРЯ",
                source="Промо-материалы",
                out_path=test_out
            )
            self.assertTrue(test_out.exists())
            self.assertGreater(test_out.stat().st_size, 1000)
        finally:
            if test_out.exists():
                test_out.unlink()

    async def test_publish_to_telegram_sends_video(self):
        """Проверяет отправку нативного видео в Telegram."""
        dummy_video = Path("dummy_video.mp4")
        dummy_video.write_bytes(b"0" * 100)
        try:
            mid = await self.publisher.publish_to_telegram(
                chat_id="@kinojdun_test_channel",
                video_path=dummy_video,
                post_text="<b>Текст премьеры</b>"
            )
            self.assertEqual(mid, 999)
            self.mock_bot.send_video.assert_awaited_once()
            args, kwargs = self.mock_bot.send_video.call_args
            self.assertEqual(kwargs["chat_id"], "@kinojdun_test_channel")
            self.assertTrue(kwargs["supports_streaming"])
        finally:
            if dummy_video.exists():
                dummy_video.unlink()


if __name__ == "__main__":
    unittest.main()
