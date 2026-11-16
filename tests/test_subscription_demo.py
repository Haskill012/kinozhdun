import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import AioHTTPTestCase
from website.__main__ import create_app, STORE


class SubscriptionDemoTests(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = {'database': str(Path(self.tmp.name) / 'site.db'), 'bot_database': None,
               'bot_url': 'https://t.me/kinojdun_bot', 'max_bot_url': 'https://max.ru/id5001170357_1_bot',
               'channel_url': 'https://t.me/kinojdun_channel', 'base_url': 'http://127.0.0.1:8099',
               'public': False, 'api_key': '', 'catalog_size': 50, 'sync_seconds': 3600,
               'api_base': 'https://api.themoviedb.org/3', 'batch_size': 2}
        app = create_app(cfg)
        app.cleanup_ctx.clear()
        async def close_store(application):
            application[STORE].db.close()
        app.on_cleanup.append(close_store)
        return app

    async def test_intro_is_first_and_keeps_six_slides(self):
        html = await (await self.client.get('/')).text()
        self.assertIn('data-slide="0" role="group" aria-label="Как работает КиноЖдун"', html)
        self.assertEqual(html.count(' data-slide='), 6)
        self.assertEqual(html.count('<h1'), 1)
        self.assertIn('/static/subscription-demo.mp4', html)
        self.assertIn('data-slide="1" role="group" aria-label="Поиск фильма в Telegram"', html)
        self.assertIn('/static/telegram-search-demo.mp4', html)
        self.assertEqual(html.count('class="subscription-demo-video"'), 3)
        self.assertIn('data-slide="2" role="group" aria-label="Как поделиться списком или фильмом"', html)
        self.assertIn('/static/telegram-share-demo.mp4', html)

    async def test_third_recording_absent_keeps_six_slides(self):
        with patch('website.catalog_views.telegram_share_demo_available', return_value=False):
            html = await (await self.client.get('/')).text()
            self.assertNotIn('telegram-share-demo.mp4', html)
            self.assertEqual(html.count('class="subscription-demo-video"'), 2)
            self.assertEqual(html.count(' data-slide='), 6)

    async def test_second_recording_absent_keeps_movie_slides(self):
        with patch('website.catalog_views.telegram_search_demo_available', return_value=False):
            html = await (await self.client.get('/')).text()
            self.assertNotIn('telegram-search-demo.mp4', html)
            self.assertEqual(html.count(' data-slide='), 6)

    async def test_one_shared_video_with_project_specific_subscription(self):
        item = self.app[STORE].catalog()[0]
        response = await self.client.get('/how-to-subscribe', params={'project': item['key']})
        self.assertEqual(response.status, 200)
        html = await response.text()
        self.assertIn(item['title'], html)
        self.assertIn(f'c_{item["media_type"]}_{item["id"]}', html)
        self.assertIn('/static/subscription-demo.mp4', html)
        project = await self.client.get(f'/title/{item["media_type"]}/{item["id"]}')
        self.assertIn('/how-to-subscribe?project=' + item['key'], await project.text())
        self.assertEqual((await self.client.get('/how-to-subscribe?project=movie:999999999')).status, 404)

    async def test_video_supports_byte_ranges_for_mobile_seek(self):
        response = await self.client.get('/static/subscription-demo.mp4', headers={'Range': 'bytes=0-1023'})
        self.assertEqual(response.status, 206)
        self.assertEqual(len(await response.read()), 1024)
        self.assertEqual(response.content_type, 'video/mp4')

    async def test_no_broken_intro_when_recording_is_absent(self):
        with patch('website.catalog_views.subscription_demo_available', return_value=False):
            html = await (await self.client.get('/')).text()
            self.assertNotIn('subscription-demo-video', html)
            self.assertEqual((await self.client.get('/how-to-subscribe')).status, 404)
