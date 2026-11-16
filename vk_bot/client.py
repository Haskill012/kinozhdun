import asyncio
import json
import logging
import secrets
import time
from html.parser import HTMLParser
import aiohttp
from bot.services.vk_client import VKClient, VKApiError

logger = logging.getLogger(__name__)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.link = None

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')
        if tag == 'a':
            self.link = dict(attrs).get('href')

    def handle_endtag(self, tag):
        if tag == 'a' and self.link:
            self.parts.append(' (' + self.link + ')')
            self.link = None

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(text):
    parser = PlainText()
    parser.feed(text or '')
    return ''.join(parser.parts)


def vk_keyboard(attachments):
    """Convert the shared bot keyboard into native VK callback/link buttons."""
    rows = []
    for attachment in attachments or []:
        if attachment.get('type') != 'inline_keyboard':
            continue
        for row in attachment.get('payload', {}).get('buttons', []):
            buttons = []
            for button in row:
                label = button.get('text', '')[:40]
                if button.get('type') == 'link':
                    action = {'type': 'open_link', 'label': label, 'link': button['url']}
                    buttons.append({'action': action})
                elif button.get('type') == 'callback':
                    action = {'type': 'callback', 'label': label,
                              'payload': json.dumps({'action': button['payload']}, ensure_ascii=False)}
                    buttons.append({'action': action, 'color': 'secondary'})
            if buttons:
                rows.append(buttons)
    if len(rows) > 10 or any(len(row) > 5 for row in rows):
        raise ValueError('VK inline keyboard exceeds platform limits')
    return {'inline': True, 'buttons': rows} if rows else None


class VKBotClient(VKClient):
    def __init__(self, token, group_id, session=None):
        super().__init__(token, group_id, session=session)
        self._request_lock = asyncio.Lock()
        self._last_call = 0
        self._photos = {}

    async def api_call(self, method, params=None, token=None):
        # Serialize API calls and respect the community's request rate limit.
        async with self._request_lock:
            for attempt in range(4):
                await asyncio.sleep(max(0, .35 - (time.monotonic() - self._last_call)))
                self._last_call = time.monotonic()
                try:
                    return await super().api_call(method, params, token)
                except VKApiError as exc:
                    if exc.error_code not in (6, 10) or attempt == 3:
                        raise
                    await asyncio.sleep(attempt + 1)

    async def send_message(self, *, chat_id=None, user_id=None, text='', attachments=None, **kwargs):
        peer_id = chat_id or user_id
        if not peer_id:
            raise ValueError('VK peer_id is required')
        keyboard = vk_keyboard(attachments)
        photos = [a['payload']['token'] for a in attachments or [] if a.get('type') == 'image']
        message = plain_text(text)
        # Split on line boundaries and put the action keyboard on the last part.
        chunks = []
        while len(message) > 4000:
            end = message.rfind('\n', 0, 4000)
            if end < 1: end = 4000
            chunks.append(message[:end]); message = message[end:].lstrip('\n')
        chunks.append(message or '🍿')
        result = None
        for index, chunk in enumerate(chunks):
            params = {'peer_id': peer_id, 'random_id': secrets.randbelow(2**31 - 1) + 1,
                      'message': chunk, 'dont_parse_links': 1}
            if index == len(chunks) - 1:
                if keyboard: params['keyboard'] = json.dumps(keyboard, ensure_ascii=False)
                if photos: params['attachment'] = ','.join(photos)
            result = await self.api_call('messages.send', params)
        return result

    async def answer_callback(self, callback_id, notification=None, **kwargs):
        if not callback_id: return
        context = json.loads(callback_id)
        params = {key: context[key] for key in ('event_id', 'user_id', 'peer_id')}
        if notification:
            params['event_data'] = json.dumps({'type': 'show_snackbar', 'text': notification[:90]}, ensure_ascii=False)
        return await self.api_call('messages.sendMessageEventAnswer', params)

    async def upload_image_from_url(self, url):
        if url in self._photos: return self._photos[url]
        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                data = await response.read()
            server = await self.api_call('photos.getMessagesUploadServer', {})
            form = aiohttp.FormData()
            form.add_field('photo', data, filename='poster.jpg', content_type='image/jpeg')
            async with session.post(server['upload_url'], data=form) as response:
                response.raise_for_status()
                uploaded = await response.json(content_type=None)
            saved = await self.api_call('photos.saveMessagesPhoto', {k: uploaded[k] for k in ('photo', 'server', 'hash')})
            photo = saved[0]
            result = f"photo{photo['owner_id']}_{photo['id']}"
            if photo.get('access_key'): result += '_' + photo['access_key']
            self._photos[url] = result
            return result
        except Exception as exc:
            # Upload URLs contain credentials, so never log exception strings.
            logger.warning('VK poster unavailable (%s)', type(exc).__name__)
            return None

    async def poll(self, server, key, ts):
        session = await self._get_session()
        try:
            async with session.get(server, params={'act':'a_check','key':key,'ts':ts,'wait':25},
                                   timeout=aiohttp.ClientTimeout(total=35)) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Do not expose the Long Poll key in HTTP error URLs.
            raise RuntimeError('VK Long Poll transport failed') from None
