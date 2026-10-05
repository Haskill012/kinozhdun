import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree

from aiohttp.test_utils import AioHTTPTestCase

from website.content import Store, slugify
from website.editor import Editor, today
from website.__main__ import create_app


def config(path):
    return {"database": str(path), "bot_database": None, "bot_url": "https://t.me/kinojdun_bot",
            "channel_url": "https://t.me/kinojdun_channel", "base_url": "http://127.0.0.1:8099",
            "public": False, "api_key": "", "api_base": "https://api.themoviedb.org/3",
            "sync_seconds": 3600, "batch_size": 2,
            "yandex_verification": "", "google_verification": "", "yandex_metrika_id": ""}


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "site.db")
        self.editor = Editor(self.store, config(Path(self.tmp.name) / "site.db"))
        self.release = (today() + timedelta(days=5)).isoformat()
        self.movie = {"id": 123, "title": "Тестовый фильм", "release_date": self.release, "status": "In Production", "overview": "Описание"}

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_slugify_transliteration(self):
        self.assertEqual(slugify("«Фоллаут»: дата выхода — 15.11.2026"), "follaut-data-vyhoda-15-11-2026")
        self.assertEqual(slugify("Очень странные дела 5"), "ochen-strannye-dela-5")
        self.assertEqual(slugify("Dune: Part Two"), "dune-part-two")

    def test_restart_does_not_duplicate_posts(self):
        self.editor.process("movie", self.movie)
        self.store.db.close()
        self.store = Store(Path(self.tmp.name) / "site.db")
        self.editor = Editor(self.store, config(Path(self.tmp.name) / "site.db"))
        self.editor.process("movie", self.movie)
        self.assertEqual(len(self.store.articles()), 1)

    def test_changed_date_publishes_old_and_new_dates(self):
        self.editor.process("movie", self.movie)
        changed = {**self.movie, "release_date": (today() + timedelta(days=20)).isoformat()}
        self.editor.process("movie", changed)
        self.assertEqual(len(self.store.articles()), 2)
        changed_article = next(a for a in self.store.articles() if "изменилась" in a["title"])
        self.assertIn("Ранее", changed_article["body"])
        self.assertEqual(self.store.snapshot("movie:123")["release_date"], changed["release_date"])

    def test_series_first_air_date_is_not_a_new_season_date(self):
        tv = {"id": 8, "name": "Сериал", "first_air_date": "2010-01-01", "status": "Returning Series"}
        self.editor.process("tv", tv)
        self.assertEqual(len(self.store.articles()), 0)
        tv["next_episode_to_air"] = {"air_date": self.release, "season_number": 4, "episode_number": 3}
        self.editor.process("tv", tv)
        self.assertIn("3-м эпизоде 4-го сезона", self.store.articles()[0]["summary"])

    def test_no_dates_or_adult_content_do_not_generate_release_news(self):
        for detail in ({**self.movie, "release_date": "invalid"}, {**self.movie, "adult": True}):
            self.editor.process("movie", detail)
        self.assertEqual(len(self.store.articles()), 0)

    def test_only_new_official_trailers_publish(self):
        detail = copy.deepcopy(self.movie)
        self.editor.process("movie", detail)
        detail["videos"] = {"results": [{"official": False, "type": "Trailer", "site": "YouTube", "key": "abcdefghijk"}]}
        self.editor.process("movie", detail)
        self.assertEqual(len(self.store.articles()), 1)
        detail["videos"]["results"][0]["official"] = True
        self.editor.process("movie", detail)
        self.editor.process("movie", detail)
        self.assertEqual(len(self.store.articles()), 2)

    def test_rollover_episode_keeps_today_release_event(self):
        self.store.save_title("tv:9", {"release_date": today().isoformat(), "media_type": "tv", "id": 9})
        self.editor.process("tv", {"id": 9, "name": "Сериал", "first_air_date": "2010-01-01"})
        self.assertTrue(any("сегодня" in a["title"] for a in self.store.articles()))

    def test_channel_import_filters_moderation_and_bad_digest(self):
        path = Path(self.tmp.name) / "bot.db"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE channel_posts (title, post_text, status, credibility, is_sponsored, content_hash, event_type, published_at)")
            for status, credibility, sponsored, key in (("published", "confirmed", 0, "ok"), ("pending", "confirmed", 0, "pending"), ("published", "rumor", 0, "rumor"), ("published", "confirmed", 1, "ad")):
                db.execute("INSERT INTO channel_posts VALUES (?,?,?,?,?,?,?,?)", ("Заголовок", "<b>Текст новости</b>", status, credibility, sponsored, key, "news", "2026-10-04 10:00:00"))
            db.execute("INSERT INTO channel_posts VALUES (?,?,?,?,?,?,?,?)", ("Неделя", "04.10.2026 – 10.10.2026\n01.09.2026 — Старый фильм", "published", "confirmed", 0, "bad", "weekly_digest", "2026-10-04 10:00:00"))
            db.commit()
        self.assertEqual(self.store.import_channel(path, "https://t.me/channel"), 1)
        self.assertEqual(self.store.import_channel(path, "https://t.me/channel"), 0)
        self.assertEqual(len(self.store.articles()), 1)
        self.assertNotIn("<b>", self.store.articles()[0]["body"])
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM channel_posts").fetchone()[0], 5)


class WebsiteHTTPTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(Path(self.tmp.name) / "site.db")
        return create_app(self.cfg)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_all_routes_and_feeds(self):
        for path in ("/", "/news", "/movies", "/series", "/calendar", "/about", "/static/site.css", "/static/mascot.jpg", "/health"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200, path)
        for path in ("/sitemap.xml", "/feed.xml"):
            response = await self.client.get(path)
            ElementTree.fromstring(await response.text())

    async def test_article_has_server_rendered_content_and_schema(self):
        feed = await self.client.get("/feed.xml")
        root = ElementTree.fromstring(await feed.text())
        url = root.find("channel/item/link").text
        response = await self.client.get(url.removeprefix(self.cfg["base_url"]))
        text = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn('application/ld+json', text)
        self.assertIn('rel="canonical"', text)
        self.assertIn("Источник материала", text)
        self.assertIn("https://t.me/kinojdun_bot", text)

    async def test_seo_meta_tags_and_breadcrumbs(self):
        feed = await self.client.get("/feed.xml")
        root = ElementTree.fromstring(await feed.text())
        url = root.find("channel/item/link").text
        response = await self.client.get(url.removeprefix(self.cfg["base_url"]))
        text = await response.text()
        self.assertIn('name="twitter:card"', text)
        self.assertIn('BreadcrumbList', text)
        self.assertIn('Напомнить о премьере в Telegram', text)

    async def test_search_escapes_input_and_is_not_indexed(self):
        response = await self.client.get("/news", params={"q": '"><script>alert(1)</script>'})
        text = await response.text()
        self.assertNotIn("<script>alert(1)</script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("noindex, follow", text)
        self.assertIn("Пока ничего не нашлось", text)

    async def test_local_indexing_is_disabled_and_real_404(self):
        response = await self.client.get("/robots.txt")
        self.assertIn("Disallow: /", await response.text())
        response = await self.client.get("/news/missing")
        self.assertEqual(response.status, 404)
        self.assertIn("Эта сцена не найдена", await response.text())

    async def test_movies_and_series_have_content(self):
        for path, label in (("/movies", "Фильмы"), ("/series", "Сериалы")):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200)
            text = await response.text()
            self.assertIn("news-card", text)
            self.assertIn(label, text)
            self.assertNotIn("Пока ничего не нашлось", text)

    async def test_sync_failure_retains_content_and_reports_status(self):
        response = await self.client.get("/health")
        data = await response.json()
        self.assertEqual(data["articles"], 19)
        self.assertEqual(data["titles"], 16)
        self.assertIn("TMDB_API_KEY", data["sync_error"])
        self.assertNotIn("api_key", data)

    async def test_calendar_has_no_past_premieres_and_purges_obsolete(self):
        response = await self.client.get("/calendar")
        self.assertEqual(response.status, 200)
        html = await response.text()
        # Verify obsolete/past titles are absent
        self.assertNotIn("Разделение", html)
        self.assertNotIn("Белый лотос", html)
        self.assertNotIn("Пламя и пепел", html)
        self.assertNotIn("Трон: Арес", html)
        # Verify genuine upcoming titles are present
        self.assertIn("Мстители: Доктор Дум", html)
        self.assertIn("Дюна: Часть третья", html)
        self.assertIn("Кэрри", html)
        self.assertIn("Бегущий по лезвию 2099", html)

