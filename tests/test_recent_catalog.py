import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.backfill_recent_catalog import recent
from tests.test_website import config
from website.catalog_views import streaming_home
from website.content import Store


class RecentCatalogTests(unittest.TestCase):
    def test_seasons_count_but_future_and_old_releases_do_not(self):
        lower, upper = '2024-01-01', '2026-10-07'
        self.assertTrue(recent('tv', {'first_air_date': '2021-01-01', 'seasons': [
            {'season_number': 2, 'air_date': '2025-08-06'}]}, lower, upper))
        self.assertFalse(recent('tv', {'first_air_date': '2010-01-01', 'seasons': [
            {'season_number': 0, 'air_date': '2025-01-01'}]}, lower, upper))
        self.assertFalse(recent('movie', {'release_date': '2026-12-18'}, lower, upper))
        self.assertFalse(recent('movie', {'release_date': 'bad'}, lower, upper))

    def test_home_has_released_hits_and_recent_seasons(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'site.db'
            store = Store(path)
            for media, ident, first, season in [('movie', 1, '2024-03-01', None),
                                                ('tv', 2, '2021-09-01', '2025-06-27')]:
                item = dict(key=f'{media}:{ident}', id=ident, media_type=media,
                            title=f'Проект {ident}', overview='Описание', first_release=first,
                            season_premiere=season, rating=8, votes=1000, popularity=100,
                            genres=[], status='Ended' if media == 'tv' else 'Released')
                store.ensure_news_card(media, ident, item['title'], 'https://www.themoviedb.org', item=item)
            store.db.commit()
            with patch('website.catalog_views.today', return_value=date(2026, 10, 7)):
                html = streaming_home(store, config(path))
            self.assertIn('Громкие фильмы последних трёх лет', html)
            self.assertIn('Популярные сериалы и новые сезоны', html)
            self.assertIn('2024–2026 · УЖЕ ВЫШЛИ', html)
            self.assertIn('/title/movie/1', html)
            self.assertIn('/title/tv/2', html)
            self.assertEqual(store.articles(), [])
            store.db.close()
