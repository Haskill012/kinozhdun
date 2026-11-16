"""Bounded upload of one catalogue poster; no tokens, arbitrary files or wall posts."""
import asyncio
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

MAX_IMAGE = 8 * 1024 * 1024


async def send_poster(session, url, image):
    fields = ('file1', 'photo') if 'bulk_upload' in urlsplit(url).path else ('photo', 'file1')
    summaries = []
    for field in fields:
        form = aiohttp.FormData()
        form.add_field(field, bytes(image), filename='poster.jpg', content_type='image/jpeg')
        async with session.post(url, data=form, allow_redirects=False) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(text='ВК не принял загрузку постера')
            raw = await response.content.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise web.HTTPBadGateway(text='Неожиданный ответ ВК')
            result = json.loads(raw)
        if not isinstance(result, dict):
            raise web.HTTPBadGateway(text='Неожиданный формат ответа ВК')
        if result.get('photo') and result['photo'] != '[]' and 'server' in result and 'hash' in result:
            return {key: result[key] for key in ('photo', 'server', 'hash')}
        # Report only known structural markers and numeric errors, never URL/hash/file secrets.
        markers = [key for key in ('photo', 'server', 'hash', 'files', 'error', 'error_code') if key in result]
        error = result.get('error', {})
        code = error.get('error_code') if isinstance(error, dict) else None
        code = result.get('error_code', code)
        summaries.append(field + ': ' + ','.join(markers) + (f' код {code}' if isinstance(code, int) else ''))
        # A files receipt may mean an actual successful upload; don't duplicate it or guess save parameters.
        if result.get('files'):
            break
    raise web.HTTPBadGateway(text='ВК не подтвердил загрузку фотографии (' + '; '.join(summaries) + ')')


def allowed_upload_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and not parsed.fragment
                and (parsed.hostname in ('pu.vk.com', 'pu.vk.ru')
                     or re.fullmatch(r'psv\d+\.userapi\.com', parsed.hostname or '') is not None))
    except ValueError:
        return False


def upload_check_handler(seed_path):
    lock = asyncio.Lock()
    last_upload = 0.0

    async def upload(request):
        nonlocal last_upload
        # This endpoint accepts only a VK upload capability and one fixed catalogue image.
        # It never receives a user/community access token and cannot publish a wall post.
        if request.content_length is None or request.content_length > 16384:
            raise web.HTTPBadRequest(text='Слишком большой запрос')
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest(text='Некорректный запрос')
        url = payload.get('upload_url') if isinstance(payload, dict) else None
        if not allowed_upload_url(url):
            raise web.HTTPBadRequest(text='Адрес загрузки ВК не поддерживается. Нужна проверка адреса без токенов.')
        if lock.locked() or time.monotonic() - last_upload < 10:
            raise web.HTTPTooManyRequests(text='Подождите 10 секунд перед повторной загрузкой')
        async with lock:
            last_upload = time.monotonic()
            item = next(t for t in json.loads(Path(seed_path).read_text(encoding='utf-8'))['titles']
                        if t.get('key') == 'tv:2734')
            source = item['poster']
            if not re.fullmatch(r'https://image\.tmdb\.org/t/p/w500/[A-Za-z0-9]+\.jpg', source):
                raise web.HTTPServiceUnavailable(text='Постер каталога недоступен')
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                    async with session.get(source, allow_redirects=False) as response:
                        if response.status != 200:
                            raise web.HTTPBadGateway(text='Не удалось получить постер')
                        image = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            image.extend(chunk)
                            if len(image) > MAX_IMAGE:
                                raise web.HTTPBadGateway(text='Постер слишком большой')
                    if not image.startswith(b'\xff\xd8\xff'):
                        raise web.HTTPBadGateway(text='Постер не является JPEG')
                    result = await send_poster(session, url, image)
                return web.json_response(result,
                                         headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex'})
            except web.HTTPException:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                # Never include signed upload URLs or API payloads in errors/logs.
                raise web.HTTPBadGateway(text='Ошибка передачи постера. Можно повторить проверку.')
    return upload
