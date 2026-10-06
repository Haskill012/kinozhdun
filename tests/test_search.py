import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from website.__main__ import create_app, STORE
from website.content import Store
from website.search import suggestions, matches, ProjectSearch
from website.title_names import source_aliases, canonical_title
from tests.test_website import config


class SearchTests(unittest.TestCase):
    def test_aliases_and_small_typo(self):
        pluribus = dict(title='Одна из многих', original_title='Pluribus')
        for query in ('Плюрибус', 'pluribus', 'Плюрибуc', 'одна из многих'):
            self.assertTrue(matches(pluribus, query), query)
        film = dict(title='На игле', original_title='Trainspotting', aliases=['На игле: альтернативное'])
        for query in ('Транспоттинг', 'Trainspotting', 'На игле', 'альтернативное'):
            self.assertTrue(matches(film, query), query)
        self.assertFalse(matches(film, 'совсем другой фильм'))
        self.assertEqual(canonical_title('Плюрибус', 'Pluribus'), 'Одна из многих')
        self.assertEqual(canonical_title('T2', 'T2 Trainspotting'), 'T2')
        self.assertEqual(source_aliases({'alternative_titles': {'titles': [{'title': 'На игле'}]},
                                       'translations': {'translations': [{'data': {'title': 'Trainspotting'}}]}}),
                         ['На игле', 'Trainspotting'])

    def test_matching_original_title_case_yo_ranking_and_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'site.db')
            items = [dict(key='tv:1',id=1,media_type='tv',title='Укрытие',original_title='Silo',rating=8.3,votes=100),
                     dict(key='tv:2',id=2,media_type='tv',title='Далёкий город'),
                     dict(key='movie:3',id=3,media_type='movie',title='Новое Укрытие',popularity=999),
                     dict(key='tv:4',id=4,media_type='tv',title='Укрытие скрытое')]
            for item in items:
                store.queue_title(item)
            store.db.execute("UPDATE catalog SET published='2026-10-06' WHERE key!='tv:4'")
            store.db.commit()
            self.assertEqual(suggestions(store,'УКРЫТИЕ')[0]['url'],'/title/tv/1')
            self.assertEqual(len(suggestions(store,'укрытие')),2)
            self.assertEqual(suggestions(store,'silo')[0]['title'],'Укрытие')
            self.assertEqual(suggestions(store,'далекий')[0]['title'],'Далёкий город')
            self.assertEqual(suggestions(store,'у'),[])
            self.assertEqual(suggestions(store,"' OR 1=1 --"),[])
            store.db.close()


class SearchHTTPTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp=tempfile.TemporaryDirectory()
        app=create_app(config(Path(self.tmp.name)/'site.db'))
        store=app[STORE]
        store.queue_title(dict(key='tv:99999',id=99999,media_type='tv',title='Укрытие',original_title='Silo',rating=8.3,votes=100,source_url='https://www.themoviedb.org/tv/99999'))
        store.db.execute("UPDATE catalog SET published='2026-10-06' WHERE key='tv:99999'")
        store.db.commit()
        return app

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.tmp.cleanup()

    async def test_api_and_header_on_every_page_with_fallback_search(self):
        response=await self.client.get('/api/search?q=silo')
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['results'][0]['url'],'/title/tv/99999')
        self.assertEqual(response.headers['X-Robots-Tag'],'noindex')
        for path in ('/','/catalog','/calendar','/about','/news','/movies','/series','/title/tv/99999','/missing'):
            response=await self.client.get(path)
            text=await response.text()
            self.assertIn('id="site-search-input"',text,path)
            self.assertIn('aria-controls="site-search-results"',text,path)
        response=await self.client.get('/catalog?q=silo')
        self.assertIn('Укрытие',await response.text())
        response=await self.client.get('/api/search?q=x')
        self.assertEqual((await response.json())['results'],[])

    async def test_remote_results_in_api_and_catalog_do_not_publish_until_opened(self):
        remote = dict(key='movie:627', id=627, media_type='movie', title='На игле', original_title='Trainspotting',
                      rating=7.9, votes=100, first_release='1996-02-23', remote_match=True, genres=[])
        with patch.object(ProjectSearch, 'projects', AsyncMock(return_value=[remote])):
            response = await self.client.get('/api/search?q=Транспоттинг')
            item = (await response.json())['results'][0]
            self.assertEqual(item['alternate_title'], 'Trainspotting')
            response = await self.client.get('/catalog?q=Транспоттинг')
            self.assertIn('/title/movie/627', await response.text())
            response = await self.client.get('/series?q=Транспоттинг')
            self.assertNotIn('/title/movie/627', await response.text())
        self.assertIsNone(self.app[STORE].catalog_item('movie:627', False))

    async def test_remote_cache_shared_for_known_aliases_and_local_on_failure(self):
        service = ProjectSearch(self.app[STORE], {'api_key': 'test'})
        remote = dict(key='tv:10', id=10, media_type='tv', title='Одна из многих', original_title='Pluribus')
        service.fetch_remote = AsyncMock(return_value=[remote])
        self.assertEqual((await service.projects('Плюрибус'))[0]['id'], 10)
        self.assertEqual((await service.projects('Pluribus'))[0]['id'], 10)
        service.fetch_remote.assert_awaited_once_with('pluribus')
        service.fetch_remote = AsyncMock(return_value=[])
        self.assertEqual((await service.projects('укры'))[0]['title'], 'Укрытие')
        await service.projects('Silo')
        service.fetch_remote.assert_awaited_once()
