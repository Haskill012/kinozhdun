"""Тесты выпадающего меню выбора бота (Telegram / Макс) на сайте."""

import tempfile
import unittest
from pathlib import Path

from tests.test_website import config
from website.catalog_views import project_page, spotlight_slide, streaming_home
from website.content import Store
from website.views import bot_banner, bot_dropdown, max_title_link, premiere_rows, title_link


class BotDropdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.store = Store(self.db_path)
        self.cfg = config(self.db_path)
        self.item_movie = {
            "id": 157336,
            "media_type": "movie",
            "title": "Интерстеллар",
            "release_date": "2026-11-05",
            "overview": "Фильм про космос",
            "key": "movie:157336",
        }

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_max_title_link_generation(self):
        """Проверка формирования deep link ссылки для бота в Макс."""
        url = max_title_link(self.item_movie, self.cfg)
        self.assertEqual(url, "https://max.ru/id5001170357_1_bot?start=c_movie_157336")

    def test_bot_dropdown_html_structure(self):
        """Проверка структуры и элементов HTML-разметки bot_dropdown."""
        tg = title_link(self.item_movie, self.cfg)
        max_bot = max_title_link(self.item_movie, self.cfg)
        html = bot_dropdown("+ Ждать", tg, max_bot, btn_class="button", wrapper_class="test-dropdown")

        self.assertIn('class="bot-dropdown test-dropdown"', html)
        self.assertIn('class="button bot-dropdown-trigger"', html)
        self.assertIn('href="https://t.me/kinojdun_bot?start=c_movie_157336"', html)
        self.assertIn('class="bot-dropdown-caret"', html)
        self.assertIn('class="bot-dropdown-menu"', html)
        self.assertIn('<button type="button"', html)
        self.assertNotIn('role="menu"', html)
        self.assertIn('class="bot-dropdown-item bot-dropdown-tg"', html)
        self.assertIn('Telegram', html)
        self.assertIn('class="bot-dropdown-item bot-dropdown-max"', html)
        self.assertIn('https://max.ru/id5001170357_1_bot?start=c_movie_157336', html)
        self.assertIn('Макс', html)

    def test_premiere_rows_renders_dropdown(self):
        """В строках премьер кнопка 'Ждать' оформлена как выпадающий список."""
        rows_html = premiere_rows([self.item_movie], self.cfg, limit=1)
        self.assertIn('class="bot-dropdown premiere-bot-dropdown"', rows_html)
        self.assertIn('class="reminder bot-dropdown-trigger"', rows_html)
        self.assertIn('https://t.me/kinojdun_bot?start=c_movie_157336', rows_html)
        self.assertIn('https://max.ru/id5001170357_1_bot?start=c_movie_157336', rows_html)
        self.assertIn('Telegram', rows_html)
        self.assertIn('Макс', rows_html)

    def test_spotlight_slide_renders_dropdown(self):
        """В слайдере главной страницы кнопка действия содержит выбор бота."""
        slide_html = spotlight_slide(self.item_movie, self.cfg, 0)
        self.assertIn('class="bot-dropdown spotlight-bot-dropdown"', slide_html)
        self.assertIn('https://t.me/kinojdun_bot?start=c_movie_157336', slide_html)
        self.assertIn('https://max.ru/id5001170357_1_bot?start=c_movie_157336', slide_html)
        self.assertIn('Telegram', slide_html)
        self.assertIn('Макс', slide_html)

    def test_project_page_renders_dropdown(self):
        """На странице проекта кнопка отслеживания оформлена как выпадающий список."""
        self.store.save_title(self.item_movie["key"], self.item_movie)
        page_html = project_page(self.store, self.cfg, self.item_movie)
        self.assertIn('class="bot-dropdown project-hero-dropdown"', page_html)
        self.assertIn('https://t.me/kinojdun_bot?start=c_movie_157336', page_html)
        self.assertIn('https://max.ru/id5001170357_1_bot?start=c_movie_157336', page_html)
        self.assertIn('Telegram', page_html)
        self.assertIn('Макс', page_html)

    def test_bot_banner_renders_dropdown(self):
        """Баннер бота на сайте содержит выбор между Telegram и Макс."""
        banner_html = bot_banner(self.cfg)
        self.assertIn('class="bot-dropdown banner-bot-dropdown"', banner_html)
        self.assertIn('https://max.ru/id5001170357_1_bot', banner_html)
        self.assertIn('Telegram', banner_html)
        self.assertIn('Макс', banner_html)

    def test_streaming_home_renders_dropdowns(self):
        """На главной странице хедер и баннеры содержат выбор между Telegram и Макс."""
        self.store.seed_catalog(self.cfg['bot_url'])
        home_html = streaming_home(self.store, self.cfg)
        self.assertIn('class="bot-dropdown header-bot-dropdown"', home_html)
        self.assertIn('class="bot-dropdown discovery-bot-dropdown"', home_html)
        self.assertIn('https://max.ru/id5001170357_1_bot', home_html)
        self.assertIn('Telegram', home_html)
        self.assertIn('Макс', home_html)


if __name__ == "__main__":
    unittest.main()
