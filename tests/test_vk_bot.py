import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from bot.db.engine import create_db_engine, get_session_factory, init_db
from bot.db.repositories import Repository
from max_bot.state import StateManager
from max_bot.keyboards import main_menu_keyboard
from vk_bot.client import VKBotClient, plain_text, vk_keyboard
from vk_bot.config import VKBotSettings
from vk_bot.dispatcher import VKBotDispatcher, action_payload
from vk_bot.handlers import VKBotHandlers
from vk_bot.scheduler import setup_scheduler
from vk_bot.__main__ import PollState
from max_bot.scheduler import check_reminders_job
from website.views import bot_dropdown, vk_bot_link


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_buttons_html_and_message_splitting(self):
        client = VKBotClient('fake', 242087163)
        client.api_call = AsyncMock(return_value=123)
        await client.send_message(user_id=77, text='<b>Привет &amp; кино</b>\n'+'А'*4100, attachments=main_menu_keyboard())
        self.assertEqual(client.api_call.await_count, 3)
        first, middle, second = client.api_call.call_args_list
        self.assertIn('Привет & кино', first.args[1]['message'])
        self.assertNotIn('keyboard', first.args[1])
        keyboard = json.loads(second.args[1]['keyboard'])
        self.assertTrue(keyboard['inline'])
        self.assertEqual(keyboard['buttons'][0][0]['action']['type'], 'callback')
        self.assertEqual(json.loads(keyboard['buttons'][0][0]['action']['payload']), {'action':'menu:search'})
        self.assertEqual(second.args[1]['peer_id'], 77)
        self.assertGreater(second.args[1]['random_id'], 0)
        self.assertEqual(plain_text('<a href="https://kinojdun.ru">Сайт</a>'), 'Сайт (https://kinojdun.ru)')

    async def test_native_callback_ack(self):
        client=VKBotClient('fake',1);client.api_call=AsyncMock()
        await client.answer_callback(json.dumps({'event_id':'event','user_id':7,'peer_id':7}))
        client.api_call.assert_awaited_once_with('messages.sendMessageEventAnswer', {'event_id':'event','user_id':7,'peer_id':7})

    async def test_dispatch_start_deep_link_and_callback(self):
        handlers=AsyncMock(); dispatcher=VKBotDispatcher(handlers,242087163)
        update={'type':'message_new','group_id':242087163,'object':{'message':{'from_id':7,'peer_id':7,'text':'Начать','ref':'c_tv_42'}}}
        await dispatcher.process_update(update)
        handlers.handle_start.assert_awaited_once_with(7,7,None,None,payload='c_tv_42')
        handlers.reset_mock();update['object']['message'].pop('ref')
        await dispatcher.process_update(update)
        handlers.dispatch_message.assert_awaited_once_with(7,7,None,None,'/start')
        handlers.reset_mock();update={'type':'message_event','group_id':242087163,'object':{'user_id':7,'peer_id':7,'event_id':'evt','payload':{'action':'menu:list'}}}
        await dispatcher.process_update(update)
        self.assertEqual(handlers.dispatch_callback.call_args.args[-1],'menu:list')
        handlers.reset_mock();update['object']['peer_id']=2000000001
        await dispatcher.process_update(update)
        handlers.dispatch_callback.assert_not_awaited()
        self.assertEqual(action_payload('{bad'), '')
        self.assertEqual(action_payload({'action':{}}), '')

    async def test_web_links_and_cursor_persistence(self):
        url=vk_bot_link('https://t.me/kinojdun_bot?start=c_tv_42')
        self.assertEqual(url,'https://vk.me/club242087163?ref=c_tv_42&ref_source=kinojdun')
        markup=bot_dropdown('Ждать','https://t.me/kinojdun_bot?start=c_movie_42','https://max.ru/bot')
        self.assertIn('bot-dropdown-vk',markup)
        self.assertIn('ref=c_movie_42&amp;ref_source=kinojdun',markup)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cursor.json';state=PollState(path);state.save('55','event123')
            restored=PollState(path)
            self.assertEqual(restored.data, {'ts':'55','seen':['event123']})


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_db_engine('sqlite+aiosqlite:///:memory:');await init_db(self.engine)
        self.factory=get_session_factory(self.engine)
        self.client=AsyncMock();self.client.upload_image_from_url.return_value=None
        self.tmdb=AsyncMock()
        self.tmdb.get_movie_details.return_value={'id':42,'title':'Дюна','release_date':(datetime.date.today()+datetime.timedelta(days=30)).isoformat()}
        self.settings=VKBotSettings('fake','fake')
        self.handlers=VKBotHandlers(self.client,self.factory,self.tmdb,self.settings,StateManager())
        await self.handlers._ensure_user(7,'Имя',None)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_search_track_date_and_remove(self):
        self.tmdb.search_multi.return_value=[{'id':42,'title':'Дюна','media_type':'movie'}]
        await self.handlers.dispatch_message(7,7,None,None,'Дюна')
        self.tmdb.search_multi.assert_awaited_once()
        await self.handlers.dispatch_callback('',7,7,'confirm_track:movie:42')
        async with self.factory() as session:
            items=await Repository(session).get_user_items(7)
            self.assertEqual(len(items),1);item_id=items[0].id
        await self.handlers.handle_confirm_track(7,7,'movie',42)
        async with self.factory() as session:
            self.assertEqual(len(await Repository(session).get_user_items(7)),1)
        await self.handlers.handle_setdate_prompt(7,7,item_id)
        await self.handlers.handle_date_input(7,7,'25.12.2027')
        async with self.factory() as session:
            self.assertEqual((await Repository(session).get_tracked_item(item_id)).custom_date,datetime.date(2027,12,25))
        await self.handlers.dispatch_callback('',7,7,f'confirm_remove:{item_id}')
        async with self.factory() as session:
            self.assertEqual(await Repository(session).get_user_items(7),[])

    async def test_other_users_cannot_read_edit_or_remove(self):
        await self.handlers.handle_confirm_track(7,7,'movie',42)
        async with self.factory() as session:
            item_id=(await Repository(session).get_user_items(7))[0].id
        await self.handlers._ensure_user(8,None,None)
        for method in ('handle_item_details','handle_setdate_prompt','handle_remove_confirm_prompt'):
            await getattr(self.handlers,method)(8,8,item_id)
            self.assertIn('не найден',self.client.send_message.call_args.kwargs['text'])
        await self.handlers.handle_confirm_remove(8,8,item_id)
        async with self.factory() as session:
            self.assertEqual(len(await Repository(session).get_user_items(7)),1)

    async def test_all_fifty_projects_are_accessible_by_pages(self):
        async with self.factory() as session:
            repo=Repository(session);user=await repo.get_or_create_user(7,None,None)
            for index in range(50):
                await repo.add_tracked_item(user.id,index+1,'movie',f'Фильм {index}',None,None,None,None,None,'https://kinojdun.ru')
            await session.commit()
        seen=set()
        for page in range(7):
            await self.handlers.show_items(7,7,'details',page)
            keyboard=vk_keyboard(self.client.send_message.call_args.kwargs['attachments'])
            self.assertLessEqual(len(keyboard['buttons']),10)
            for row in keyboard['buttons']:
                for button in row:
                    action=json.loads(button['action']['payload'])['action']
                    if action.startswith('details:'):seen.add(action)
        self.assertEqual(len(seen),50)

    async def test_reminder_goes_to_vk_and_is_deduplicated(self):
        async with self.factory() as session:
            repo=Repository(session);user=await repo.get_or_create_user(7,None,None)
            await repo.add_tracked_item(user.id,42,'movie','Дюна',None,None,None,None,datetime.date.today()+datetime.timedelta(days=3),'https://kinojdun.ru')
            await session.commit()
        await check_reminders_job(self.client,self.factory,self.settings)
        self.client.send_message.assert_awaited_once()
        self.assertEqual(self.client.send_message.call_args.kwargs['user_id'],7)
        await check_reminders_job(self.client,self.factory,self.settings)
        self.assertEqual(self.client.send_message.await_count,1)
        scheduler=setup_scheduler(self.client,self.factory,self.tmdb,self.settings)
        self.assertEqual({job.id for job in scheduler.get_jobs()},{'vk_updates','vk_reminders','vk_episodes'})
