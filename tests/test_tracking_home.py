import re
import tempfile
import unittest
from pathlib import Path

from tests.test_website import config
from website.content import Store
from website.catalog_views import streaming_home, tracking_events


class TrackingHomeTests(unittest.TestCase):
    def test_tracking_layout_unique_search_ids_and_real_event_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'site.db');cfg=config(Path(directory)/'site.db')
            store.seed_guides(cfg['bot_url']);store.seed_catalog(cfg['bot_url'])
            for fingerprint,title in [('tmdb:tv:1:trailer:key123','Настоящий новый трейлер'),
                                      ('channel:123','Обычная новость'),
                                      ('tmdb:tv:1:release:2026-10-06','Выход по календарю')]:
                store.publish(fingerprint,title,'series','Описание',[], 'https://www.themoviedb.org/tv/1')
            self.assertEqual({a['title'] for a in tracking_events(store)}, {'Настоящий новый трейлер', 'Выход по календарю'})
            html=streaming_home(store,cfg)
            for text in ('ТРЕКЕР ЛЮБИМЫХ ФИЛЬМОВ И СЕРИАЛОВ','spotlight','+ Ждать','Что изменилось','Ближайшие события', 'Больше всего ждут', 'Не проверяйте даты сами.'):
                self.assertIn(text,html)
            ids=re.findall(r'\bid="([^"]+)"',html)
            self.assertEqual(len(ids),len(set(ids)))
            self.assertNotIn('hero-search-results',ids)
            self.assertNotIn('ПРИМЕР УВЕДОМЛЕНИЯ',html)
            self.assertNotIn('Как работает КиноЖдун',html)
            self.assertIn('site-search-results',ids)
            self.assertIn('aria-controls="site-search-results"',html)
            self.assertNotIn('Отслеживать', html)
            self.assertNotIn('Найдите проект для отслеживания', html)
            self.assertEqual(html.count('data-slide='), 6)
            self.assertEqual(html.count('fetchpriority="high"'), 1)
            self.assertEqual(html.count('data-src='), 5)
            store.db.close()
