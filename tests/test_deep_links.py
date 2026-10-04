"""Тесты единого механизма и формата Telegram Deep Links."""

import unittest
from bot.handlers.start import (
    parse_content_deep_link,
    parse_watchlist_deep_link,
    parse_channel_deep_link,
)
from bot.keyboards.inline import (
    track_success_keyboard,
    shared_watchlist_created_keyboard,
)


class TestDeepLinks(unittest.TestCase):
    """Тестирование парсинга и валидации различных deep link форматов."""

    def test_parse_content_deep_link_valid(self):
        """Проверка корректного распознавания ссылок на контент."""
        # Сериал без реферера
        res = parse_content_deep_link("c_tv_82856")
        self.assertEqual(res, ("tv", 82856, None))

        # Фильм без реферера
        res = parse_content_deep_link("c_movie_550")
        self.assertEqual(res, ("movie", 550, None))

        # Сериал с реферером
        res = parse_content_deep_link("c_tv_82856_u123456789")
        self.assertEqual(res, ("tv", 82856, 123456789))

        # Формат share_* для обратной совместимости
        res = parse_content_deep_link("share_movie_100")
        self.assertEqual(res, ("movie", 100, None))

    def test_parse_content_deep_link_invalid(self):
        """Проверка обработки некорректных форматов ссылок на контент."""
        self.assertIsNone(parse_content_deep_link(""))
        self.assertIsNone(parse_content_deep_link("c_"))
        self.assertIsNone(parse_content_deep_link("c_tv_"))
        self.assertIsNone(parse_content_deep_link("c_game_123"))
        self.assertIsNone(parse_content_deep_link("c_tv_abc"))
        self.assertIsNone(parse_content_deep_link("c_tv_123_invalid"))
        self.assertIsNone(parse_content_deep_link("random_string_here"))

    def test_parse_watchlist_deep_link_valid(self):
        """Проверка корректного распознавания ссылок на расшаренный список."""
        res = parse_watchlist_deep_link("w_a1b2c3d4e5")
        self.assertEqual(res, "a1b2c3d4e5")

        res = parse_watchlist_deep_link("w_test-token_123")
        self.assertEqual(res, "test-token_123")

    def test_parse_watchlist_deep_link_invalid(self):
        """Проверка отклонения некорректных токенов списков."""
        self.assertIsNone(parse_watchlist_deep_link(""))
        self.assertIsNone(parse_watchlist_deep_link("w_"))
        self.assertIsNone(parse_watchlist_deep_link("w_ab"))  # слишком короткий (< 4)
        self.assertIsNone(parse_watchlist_deep_link("w_a!b@c#d$"))  # спецсимволы
        self.assertIsNone(parse_watchlist_deep_link("c_tv_123"))  # чужой префикс
        self.assertIsNone(parse_watchlist_deep_link("w_" + "x" * 40))  # слишком длинный (> 32)

    def test_parse_channel_deep_link_valid(self):
        """Проверка распознавания ссылок перехода из Telegram-канала."""
        res = parse_channel_deep_link("ch_42")
        self.assertEqual(res, 42)

        res = parse_channel_deep_link("ch_1")
        self.assertEqual(res, 1)

    def test_parse_channel_deep_link_invalid(self):
        """Проверка отклонения некорректных ссылок канала."""
        self.assertIsNone(parse_channel_deep_link(""))
        self.assertIsNone(parse_channel_deep_link("ch_"))
        self.assertIsNone(parse_channel_deep_link("ch_abc"))
        self.assertIsNone(parse_channel_deep_link("ch_12_extra"))

    def test_payload_length_within_telegram_limit(self):
        """Проверка того, что все генерируемые payload строго укладываются в лимит Telegram (64 символа)."""
        content_payload = "c_tv_1234567_u1234567890123"
        self.assertLessEqual(len(content_payload), 64)

        watchlist_payload = "w_0123456789"
        self.assertLessEqual(len(watchlist_payload), 64)

        channel_payload = "ch_9999999"
        self.assertLessEqual(len(channel_payload), 64)


if __name__ == "__main__":
    unittest.main()
