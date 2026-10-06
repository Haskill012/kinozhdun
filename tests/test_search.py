import tempfile
import unittest
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase
from website.__main__ import create_app, STORE
from website.content import Store
from website.search import suggestions
from tests.test_website import config


class SearchTests(unittest.TestCase):
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
