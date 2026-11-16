import asyncio
import json
import logging
import signal
from pathlib import Path
from bot.db.engine import create_db_engine, get_session_factory, init_db
from bot.services.tmdb import TMDBClient
from bot.services.vk_client import VKApiError
from max_bot.state import StateManager
from vk_bot.config import VKBotSettings
from vk_bot.client import VKBotClient
from vk_bot.dispatcher import VKBotDispatcher
from vk_bot.handlers import VKBotHandlers
from vk_bot.scheduler import setup_scheduler

logger = logging.getLogger(__name__)


class PollState:
    def __init__(self, path):
        self.path = Path(path)
        try: self.data = json.loads(self.path.read_text())
        except (OSError, ValueError): self.data = {'ts':None, 'seen':[]}

    def save(self, ts, event=None):
        self.data['ts'] = ts
        if event: self.data['seen'] = (self.data['seen'] + [event])[-1000:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data))
        temp.replace(self.path)


async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    settings = VKBotSettings.from_env()
    engine = create_db_engine(settings.VK_DATABASE_URL)
    tmdb = TMDBClient(settings.TMDB_API_KEY, base_url=settings.TMDB_BASE_URL)
    client = VKBotClient(settings.VK_BOT_TOKEN, settings.VK_BOT_GROUP_ID)
    scheduler = None
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
        except (NotImplementedError, RuntimeError): pass
    state = PollState('data/vk_bot_poll.json')
    Path('data/vk_bot_ready.json').unlink(missing_ok=True)
    try:
        await init_db(engine)
        factory = get_session_factory(engine)
        await client.api_call('groups.setSettings', {'group_id':client.group_id,'messages':1,'bots_capabilities':1,'bots_start_button':1})
        await client.api_call('groups.setLongPollSettings', {'group_id':client.group_id,'enabled':1,'api_version':'5.199','message_new':1,'message_event':1})
        server = await client.api_call('groups.getLongPollServer', {'group_id':client.group_id})
        ts = state.data.get('ts') or server['ts']
        handlers = VKBotHandlers(client, factory, tmdb, settings, StateManager())
        dispatcher = VKBotDispatcher(handlers, client.group_id)
        scheduler = setup_scheduler(client, factory, tmdb, settings)
        scheduler.start()
        Path('data/vk_bot_ready.json').write_text(json.dumps({'group_id':client.group_id,'ready':True}))
        logger.info('VK bot ready: community %s; polling and reminders active', client.group_id)
        while not stopped.is_set():
            try:
                result = await client.poll(server['server'], server['key'], ts)
                failed = result.get('failed')
                if failed == 1:
                    ts = result['ts']; state.save(ts); continue
                if failed in (2,3):
                    server = await client.api_call('groups.getLongPollServer', {'group_id':client.group_id})
                    if failed == 3: ts = server['ts']
                    continue
                if failed: raise RuntimeError('Unknown Long Poll response')
                for update in result.get('updates', []):
                    event = update.get('event_id')
                    if not event and update.get('type') == 'message_new':
                        message = update.get('object', {}).get('message', {})
                        event = f"message:{message.get('peer_id')}:{message.get('id')}"
                    if not event and update.get('type') == 'message_event':
                        obj = update.get('object', {})
                        event = f"callback:{obj.get('user_id')}:{obj.get('event_id')}"
                    if event in state.data['seen']: continue
                    try:
                        await dispatcher.process_update(update)
                    except VKApiError as exc:
                        if exc.error_code not in (901, 902, 917): raise
                        logger.info('VK message unavailable for this peer (%s)', exc.error_code)
                    state.save(ts, event)
                ts = result['ts']; state.save(ts)
                Path('data/vk_bot_ready.json').touch()
            except asyncio.CancelledError: raise
            except Exception as exc:
                logger.warning('VK polling/dispatch retry (%s)', type(exc).__name__)
                try: await asyncio.wait_for(stopped.wait(), timeout=3)
                except asyncio.TimeoutError: pass
    finally:
        Path('data/vk_bot_ready.json').unlink(missing_ok=True)
        if scheduler: scheduler.shutdown(wait=False)
        await client.close(); await tmdb.close(); await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
