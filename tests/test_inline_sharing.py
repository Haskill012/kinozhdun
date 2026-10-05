"""Тесты инлайн-режима шеринга карточек фильмов, списков и клавиатур."""

import unittest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

from bot.keyboards.inline import (
    preview_item_keyboard,
    track_success_keyboard,
    item_details_keyboard,
    shared_watchlist_created_keyboard,
    generate_share_url,
)
from bot.handlers.inline import process_inline_query


class TestInlineKeyboards(unittest.TestCase):
    """Проверка правильной настройки кнопок шеринга через switch_inline_query."""

    def test_track_success_keyboard_uses_inline_switch(self):
        """Кнопка шеринга после добавления тайтла должна использовать switch_inline_query."""
        kb = track_success_keyboard("movie", 1170608, "Дюна: Часть третья", referrer_id=330413281)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        share_btn = next((b for b in buttons if "Поделиться" in b.text), None)

        self.assertIsNotNone(share_btn)
        self.assertEqual(share_btn.switch_inline_query, "share_movie_1170608_u330413281")
        self.assertIsNone(share_btn.url)

    def test_preview_item_keyboard_uses_inline_switch(self):
        """Кнопка 'Поделиться с другом' из предпросмотра должна открывать инлайн-шеринг."""
        kb = preview_item_keyboard(
            media_type="tv",
            tmdb_id=82856,
            is_already_tracked=True,
            title="Фоллаут",
            referrer_id=12345,
        )
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        share_btn = next((b for b in buttons if "Поделиться" in b.text), None)

        self.assertIsNotNone(share_btn)
        self.assertEqual(share_btn.switch_inline_query, "share_tv_82856_u12345")

    def test_item_details_keyboard_uses_inline_switch(self):
        """Кнопка шеринга из карточки отслеживаемого тайтла должна использовать switch_inline_query."""
        item = SimpleNamespace(id=1, tmdb_id=1170608, media_type="movie", title="Дюна 3", tmdb_url=None)
        kb = item_details_keyboard(item, referrer_id=98765)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        share_btn = next((b for b in buttons if "Поделиться" in b.text), None)

        self.assertIsNotNone(share_btn)
        self.assertEqual(share_btn.switch_inline_query, "share_movie_1170608_u98765")

    def test_shared_watchlist_keyboard_uses_inline_switch(self):
        """Кнопка шеринга списка ожидания должна использовать switch_inline_query=list_token."""
        kb = shared_watchlist_created_keyboard("token_abc_123", "kinojdun_bot", ["Фильм 1", "Сериал 2"])
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        share_btn = next((b for b in buttons if "Отправить друзьям" in b.text), None)

        self.assertIsNotNone(share_btn)
        self.assertEqual(share_btn.switch_inline_query, "list_token_abc_123")

    def test_generate_share_url_puts_text_before_link(self):
        """Резервный метод генерации ссылки t.me/share/url должен ставить текст перед ссылкой."""
        url = generate_share_url("https://t.me/kinojdun_bot?start=c_movie_1", "🍿 Жду фильм!")
        self.assertIn("https%3A//t.me/kinojdun_bot", url)
        # В URL параметр url содержит весь текст с ссылкой в конце
        self.assertTrue(url.startswith("https://t.me/share/url?url="))


class TestInlineQueryHandler(unittest.IsolatedAsyncioTestCase):
    """Проверка формирования инлайн-карточек ботом."""

    async def test_inline_query_movie_share(self):
        """Инлайн-запрос share_movie_... должен возвращать карточку с постером и кнопкой отслеживания."""
        mock_tmdb = AsyncMock()
        mock_tmdb.get_movie_details.return_value = {
            "id": 1170608,
            "title": "Дюна: Часть третья",
            "overview": "Продолжение саги Дени Вильнёва.",
            "poster_path": "/dune3.jpg",
            "release_date": "2026-12-18",
            "network": "Warner Bros.",
        }

        mock_bot = MagicMock()
        mock_bot.__getitem__.side_effect = lambda k: {
            "session_factory": MagicMock(),
            "tmdb_client": mock_tmdb,
            "settings": SimpleNamespace(BOT_USERNAME="kinojdun_bot"),
        }[k]

        mock_user = SimpleNamespace(id=330413281, username="test_user")
        mock_query = AsyncMock()
        mock_query.query = "share_movie_1170608_u330413281"
        mock_query.from_user = mock_user
        mock_query.bot = mock_bot

        await process_inline_query(mock_query)

        mock_query.answer.assert_called_once()
        args, kwargs = mock_query.answer.call_args
        results = args[0]
        self.assertGreaterEqual(len(results), 1)

        # Первый результат — фотокарточка
        photo_res = results[0]
        self.assertEqual(photo_res.id, "p_movie_1170608")
        self.assertIn("https://image.tmdb.org/t/p/w780/dune3.jpg", photo_res.photo_url)
        self.assertIn("Дюна: Часть третья", photo_res.caption)
        self.assertIn("18.12.2026", photo_res.caption)

        # Кнопка под карточкой
        kb = photo_res.reply_markup
        btn = kb.inline_keyboard[0][0]
        self.assertIn("Отслеживать «Дюна: Часть третья»", btn.text)
        self.assertIn("c_movie_1170608_u330413281", btn.url)

    async def test_inline_query_empty_hint(self):
        """При пустом инлайн-запросе бот возвращает подсказку по поиску."""
        mock_bot = MagicMock()
        mock_bot.__getitem__.side_effect = lambda k: {
            "session_factory": MagicMock(),
            "tmdb_client": AsyncMock(),
            "settings": SimpleNamespace(BOT_USERNAME="kinojdun_bot"),
        }[k]

        mock_query = AsyncMock()
        mock_query.query = ""
        mock_query.from_user = SimpleNamespace(id=1, username="user")
        mock_query.bot = mock_bot

        await process_inline_query(mock_query)

        mock_query.answer.assert_called_once()
        args, _ = mock_query.answer.call_args
        results = args[0]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, "hint")


if __name__ == "__main__":
    unittest.main()
