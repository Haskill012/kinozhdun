import tempfile
import unittest
from pathlib import Path
from datetime import timedelta

from website.audience import audience_metadata, exclusion_reason, audience_items, audience_articles
from website.ratings import rating_class
from website.catalog_views import poster_card, spotlight_slide, streaming_home
from website.editor import Editor, today
from website.content import Store
from tests.test_website import config


class AudienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'site.db')
        self.cfg = config(Path(self.tmp.name) / 'site.db')
        self.editor = Editor(self.store, self.cfg)
        self.item = dict(key='tv:1', id=1, media_type='tv', title='Сериал', overview='Описание сериала',
                         original_language='ja', origin_country=['JP'], votes=100, rating=8,
                         popularity=100, genres=[], release_date=(today() + timedelta(days=5)).isoformat())

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_local_asian_popularity_alone_is_not_enough(self):
        self.assertEqual(exclusion_reason(self.item), 'asian-local')
        self.assertIsNone(exclusion_reason(dict(self.item, votes=2000)))
        self.assertIsNotNone(exclusion_reason(dict(self.item, votes=2000, title='Local Show')))
        self.assertIsNone(exclusion_reason(dict(self.item, ru_release=True)))
        self.assertIsNone(exclusion_reason(dict(self.item, ru_official_trailer=True)))
        self.assertIsNone(exclusion_reason(self.item, dict(audience_allow_keys=['tv:1'])))
        self.assertIsNone(exclusion_reason(dict(self.item, origin_country=['JP', 'RU'])))
        self.assertIsNone(exclusion_reason(dict(self.item, original_language='en', origin_country=['US'])))
        self.assertIsNone(exclusion_reason(dict(title='Нет данных')))

    def test_talk_shows_cannot_bypass_filter(self):
        for field in [dict(series_type='Talk Show'), dict(genres=['ток-шоу']), dict(genre_ids=[10767]), dict(series_type='Soap')]:
            item = dict(self.item, **field, ru_release=True)
            self.assertEqual(exclusion_reason(item, dict(audience_allow_keys=['tv:1'])), 'nonfiction-format')

    def test_regional_metadata_uses_actual_release_and_official_trailer(self):
        detail = dict(production_countries=[{'iso_3166_1':'JP'}], original_language='ja',
                      genres=[{'id':16, 'name':'мультфильм'}],
                      release_dates={'results':[{'iso_3166_1':'RU', 'release_dates':[{'type':3,'release_date':'2026-10-08'}]}]},
                      videos={'results':[{'official':False, 'type':'Trailer', 'iso_639_1':'ru'}]})
        meta = audience_metadata('movie', detail)
        self.assertTrue(meta['ru_release'])
        self.assertFalse(meta['ru_official_trailer'])
        self.assertEqual(meta['origin_country'], ['JP'])
        self.assertEqual(meta['genre_ids'], [16])

    def test_existing_excluded_card_is_preserved_but_not_promoted(self):
        self.store.queue_title(self.item)
        self.store.release_catalog()
        detail = dict(id=1, name='Сериал', overview='Описание сериала', original_language='ja',
                      origin_country=['JP'], poster_path='/poster.jpg', popularity=100,
                      vote_count=100, vote_average=8, genres=[],
                      next_episode_to_air={'air_date':self.item['release_date'],'season_number':1,'episode_number':1})
        self.assertFalse(self.editor.eligible('tv', detail))
        self.editor.process('tv', detail)
        self.assertIsNotNone(self.store.catalog_item('tv:1'))
        self.assertEqual(self.store.snapshot('tv:1')['original_language'], 'ja')
        self.assertEqual(self.store.articles(), [])
        self.assertNotIn('/title/tv/1', streaming_home(self.store, self.cfg))

    def test_news_filter_paginates_after_exclusions(self):
        self.store.queue_title(self.item)
        for n in range(4):
            self.store.publish(f'tmdb:tv:{n+1}:trailer:key{n}', f'Материал {n}', 'series', 'Описание', [],
                               'https://www.themoviedb.org/tv/1', media_type='tv', tmdb_id=n+1)
        all_visible = audience_articles(self.store, self.cfg, limit=10)
        self.assertEqual(len(all_visible), 3)
        self.assertEqual(audience_articles(self.store, self.cfg, limit=1, offset=1), all_visible[1:2])

    def test_rating_colors_are_consistent_and_numbers_remain_visible(self):
        for score, cls in [(7, 'rating-good'), (6.9,'rating-medium'), (5,'rating-medium'), (4.9,'rating-low')]:
            self.assertEqual(rating_class(score), cls)
            item = dict(self.item, rating=score)
            self.assertIn(cls, poster_card(item))
            self.assertIn(cls, spotlight_slide(item, self.cfg, 0))
            self.assertIn(f'{score:.1f}', poster_card(item))
