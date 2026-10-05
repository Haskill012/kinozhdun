import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree
from unittest.mock import patch
from datetime import date

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

    def test_daily_queue_persists_and_does_not_catch_up(self):
        for n in range(50):
            self.store.queue_title({"key": f"movie:{n}", "id": n, "media_type": "movie", "title": str(n)})
        with patch("website.content.today", return_value=date(2026, 10, 5)):
            self.assertEqual(self.store.release_catalog(3), 3)
            self.assertEqual(self.store.release_catalog(3), 0)
            self.store.db.close()
            self.store = Store(Path(self.tmp.name) / "site.db")
            self.assertEqual(self.store.release_catalog(3), 0)
        with patch("website.content.today", return_value=date(2026, 10, 10)):
            self.assertEqual(self.store.release_catalog(3), 3)
        self.assertEqual(len(self.store.catalog()), 6)
        self.assertEqual(len(self.store.catalog(False)), 50)

    def test_verified_seed_has_50_and_restart_preserves_removed_card_and_quota(self):
        self.store.seed_live_catalog()
        self.assertEqual(len(self.store.catalog(False)), 50)
        self.assertEqual(self.store.release_catalog(), 3)
        removed = self.store.catalog()[0]["key"]
        self.store.db.execute("DELETE FROM catalog WHERE key=?", (removed,))
        self.store.db.commit()
        self.store.seed_live_catalog()
        self.assertIsNone(self.store.catalog_item(removed, False))
        self.assertEqual(self.store.release_catalog(), 0)

    def test_quality_filter_allows_popular_unrated_future_titles(self):
        detail = {**self.movie, "poster_path": "/poster.jpg", "popularity": 10, "vote_count": 0, "vote_average": 0}
        self.assertTrue(self.editor.eligible("movie", detail))
        self.assertFalse(self.editor.eligible("movie", {**detail, "vote_count": 100, "vote_average": 4.5}))
        self.assertFalse(self.editor.eligible("movie", {**detail, "popularity": 0.2}))
        self.assertFalse(self.editor.eligible("movie", {**detail, "adult": True}))
        self.assertFalse(self.editor.eligible("movie", {**detail, "release_date": "1990-01-01"}))

    def test_russian_trailer_preferred_and_new_english_trailer_makes_news(self):
        detail = copy.deepcopy(self.movie)
        ru = {"official": True, "type": "Trailer", "site": "YouTube", "key": "russian1234", "iso_639_1": "ru", "published_at": "2026-09-01"}
        en = {**ru, "key": "english1234", "iso_639_1": "en", "published_at": "2026-10-01"}
        detail["videos"] = {"results": [ru]}
        self.editor.process("movie", detail)
        detail["videos"]["results"].append(en)
        self.editor.process("movie", detail)
        self.editor.process("movie", detail)
        self.assertEqual(self.store.snapshot("movie:123")["trailer"], "russian1234")
        self.assertEqual(sum(":trailer:" in a["fingerprint"] for a in self.store.articles()), 1)

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

    def test_catalog_restart_preserves_live_dates_and_removed_titles(self):
        with patch("website.content.today", return_value=date(2026, 10, 5)):
            self.store.seed_catalog("https://t.me/kinojdun_bot")
            item = self.store.snapshot("movie:1170608")
            item["release_date"] = "2027-01-01"
            item["status"] = "Post Production"
            self.store.save_title(item["key"], item)
            self.store.delete_title("tv:224377")
            self.store.db.close()
            self.store = Store(Path(self.tmp.name) / "site.db")
            self.store.seed_catalog("https://t.me/kinojdun_bot")
            self.assertEqual(self.store.snapshot(item["key"]), item)
            self.assertIsNone(self.store.snapshot("tv:224377"))

    def test_catalog_preserves_existing_snapshot_before_first_seed(self):
        item = {"key": "movie:1170608", "release_date": "2027-01-01", "title": "Обновлённый фильм"}
        self.store.save_title(item["key"], item)
        with patch("website.content.today", return_value=date(2026, 10, 5)):
            self.store.seed_catalog("https://t.me/kinojdun_bot")
        self.assertEqual(self.store.snapshot(item["key"]), item)

    def test_catalog_never_seeds_expired_dates(self):
        with patch("website.content.today", return_value=date(2027, 1, 1)):
            self.store.seed_catalog("https://t.me/kinojdun_bot")
            self.assertEqual(self.store.titles(), [])
            self.assertEqual(self.store.articles(), [])

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


class CatalogSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_pipeline_selects_50_and_opens_three_without_duplicate_news(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "site.db")
            cfg = {**config(Path(directory) / "site.db"), "api_key": "test", "catalog_size": 50}
            editor = Editor(store, cfg)
            video_key = None

            async def fetch(endpoint, **params):
                if endpoint.startswith("/discover/"):
                    return {"results": [{"id": n, "popularity": 100-n, "vote_average": 8, "vote_count": 100} for n in range(1, 26)]}
                if endpoint == "/tv/on_the_air":
                    return {"results": []}
                tmdb_id = int(endpoint.split("/")[-1])
                media = endpoint.split("/")[1]
                videos = [{"official": True, "type": "Trailer", "site": "YouTube", "key": video_key, "iso_639_1": "ru"}] if video_key else []
                return {"id": tmdb_id, "title": f"Фильм {tmdb_id}", "name": f"Сериал {tmdb_id}", "overview": "Описание", "poster_path": "/poster.jpg", "popularity": 100-tmdb_id, "vote_average": 8, "vote_count": 100,
                        "release_date": (today()+timedelta(days=7)).isoformat(), "first_air_date": (today()+timedelta(days=7)).isoformat(), "videos": {"results": videos}}

            editor.fetch = fetch
            await editor.sync()
            self.assertEqual(len(store.catalog(False)), 50)
            self.assertEqual(len(store.catalog()), 3)
            self.assertTrue(store.state("catalog_selected"))
            video_key = "russian1234"
            await editor.sync()
            await editor.sync()
            self.assertEqual(len(store.catalog()), 3)
            self.assertEqual(sum(":trailer:" in a["fingerprint"] for a in store.articles(limit=100)), 3)
            store.db.close()


class WebsiteHTTPTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(Path(self.tmp.name) / "site.db")
        return create_app(self.cfg)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_hidden_card_404_then_public_embed_and_sitemap(self):
        from website.__main__ import STORE
        store = self.app[STORE]
        item = {"key": "movie:123", "id": 123, "media_type": "movie", "title": "Карточка", "overview": "Описание", "source_url": "https://www.themoviedb.org/movie/123", "trailer": "russian1234", "trailer_language": "ru"}
        store.queue_title(item)
        response = await self.client.get("/title/movie/123")
        self.assertEqual(response.status, 404)
        store.release_catalog()
        response = await self.client.get("/title/movie/123")
        self.assertEqual(response.status, 200)
        text = await response.text()
        self.assertIn("youtube-nocookie.com/embed/russian1234", text)
        self.assertIn("На русском языке", text)
        response = await self.client.get("/sitemap.xml")
        self.assertIn("/title/movie/123", await response.text())
        response = await self.client.get("/movies")
        self.assertIn("/title/movie/123", await response.text())

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


class CatalogHTTPTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = {**config(Path(self.tmp.name) / "site.db"), "catalog_size": 50, "daily_cards": 3}
        return create_app(self.cfg)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_initial_collection_is_visible_and_filters_match_data(self):
        from website.__main__ import STORE
        items = self.app[STORE].catalog()
        self.assertEqual(len(items), 50)
        for route, count in (("/catalog", 50), ("/movies", 25), ("/series", 25)):
            response = await self.client.get(route)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.text()).count('class="poster-card"'), count)
        expected = [t for t in items if t['media_type'] == 'movie' and t.get('votes',0) >= 50 and (t.get('rating') or 0) >= 8 and 'фантастика' in t.get('genres', [])]
        response = await self.client.get('/catalog', params={'type':'movie','rating':'8','genre':'фантастика','sort':'rating'})
        text = await response.text()
        self.assertEqual(text.count('class="poster-card"'), len(expected))
        self.assertIn('noindex, follow', text)
        response = await self.client.get('/catalog', params={'q':'Обитель зла'})
        self.assertEqual((await response.text()).count('class="poster-card"'), 1)
        response = await self.client.get('/catalog', params={'q':'nonexistent-title'})
        self.assertIn('Ничего не нашлось', await response.text())

    async def test_project_layout_and_asset_versioning(self):
        from website.__main__ import STORE
        from website.views import ASSET_VERSION
        item = next(t for t in self.app[STORE].catalog() if t.get('trailer'))
        response = await self.client.get(f"/title/{item['media_type']}/{item['id']}")
        text = await response.text()
        self.assertIn('project-grid', text)
        self.assertIn('id="trailer"', text)
        self.assertIn('youtube-nocookie.com/embed/', text)
        self.assertIn('/static/site.css?v=' + ASSET_VERSION, text)
        self.assertIn('В список ожидания', text)
        self.assertNotIn('Новости проекта', text)
        response = await self.client.get('/health')
        data = await response.json()
        self.assertEqual(data['cards_published'], 50)
        self.assertEqual(data['cards_queued'], 0)

    async def test_public_seo_preserves_existing_metrika_and_verification(self):
        self.cfg.update(public=True, base_url="https://kinojdun.ru",
                        yandex_metrika_id="113425218",
                        google_verification="existing-google", yandex_verification="existing-yandex")
        response = await self.client.get('/')
        html = await response.text()
        self.assertIn('content="index, follow, max-image-preview:large"', html)
        self.assertEqual(html.count('ym(113425218,"init"'), 1)
        self.assertIn('data-metrika-id="113425218"', html)
        self.assertIn('content="existing-google"', html)
        self.assertIn('content="existing-yandex"', html)
        response = await self.client.get('/catalog?q=test')
        self.assertIn('content="noindex, follow"', await response.text())

    async def test_www_redirect_preserves_path_query_and_local_access(self):
        self.cfg.update(public=True, base_url="https://kinojdun.ru")
        response = await self.client.get('/catalog?q=%D0%BA%D0%B8%D0%BD%D0%BE&sort=rating',
                                         headers={'Host': 'www.kinojdun.ru'}, allow_redirects=False)
        self.assertEqual(response.status, 301)
        self.assertEqual(response.headers['Location'], 'https://kinojdun.ru/catalog?q=%D0%BA%D0%B8%D0%BD%D0%BE&sort=rating')
        response = await self.client.get('/catalog', headers={'Host': 'kinojdun.ru'})
        self.assertEqual(response.status, 200)
        self.cfg['public'] = False
        response = await self.client.get('/catalog', headers={'Host': 'www.kinojdun.ru'})
        self.assertEqual(response.status, 200)

    async def test_card_metadata_answers_release_query_without_changing_heading(self):
        from website.__main__ import STORE
        from website.editor import date_ru
        for media in ('movie', 'tv'):
            item = next(t for t in self.app[STORE].catalog() if t['media_type'] == media)
            response = await self.client.get(f"/title/{media}/{item['id']}")
            html = await response.text()
            self.assertIn('дата выхода', html.split('</title>')[0])
            self.assertIn(f'<h1>{item["title"]}</h1>', html)
            self.assertIn(f'rel="canonical" href="http://127.0.0.1:8099/title/{media}/{item["id"]}"', html)
            release = item.get('first_release') if media == 'movie' else item.get('release_date')
            if release:
                self.assertIn(date_ru(release), html.split('name="description"')[1].split('>')[0])
