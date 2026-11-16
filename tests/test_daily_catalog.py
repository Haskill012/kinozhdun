import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from website.content import Store
from website.editor import Editor, ranked_discovery
from website.__main__ import configuration


class DailyCatalogTests(unittest.IsolatedAsyncioTestCase):
    def test_configuration_accepts_thirty(self):
        with patch.dict('os.environ', {'SITE_DAILY_CARDS': '30'}):
            self.assertEqual(configuration()['daily_cards'], 30)

    def test_new_releases_and_reliable_ratings_both_enter_balanced_selection(self):
        entries = [('movie', {'id': 1, 'release_date': '2026-10-06', 'vote_average': 7, 'vote_count': 100}),
                   ('movie', {'id': 2, 'release_date': '2026-05-01', 'vote_average': 9, 'vote_count': 1000}),
                   ('tv', {'id': 3, 'first_air_date': '2026-10-05', 'vote_average': 8, 'vote_count': 100}),
                   ('movie', {'id': 4, 'release_date': '2027-01-01', 'vote_average': 10, 'vote_count': 1})]
        with patch('website.editor.today', return_value=date(2026, 10, 6)):
            ids = [entry[1]['id'] for entry in ranked_discovery(entries)]
        self.assertEqual(ids[:3], [1, 2, 3])
        self.assertEqual(len(ids), len(set(ids)))

    async def test_thirty_cards_each_day_with_replenishment_and_restart_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'site.db'
            store = Store(path)
            store.state('catalog_selected', 'reviewed')
            store.state('initial_catalog_visible', 'true')
            cfg = {'api_key': 'test', 'api_base': 'unused', 'bot_database': None,
                   'channel_url': 'https://t.me/test', 'bot_url': 'https://t.me/test_bot',
                   'daily_cards': 30, 'catalog_size': 50, 'min_rating': 7}
            queries = []
            async def fetch(endpoint, **params):
                if endpoint.startswith('/discover/'):
                    queries.append(params)
                    return {'results': [{'id': n, 'popularity': 100, 'vote_average': 8,
                        'vote_count': 100, 'release_date': '2026-10-01', 'first_air_date': '2026-10-01'}
                        for n in range(1, 41)]}
                if endpoint == '/tv/on_the_air':
                    return {'results': []}
                ident = int(endpoint.split('/')[-1])
                return {'id': ident, 'title': f'Фильм {ident}', 'name': f'Сериал {ident}',
                        'overview': 'Описание', 'poster_path': '/p.jpg', 'popularity': 100,
                        'vote_average': 8, 'vote_count': 100, 'release_date': '2026-10-01',
                        'first_air_date': '2026-10-01', 'videos': {'results': []}}
            for day, expected in [(date(2026, 10, 6), 30), (date(2026, 10, 7), 60)]:
                editor = Editor(store, cfg);editor.fetch = fetch
                with patch('website.editor.today', return_value=day), patch('website.content.today', return_value=day):
                    await editor.sync()
                    self.assertEqual(len(store.catalog()), expected)
                    self.assertEqual(store.release_catalog(30), 0)
                    store.db.close();store = Store(path)
                    self.assertEqual(store.release_catalog(30), 0)
                self.assertEqual(len({c['key'] for c in store.catalog()}), expected)
                self.assertEqual(len([c for c in store.catalog() if c['media_type']=='movie']), expected // 2)
            self.assertTrue(any(q.get('sort_by')=='vote_average.desc' for q in queries))
            self.assertTrue(any(q.get('sort_by')=='primary_release_date.desc' for q in queries))
            store.db.close()
