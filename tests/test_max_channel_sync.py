import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from max_bot.channel_sync import ChannelSync, is_current_digest


class ChannelSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.db"
        db = sqlite3.connect(self.source)
        try:
            db.execute("CREATE TABLE channel_posts(id INTEGER, post_type TEXT, status TEXT, telegram_message_id INTEGER, published_at TEXT, post_text TEXT, poster_path TEXT)")
            db.executemany("INSERT INTO channel_posts VALUES (?,?,?,?,?,?,?)", [
                (1,'daily_digest','published',10,'2026-10-06 06:30:00','yesterday',None),
                (2,'daily_digest','pending',None,'2026-10-07 06:30:00','draft',None),
                (3,'daily_digest','published',11,'2026-10-07 06:30:00','<b>today</b>','/poster.jpg'),
                (4,'news','published',12,'2026-10-07 06:30:00','news',None),
            ])
            db.commit()
        finally:
            db.close()
        self.client = AsyncMock()
        self.client.upload_image_from_url.return_value = 'image-token'
        self.client.send_message.return_value = {'message':{'body':{'mid':'max-id'}}}
        self.journal = self.root / 'journal.db'
        self.sync = ChannelSync(self.client, -123, self.source, self.journal)
        self.today = dt.date(2026,10,7)

    def tearDown(self):
        self.sync.db.close()
        import gc
        gc.collect()
        self.temp.cleanup()

    async def test_only_current_published_digest_and_durable_dedup(self):
        self.assertEqual(await self.sync.tick(self.today), 1)
        kwargs = self.client.send_message.call_args.kwargs
        self.assertEqual(kwargs['text'], '<b>today</b>')
        self.assertEqual(kwargs['chat_id'], -123)
        self.assertEqual(kwargs['attachments'][0]['type'], 'image')
        self.assertTrue(kwargs['attachments'][1]['payload']['buttons'][1][0]['url'].startswith('https://max.ru/'))
        self.sync.db.close()
        self.sync = ChannelSync(self.client, -123, self.source, self.journal)
        self.assertEqual(await self.sync.tick(self.today), 0)
        self.client.send_message.assert_awaited_once()

    async def test_ambiguous_send_is_not_repeated(self):
        self.client.send_message.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            await self.sync.tick(self.today)
        self.assertEqual(await self.sync.tick(self.today), 0)
        self.assertEqual(self.sync.unresolved(), 1)
        self.client.send_message.assert_awaited_once()

    async def test_image_failure_is_retryable_before_send(self):
        self.client.upload_image_from_url.return_value = None
        with self.assertRaises(RuntimeError):
            await self.sync.tick(self.today)
        self.client.send_message.assert_not_awaited()
        self.client.upload_image_from_url.return_value = 'ready'
        self.assertEqual(await self.sync.tick(self.today), 1)

    async def test_missing_message_id_requires_manual_resolution(self):
        self.client.send_message.return_value = {'success':True}
        with self.assertRaises(RuntimeError):
            await self.sync.tick(self.today)
        self.assertEqual(await self.sync.tick(self.today), 0)
        self.assertEqual(self.sync.unresolved(), 1)

    def test_moscow_date_and_week(self):
        p = {'post_type':'daily_digest','published_at':'2026-10-06 22:30:00','post_text':'text'}
        self.assertTrue(is_current_digest(p, self.today))
        p.update(post_type='weekly_digest',published_at='2026-10-05 07:00:00')
        self.assertTrue(is_current_digest(p, self.today))
        self.assertFalse(is_current_digest(p, dt.date(2026,10,12)))


if __name__ == '__main__':
    unittest.main()
