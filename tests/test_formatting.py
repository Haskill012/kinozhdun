"""Тесты шаблонов форматирования и экранирования сообщений КиноЖдуна."""

import datetime
import unittest
from unittest.mock import MagicMock

from bot.keyboards.inline import notification_item_keyboard
from bot.utils.formatting import (
    format_announced_notification,
    format_date_ru,
    format_item_details,
    format_released_notification,
    format_reminder_notification,
    format_status_change_notification,
    format_status_emoji,
    safe_html,
)


class TestFormattingTemplates(unittest.TestCase):
    """Тестирование эстетики, безопасности HTML и локализации всех шаблонов."""

    def test_safe_html_escaping(self):
        """Проверка безопасного экранирования амперсандов, скобок и спецсимволов."""
        self.assertEqual(safe_html("Tom & Jerry"), "Tom &amp; Jerry")
        self.assertEqual(safe_html("<script>alert('xss')</script>"), "&lt;script&gt;alert('xss')&lt;/script&gt;")
        self.assertEqual(safe_html(None), "")
        self.assertEqual(safe_html("Fast & Furious 10"), "Fast &amp; Furious 10")

    def test_status_emoji_russian_localization(self):
        """Проверка русского перевода всех статусов TMDB."""
        self.assertIn("Завершён", format_status_emoji("Ended"))
        self.assertIn("Продлён на новый сезон", format_status_emoji("Returning Series"))
        self.assertIn("Закрыт", format_status_emoji("Canceled"))
        self.assertIn("Премьера состоялась", format_status_emoji("Released"))
        self.assertIn("В производстве", format_status_emoji("In Production"))
        self.assertIn("Пост-продакшн", format_status_emoji("Post Production"))

    def test_format_status_change_notification_ended(self):
        """Проверка уведомления об окончании сериала (например, Медведь)."""
        item = MagicMock(title="Медведь", media_type="tv", network="FX", tmdb_url="https://www.themoviedb.org/tv/136315")
        text = format_status_change_notification(item, {"status": "Ended"})

        self.assertIn("Статус сериала изменился", text)
        self.assertIn("«Медведь»", text)
        self.assertIn("FX", text)
        self.assertIn("Завершён", text)
        # Не должно быть сырых англоязычных статусов, дефисных разделителей и ссылок в тексте
        self.assertNotIn("Ended", text)
        self.assertNotIn("────────────────────────", text)
        self.assertNotIn("<a href=", text)

    def test_format_status_change_notification_returning(self):
        """Проверка уведомления о продлении сериала на новый сезон."""
        item = MagicMock(title="Дом Дракона", media_type="tv", network="HBO", tmdb_url="https://www.themoviedb.org/tv/94997")
        text = format_status_change_notification(item, {"status": "Returning Series"})

        self.assertIn("«Дом Дракона»", text)
        self.assertIn("Продлён", text)
        self.assertNotIn("Returning Series", text)

    def test_format_announced_notification(self):
        """Проверка уведомления об анонсе даты выхода."""
        item = MagicMock(title="Фоллаут", media_type="tv", network="Prime Video", tmdb_url="https://www.themoviedb.org/tv/82856")
        update = {"next_season": 2, "next_air_date": datetime.date(2027, 4, 17)}
        text = format_announced_notification(item, update)

        self.assertIn("Объявлена дата премьеры", text)
        self.assertIn("«Фоллаут»", text)
        self.assertIn("2 сезон", text)
        self.assertIn("17.04.2027", text)
        self.assertNotIn("────────────────────────", text)
        self.assertNotIn("<a href=", text)

    def test_format_released_notification(self):
        """Проверка уведомления о состоявшейся премьере."""
        item = MagicMock(title="Дюна: Часть третья", media_type="movie", network="Warner Bros.", next_season_number=None, last_known_season=None, next_air_date=datetime.date(2027, 10, 15))
        text = format_released_notification(item)

        self.assertIn("Премьера состоялась", text)
        self.assertIn("«Дюна: Часть третья»", text)
        self.assertIn("15.10.2027", text)
        self.assertNotIn("────────────────────────", text)

    def test_format_reminder_notification(self):
        """Проверка уведомления-напоминания за 3 дня."""
        item = MagicMock(title="Очень странные дела", media_type="tv", network="Netflix", next_season_number=5, next_air_date=datetime.date(2026, 11, 20), custom_date=None)
        text = format_reminder_notification(item, days_left=3)

        self.assertIn("осталось 3 дня", text)
        self.assertIn("«Очень странные дела»", text)
        self.assertIn("(сезон 5)", text)
        self.assertIn("20.11.2026", text)
        self.assertNotIn("────────────────────────", text)

    def test_notification_item_keyboard(self):
        """Проверка генерации инлайн-клавиатуры для уведомлений."""
        kb = notification_item_keyboard(item_id=42, tmdb_url="https://www.themoviedb.org/tv/136315")
        buttons = [b for row in kb.inline_keyboard for b in row]

        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0].text, "🍿 Открыть в Кинождуне")
        self.assertEqual(buttons[0].callback_data, "info:42")
        self.assertEqual(buttons[1].text, "🌐 Страница на TMDB")
        self.assertEqual(buttons[1].url, "https://www.themoviedb.org/tv/136315")


if __name__ == "__main__":
    unittest.main()
