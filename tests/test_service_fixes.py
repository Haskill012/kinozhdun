import asyncio
import json
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import Settings
from bot.db.models import Base, User, TrackedItem, NotificationLog, SharedWatchlist, AnalyticsEvent
from bot.db.repositories import Repository
from bot.handlers.tracking import process_setdate_btn, process_date_input
from bot.handlers.privacy import request_deletion, confirm_deletion, cancel_deletion
from bot.handlers.start import cmd_start
from bot.services.channel import ChannelPublisher
from bot.scheduler.jobs import check_reminders_job
from aiogram.filters import CommandObject
from website.editorial import public_article
from website.views import stamp
from website.service_pages import about, help_page, privacy
from tests.test_website import config


class ServiceRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine('sqlite+aiosqlite:///'+str(Path(self.tmp.name)/'bot.db'))
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.settings = Settings(TELEGRAM_BOT_TOKEN='test', TMDB_API_KEY='test',
                                 TELEGRAM_CHANNEL_ID='@test', CHANNEL_AUTO_PUBLISH=True, CHANNEL_POSTING_ENABLED=True)
        self.tmdb = MagicMock()
        self.bot = MagicMock()
        self.bot.settings = None
        self.bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        self.bot.send_photo = AsyncMock(return_value=MagicMock(message_id=2))
        self.bot.__getitem__.side_effect = {'session_factory': self.factory, 'settings': self.settings, 'tmdb_client': self.tmdb}.__getitem__
        self.state = MagicMock();self.data={}
        async def update(**kwargs): self.data.update(kwargs)
        async def clear(): self.data.clear()
        self.state.update_data=AsyncMock(side_effect=update)
        self.state.clear=AsyncMock(side_effect=clear)
        self.state.set_state=AsyncMock()
        self.state.get_data=AsyncMock(side_effect=lambda:dict(self.data))
        async with self.factory() as session:
            repo=Repository(session)
            for telegram in (101,202):
                u=await repo.get_or_create_user(telegram,None,'Test')
                item=await repo.add_tracked_item(u.id,telegram,'movie','Film',None,None,None,None,None,'')
                if telegram==101:self.item_id=item.id
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose();self.tmp.cleanup()

    def callback(self, telegram=101, data=''):
        cb=MagicMock(bot=self.bot,from_user=MagicMock(id=telegram),data=data)
        cb.answer=AsyncMock();cb.message.edit_text=AsyncMock();return cb

    def message(self, telegram=101, text=''):
        msg=MagicMock(bot=self.bot,from_user=MagicMock(id=telegram),text=text)
        msg.answer=AsyncMock();return msg

    async def test_foreign_date_callback_and_forged_fsm_cannot_change_owner(self):
        cb=self.callback(202,'setdate:'+str(self.item_id))
        await process_setdate_btn(cb,self.state)
        self.state.set_state.assert_not_awaited()
        self.data['item_id']=self.item_id
        await process_date_input(self.message(202,(date.today()+timedelta(days=10)).strftime('%d.%m.%Y')),self.state)
        async with self.factory() as session:
            item=await Repository(session).get_tracked_item(self.item_id)
            self.assertIsNone(item.custom_date)

    async def test_changed_date_gets_second_reminder_same_date_does_not(self):
        target=date.today()+timedelta(days=3)
        async with self.factory() as session:
            item=await Repository(session).get_tracked_item(self.item_id)
            item.next_air_date=target+timedelta(days=10)
            await session.commit()
        async def set_date(value):
            await process_setdate_btn(self.callback(data='setdate:'+str(self.item_id)),self.state)
            await process_date_input(self.message(text=value.strftime('%d.%m.%Y')),self.state)
        await set_date(target)
        await check_reminders_job(self.bot,self.factory)
        await set_date(target)
        await check_reminders_job(self.bot,self.factory)
        self.assertEqual(self.bot.send_message.await_count,1)
        self.assertIn(target.strftime('%d.%m.%Y'),self.bot.send_message.call_args.args[1])
        await set_date(target+timedelta(days=1))
        class Tomorrow(date):
            @classmethod
            def today(cls):return date.today()+timedelta(days=1)
        with patch('bot.db.repositories.date',Tomorrow):
            await check_reminders_job(self.bot,self.factory)
            await check_reminders_job(self.bot,self.factory)
        self.assertEqual(self.bot.send_message.await_count,2)

    async def test_two_publishers_and_repeat_call_send_once(self):
        async with self.factory() as session:
            post=await Repository(session).create_channel_post('Test','claim-test','daily_digest',post_type='daily_digest',post_text='Test',status='pending')
            await session.commit();ident=post.id
        first=ChannelPublisher(self.factory,self.settings,self.bot)
        second=ChannelPublisher(self.factory,self.settings,self.bot)
        await asyncio.gather(first.publish_post_by_id(ident),second.publish_post_by_id(ident))
        self.assertTrue(await second.publish_post_by_id(ident))
        self.assertEqual(self.bot.send_message.await_count,1)
        async with self.factory() as session:
            self.assertEqual((await Repository(session).get_channel_post(ident)).status,'published')

    async def test_uncertain_send_failure_is_not_automatically_retried(self):
        async with self.factory() as session:
            repo=Repository(session)
            post=await repo.create_channel_post('Test','failed-test','daily_digest',post_type='daily_digest',post_text='Test',status='pending')
            await session.commit();ident=post.id
        publisher=ChannelPublisher(self.factory,self.settings,self.bot)
        self.bot.send_message.side_effect=RuntimeError('Transport interrupted')
        self.assertFalse(await publisher.publish_post_by_id(ident))
        self.assertEqual(await publisher.publish_pending_queue(),0)
        self.assertFalse(await publisher.publish_post_by_id(ident))
        self.assertEqual(self.bot.send_message.await_count,1)

    async def test_channel_filter_matches_site_and_keeps_anime(self):
        target=date.today()
        local=dict(title='Локальный фильм',overview='Описание',original_language='ja',production_countries=[{'iso_3166_1':'JP'}],vote_count=12,vote_average=6.5,popularity=16,release_date=target.isoformat())
        anime=dict(local,title='Популярное аниме',genres=[{'id':16}],vote_count=656,vote_average=8.6,popularity=118)
        self.tmdb.get_movie_details=AsyncMock(side_effect=[local,anime])
        publisher=ChannelPublisher(self.factory,self.settings,self.bot,self.tmdb)
        items=await publisher.enrich_digest_items([dict(media_type='movie',tmdb_id=1),dict(media_type='movie',tmdb_id=2)],target,target,True)
        self.assertEqual([i['tmdb_id'] for i in items],[2])

    async def test_privacy_requires_fresh_confirmation_and_preserves_other_users(self):
        async with self.factory() as session:
            repo=Repository(session);item=await repo.get_tracked_item(self.item_id)
            await repo.log_notification(item.id,'reminder','Test')
            await repo.create_shared_watchlist(item.user_id,[item])
            session.add(AnalyticsEvent(telegram_id=101,event_name='test'))
            await session.commit()
        cb=self.callback(data='privacy_delete_confirm:forged')
        await confirm_deletion(cb,self.state)
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(User)),2)
        await request_deletion(self.callback(),self.state)
        self.data['delete_time']=time.time()-601
        await confirm_deletion(self.callback(data='privacy_delete_confirm:'+self.data['delete_nonce']),self.state)
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(User)),2)
        await cancel_deletion(self.callback(),self.state)
        self.assertEqual(self.data,{})
        await request_deletion(self.callback(),self.state)
        nonce=self.data['delete_nonce']
        await confirm_deletion(self.callback(202,'privacy_delete_confirm:'+nonce),self.state)
        await confirm_deletion(self.callback(data='privacy_delete_confirm:'+nonce),self.state)
        async with self.factory() as session:
            self.assertEqual(list(await session.scalars(select(User.telegram_id))),[202])
            self.assertEqual(await session.scalar(select(func.count()).select_from(TrackedItem)),1)
            for table in (NotificationLog,SharedWatchlist,AnalyticsEvent):
                self.assertEqual(await session.scalar(select(func.count()).select_from(table)),0)

    async def test_help_and_privacy_deep_links_open_actual_controls(self):
        msg=self.message()
        for payload in ('help','privacy'):
            await cmd_start(msg,CommandObject(prefix='/',command='start',args=payload))
        self.assertEqual(msg.answer.await_count,2)
        self.assertIn('Удалить мои данные',str(msg.answer.call_args.kwargs['reply_markup']))


class ServiceCopyTests(unittest.TestCase):
    def test_moscow_date_and_unique_event_titles_preserve_article_urls(self):
        self.assertEqual(stamp('2026-10-05T21:54:24+00:00'),['06','10','2026'])
        row=dict(slug='stable-url',title='«Сериал»: изменился статус проекта',summary='TMDB',body='[]',fingerprint='tmdb:tv:1:status:In Production')
        self.assertNotEqual(public_article(row)['title'],public_article(dict(row,fingerprint='tmdb:tv:1:status:Released'))['title'])
        self.assertEqual(public_article(row)['slug'],'stable-url')
        self.assertNotIn('TMDB',json.dumps(public_article(row),ensure_ascii=False))

    def test_service_pages_offer_real_help_and_no_internal_selection_rules(self):
        cfg=config('unused.db')
        for html in (about(cfg),help_page(cfg),privacy(cfg)):
            self.assertEqual(html.count('<h1>'),1)
            self.assertNotIn('50 выбранных',html)
            self.assertNotIn('автоматическая редакция',html)
            self.assertIn('/help',html)
            self.assertIn('/privacy',html)
        self.assertIn('?start=help',help_page(cfg))
        self.assertIn('?start=privacy',privacy(cfg))
