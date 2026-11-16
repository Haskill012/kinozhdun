import tempfile
import unittest
from pathlib import Path

from scripts.backfill_seo_catalog import interleave, rejection, publish
from website.content import Store


class SEOCatalogBackfillTests(unittest.TestCase):
    def detail(self, **changes):
        return dict(id=1, title='Известный фильм', original_title='Famous Movie',
                    overview='Подробное описание известного фильма с героями и сюжетом. ' * 4,
                    poster_path='/poster.jpg', genres=[{'id': 18, 'name': 'драма'}],
                    release_date='2009-12-10', vote_count=10000, vote_average=7.5,
                    original_language='en', production_countries=[{'iso_3166_1': 'US'}], **changes)

    def test_discovery_lanes_deduplicate_and_preserve_rank(self):
        self.assertEqual(interleave([['a', 'b', 'c'], ['b', 'd']]), ['a', 'b', 'd', 'c'])

    def test_no_thin_untranslated_future_or_unpopular_cards(self):
        base = self.detail()
        self.assertIsNone(rejection('movie', base, {}, '2026-10-07'))
        for changes, expected in [({'overview': 'Коротко'}, 'no-substantial-russian-description'),
                                  ({'title': 'Untranslated'}, 'no-russian-title'),
                                  ({'release_date': '2027-01-01'}, 'not-released'),
                                  ({'vote_count': 20}, 'insufficient-audience-evidence'),
                                  ({'adult': True}, 'adult')]:
            self.assertEqual(rejection('movie', {**base, **changes}, {}, '2026-10-07'), expected)

    def test_box_office_hits_can_have_modest_ratings(self):
        base = {**self.detail(), 'vote_average': 5.5, 'revenue': 500_000_000}
        self.assertIsNone(rejection('movie', base, {}, '2026-10-07'))
        self.assertEqual(rejection('movie', {**base, 'revenue': 1000}, {}, '2026-10-07'), 'low-rating')

    def cards(self):
        return [dict(key=f'movie:{i}', media_type='movie', id=i, title=f'Фильм {i}',
                     overview='Полное описание', poster='https://image.tmdb.org/t/p/w500/p.jpg',
                     first_release='2000-01-01') for i in range(1, 501)]

    def test_atomic_batch_preserves_daily_quota_and_news_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'site.db'
            store = Store(path)
            store.state('cards_published:2026-10-07', '30')
            backup = publish(store, self.cards(), {'database': str(path)})
            self.assertTrue(Path(backup).exists())
            self.assertEqual(len(store.catalog()), 500)
            self.assertEqual(len(store.titles()), 500)
            self.assertEqual(store.articles(), [])
            self.assertEqual(store.state('cards_published:2026-10-07'), '30')
            with self.assertRaises(AssertionError):
                publish(store, self.cards(), {'database': str(path)})
            self.assertEqual(len(store.catalog()), 500)
            store.db.close()

    def test_failed_batch_rolls_back_every_card(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'site.db'
            store = Store(path)
            store.db.execute("create trigger fail_batch before insert on catalog when new.key='movie:250' begin select raise(abort,'test failure'); end")
            store.db.commit()
            with self.assertRaises(Exception):
                publish(store, self.cards(), {'database': str(path)})
            self.assertEqual(store.catalog(), [])
            self.assertEqual(store.titles(), [])
            store.db.close()
