import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from website.artwork import artwork, allowed_asset
from website.content import Store
from website.editor import Editor
from website.search import result
from website.views import image
from tests.test_website import config


class ArtworkTests(unittest.TestCase):
    def test_sparse_source_and_reviewed_bad_record_have_no_artwork(self):
        sparse = dict(id=1, poster_path='/p.jpg', backdrop_path='/b.jpg')
        self.assertEqual(artwork('movie', sparse), (None, None))
        self.assertEqual(artwork('tv', sparse), (None, None))
        self.assertEqual(artwork('movie', {**sparse, 'id':1426176, 'overview':'New description'}), (None, None))
        self.assertEqual(artwork('movie', {**sparse, 'genres':[{'id':1}]}), ('/p.jpg', '/b.jpg'))
        self.assertEqual(artwork('tv', {**sparse, 'genre_ids':[1]}), ('/p.jpg', '/b.jpg'))

    def test_rejected_assets_in_source_search_and_legacy_render(self):
        bad = '/jWZDC1FhauBSyPuIRT0IWqTFcfN.jpg'
        self.assertFalse(allowed_asset('https://image.tmdb.org/t/p/w500'+bad))
        self.assertEqual(artwork('movie', dict(id=2,overview='Plot',poster_path=bad,backdrop_path='/good.jpg')), (None,'/good.jpg'))
        self.assertNotIn(bad, image('https://image.tmdb.org/t/p/w500'+bad,'Movie'))
        self.assertIsNone(result(dict(id=2,title='Movie',media_type='movie',poster=bad))['poster'])

    def test_refresh_does_not_restore_poisoned_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'site.db')
            editor=Editor(store,config(Path(directory)/'site.db'))
            detail=dict(id=1426176,title='E Pluribus Unum',release_date='1969-06-30',
                        poster_path='/jWZDC1FhauBSyPuIRT0IWqTFcfN.jpg',backdrop_path='/5cqHto73TU7DH2v4MmRGZMPVTTT.jpg')
            for _ in range(2):
                editor.process('movie',detail,emit_news=False,publish_card=True)
                item=store.catalog_item('movie:1426176')
                self.assertIsNone(item['poster'])
                self.assertIsNone(item['image'])
            store.db.close()


class ArtworkIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_identity_must_match_requested_project(self):
        editor=Editor(None,{})
        editor.fetch=AsyncMock(return_value={'id':20})
        with self.assertRaisesRegex(RuntimeError,'идентификатор'):
            await editor.fetch_details('movie',10)
