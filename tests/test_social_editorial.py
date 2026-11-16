import unittest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, Mock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import Settings
from bot.db.models import Base, DzenPost, ChannelPost
from bot.services.channel import ChannelPublisher
from bot.services.dzen_delivery import DzenPublisher
from bot.services.social_editorial import event_copy, resolve_catalog_item, catalog_candidates
from bot.scheduler.jobs import setup_scheduler


class EditorialTests(unittest.IsolatedAsyncioTestCase):
    def test_past_film_has_no_availability_or_future_promise(self):
        parts, past = event_copy('Фильм', air_date=date(2000,1,1), today=date(2026,10,6), tmdb_id=123)
        self.assertTrue(past)
        text='\n'.join(parts)
        self.assertIn('Уже вышло', text)
        self.assertNotIn('доступен для просмотра', text)
        self.assertIn('https://www.themoviedb.org/movie/123', text)

    def test_series_without_event_detail_does_not_invent_premiere(self):
        parts,_=event_copy('Сериал', 'tv', air_date=date(2026,10,8))
        text='\n'.join(parts)
        self.assertIn('Ближайшая дата в каталоге',text)
        self.assertNotIn('премьера',text.casefold())

    async def test_actual_episode_overrides_the_seed_season_and_date(self):
        tmdb=Mock(get_tv_details=AsyncMock(return_value={
            'title':'Сериал', 'genres':[], 'next_episode_to_air':{
                'air_date':'2026-10-08','season_number':28,'episode_number':3}}))
        item=await resolve_catalog_item({'id':2734,'title':'Сериал','media_type':'tv',
            'release_date':'2026-10-06','season':1},tmdb,date(2026,10,6))
        self.assertEqual((item['event_type'],item['season'],item['episode_number'],item['air_date']),
                         ('episode_date',28,3,date(2026,10,8)))

    async def test_unavailable_metadata_prevents_scheduled_publication(self):
        tmdb=Mock(get_movie_details=AsyncMock(return_value={}))
        self.assertIsNone(await resolve_catalog_item({'id':1,'title':'Фильм','media_type':'movie'},tmdb))

    def test_near_release_precedes_far_future_and_old_seed_order(self):
        candidates=catalog_candidates([
            {'id':1,'title':'Старый','media_type':'movie','release_date':'2026-01-01'},
            {'id':2,'title':'Ближайший','media_type':'movie','release_date':'2026-10-08'},
            {'id':3,'title':'Далёкий','media_type':'movie','release_date':'2028-01-01'}],date(2026,10,6))
        self.assertEqual([i['id'] for i in candidates],[2,1])

    def test_daytime_cron_and_sync_has_no_second_publisher(self):
        settings=Settings(TELEGRAM_BOT_TOKEN='test',TMDB_API_KEY='test',VK_POSTING_ENABLED=True,
                          VK_AUTO_PUBLISH=True,DZEN_POSTING_ENABLED=True,DZEN_SYNC_MODE='telegram_sync')
        scheduler=setup_scheduler(Mock(),Mock(),Mock(),settings)
        self.assertIsNone(scheduler.get_job('check_dzen_feed'))
        now=datetime(2026,10,6,0,tzinfo=timezone.utc)
        vk=scheduler.get_job('check_vk_feed').trigger.get_next_fire_time(None,now)
        self.assertEqual(vk.astimezone(timezone.utc),datetime(2026,10,6,15,30,tzinfo=timezone.utc))
        self.assertEqual(scheduler.get_job('check_vk_feed').max_instances,1)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory=async_sessionmaker(self.engine,expire_on_commit=False)
        self.settings=Settings(TELEGRAM_BOT_TOKEN='test',TMDB_API_KEY='test',
                              TELEGRAM_CHANNEL_ID='@test',CHANNEL_POSTING_ENABLED=True,
                              CHANNEL_AUTO_PUBLISH=True,DZEN_POSTING_ENABLED=True)
        self.bot=Mock(send_message=AsyncMock(return_value=Mock(message_id=91)),send_photo=AsyncMock())

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_sync_tracks_original_message_and_never_sends_an_extra_post(self):
        channel=ChannelPublisher(self.factory,self.settings,self.bot)
        await channel.process_update_for_channel(123,'movie','announced','Фильм',air_date=date(2027,1,1))
        dzen=DzenPublisher(self.factory,self.settings,bot=self.bot)
        self.assertIsNone(await dzen.publish_event('Другой фильм',tmdb_id=456,force=True))
        self.assertIsNone(await dzen.create_daily_digest())
        self.assertEqual(self.bot.send_message.await_count,1)
        self.bot.send_photo.assert_not_awaited()
        async with self.factory() as session:
            rows=(await session.scalars(select(DzenPost))).all()
            self.assertEqual(len(rows),1)
            self.assertEqual((rows[0].status,rows[0].dzen_publication_id),('forwarded','tg_sync:91'))

    async def test_direct_mode_cannot_report_an_emulated_publication(self):
        self.settings.DZEN_SYNC_MODE='direct'
        publisher=DzenPublisher(self.factory,self.settings,bot=self.bot)
        result=await publisher._send_to_dzen('Фильм','Текст')
        self.assertFalse(result['success'])
        self.assertNotIn('publication_id',result)
        self.bot.send_message.assert_not_awaited()

    async def test_claim_blocks_repeated_delivery_even_without_native_publication_id(self):
        self.settings.DZEN_SYNC_MODE='webhook'
        publisher=DzenPublisher(self.factory,self.settings)
        publisher._send_to_dzen=AsyncMock(return_value={'success':True,'delivery_status':'submitted'})
        post=await publisher.publish_event('Фильм',tmdb_id=234)
        self.assertEqual(post.status,'submitted')
        self.assertIsNone(post.dzen_publication_id)
        self.assertFalse(await publisher._deliver_record(post.id))
        self.assertIsNone(await publisher.publish_event('Фильм',tmdb_id=234))
        publisher._send_to_dzen.assert_awaited_once()

    async def test_failed_photo_transport_does_not_create_a_text_duplicate(self):
        from aiogram.exceptions import TelegramNetworkError
        from aiogram.methods import SendPhoto
        self.bot.send_photo.side_effect=TelegramNetworkError(SendPhoto(chat_id='@test',photo='https://example.com/p.jpg'),'timeout')
        publisher=ChannelPublisher(self.factory,self.settings,self.bot)
        with self.assertRaises(TelegramNetworkError):
            await publisher._send_post_to_telegram('@test','Text','/photo.jpg',None)
        self.bot.send_message.assert_not_awaited()

    async def test_expired_digest_is_not_published_from_queue(self):
        from unittest.mock import patch
        async with self.factory() as session:
            post=ChannelPost(post_type='daily_digest',event_type='daily_digest',title='Yesterday',post_text='Outdated dates',
                             status='pending',content_hash='expired-digest',
                             created_at=datetime(2026,10,5,12))
            session.add(post);await session.commit();ident=post.id
        publisher=ChannelPublisher(self.factory,self.settings,self.bot)
        publisher.can_publish_now=AsyncMock(return_value=True)
        publisher.publish_post_by_id=AsyncMock()
        with patch('bot.services.channel.moscow_today',return_value=date(2026,10,6)):
            self.assertEqual(await publisher.publish_pending_queue(),0)
        publisher.publish_post_by_id.assert_not_awaited()
        async with self.factory() as session:
            self.assertEqual((await session.get(ChannelPost,ident)).status,'expired')
