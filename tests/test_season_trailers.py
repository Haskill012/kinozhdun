import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from website.content import Store
from website.editor import Editor
from website.trailers import select_trailers, trailer_season
from website.views import trailer_player


def video(key, language="en", **extra):
    return {"official": True, "site": "YouTube", "type": "Trailer",
            "key": key, "iso_639_1": language, **extra}


class TrailerSelectionTests(unittest.TestCase):
    def test_newest_season_beats_russian_first_season(self):
        detail = {"videos": {"results": [video("oldrussian1", "ru", name="1 сезон")]},
                  "season_videos": {3: [video("newenglish3")], 4: [video("newteaser44", type="Teaser")]}}
        trailers = select_trailers("tv", detail)
        self.assertEqual(trailers[-1]["key"], "newenglish3")
        self.assertEqual(trailer_season(trailers[-1]), 3)

    def test_language_preference_within_same_season_and_movie(self):
        detail = {"season_videos": {2: [video("english2222"), video("russian2222", "ru")]}}
        self.assertEqual(select_trailers("tv", detail)[-1]["key"], "russian2222")
        detail = {"videos": {"results": [video("english2222"), video("russian2222", "ru")]}}
        self.assertEqual(select_trailers("movie", detail)[-1]["key"], "russian2222")

    def test_same_key_keeps_explicit_season_and_rejects_invalid_nonofficial(self):
        detail = {"videos": {"results": [video("samevideo11")]}, "season_videos": {
            3: [video("samevideo11"), video("badkey/<>", "ru"), video("unofficial1", official=False)]}}
        result = select_trailers("tv", detail)
        self.assertEqual(len(result), 1)
        self.assertEqual(trailer_season(result[0]), 3)

    def test_general_videos_with_explicit_season_names(self):
        for name in ("Season 3 Official Trailer", "Трейлер 3 сезона", "3-й сезон — трейлер"):
            with self.subTest(name=name):
                self.assertEqual(trailer_season({"name": name}), 3)
        self.assertIn("Трейлер 3-го сезона", trailer_player("newenglish3", "en", 3))


class SeasonVideoFetchTests(unittest.IsolatedAsyncioTestCase):
    def test_backfill_does_not_publish_old_trailer_as_news_but_later_updates_do(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "site.db")
            editor = Editor(store, {})
            detail = {"id": 125988, "name": "Укрытие", "videos": {"results": [video("season1old1")]}}
            editor.process("tv", detail, publish_card=True)
            detail["season_videos"] = {3: [video("season3new1")]}
            editor.process("tv", detail)
            self.assertEqual(len(store.articles()), 0)
            detail["season_videos"][3].append(video("season3new2"))
            editor.process("tv", detail)
            self.assertEqual(len(store.articles()), 1)
            store.db.close()

    async def test_fetch_season_endpoints_and_stop_at_newest_official_trailer(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "site.db")
            editor = Editor(store, {})
            endpoints = []

            async def fetch(endpoint, **params):
                endpoints.append(endpoint)
                self.assertEqual(params["include_video_language"], "ru,en,null")
                if endpoint == "/tv/125988":
                    return {"id": 125988, "name": "Укрытие", "seasons": [
                        {"season_number": n} for n in (0, 1, 2, 3, 4)],
                        "videos": {"results": [video("season1old1", "ru")]}}
                if endpoint.endswith("/4/videos"):
                    return {"results": [video("season4peek", type="Teaser")]}
                if endpoint.endswith("/3/videos"):
                    return {"results": [video("season3new1")]}
                self.fail("Older seasons should not be queried")

            editor.fetch = fetch
            detail = await editor.fetch_details("tv", 125988)
            editor.process("tv", detail, emit_news=False, publish_card=True)
            item = store.catalog_item("tv:125988")
            self.assertEqual(item["trailer"], "season3new1")
            self.assertEqual(item["trailer_season"], 3)
            self.assertEqual(endpoints, ["/tv/125988", "/tv/125988/season/4/videos", "/tv/125988/season/3/videos"])
            self.assertEqual(len(store.articles()), 0)
            store.db.close()

    async def test_series_without_seasons_and_movies_need_no_season_queries(self):
        editor = Editor(None, {})
        for media in ("tv", "movie"):
            editor.fetch = AsyncMock(return_value={"id": 1, "videos": {"results": []}})
            await editor.fetch_details(media, 1)
            self.assertEqual(editor.fetch.await_count, 1)
