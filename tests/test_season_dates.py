import datetime
import unittest
from types import SimpleNamespace
from bot.services.season_dates import upcoming_season, season_premieres
from bot.services.tracker import TrackerService
from bot.utils.formatting import format_item_details


class SeasonDatesTests(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date.today()
        self.premiere = self.today - datetime.timedelta(days=4)
        self.episode = self.today + datetime.timedelta(days=3)
        self.details = {
            "tmdb_id": 1, "title": "Гангстерленд", "number_of_seasons": 2,
            "seasons": [{"season_number": 0, "air_date": self.episode.isoformat()},
                        {"season_number": 2, "air_date": self.premiere.isoformat()}],
            "next_episode_to_air": {"season_number": 2, "episode_number": 4,
                                    "air_date": self.episode.isoformat()},
        }

    def test_weekly_episode_is_not_an_upcoming_season(self):
        self.assertEqual(upcoming_season(self.details), (None, None))
        self.assertEqual(season_premieres(self.details), [(2, self.premiere)])
        item = SimpleNamespace(next_air_date=self.episode, status="waiting")
        self.assertIsNone(TrackerService(None, None).evaluate_tv_update(item, self.details))

    def test_card_distinguishes_aired_premiere_and_next_episode(self):
        text = format_item_details(self.details, "tv")
        self.assertIn("Премьера 2-го сезона состоялась", text)
        self.assertIn("2 сезон, 4 серия", text)
        self.assertIn("Дата премьеры нового сезона:</b> <i>пока не объявлена", text)

    def test_first_episode_fallback_and_future_season(self):
        self.details["next_episode_to_air"]["episode_number"] = 1
        self.assertEqual(upcoming_season(self.details), (2, self.episode))
        self.details["next_episode_to_air"]["episode_number"] = 4
        self.details["seasons"].append({"season_number": 3, "air_date": self.episode.isoformat()})
        self.assertEqual(upcoming_season(self.details), (3, self.episode))

    def test_premiere_release_after_tmdb_advances_episode(self):
        item = SimpleNamespace(next_air_date=self.premiere, status="announced", notified_released=False)
        result = TrackerService(None, None).evaluate_tv_update(item, self.details)
        self.assertEqual(result["type"], "released")
        self.assertEqual(result["next_air_date"], self.premiere)
