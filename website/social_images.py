"""Serve TMDB social previews from our domain with a bounded disk cache."""
import logging
from pathlib import Path
import re
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

NAME = re.compile(r"[A-Za-z0-9]+\.jpg\Z")


def social_image_url(base, source):
    parsed = urlsplit(source or '')
    name = parsed.path.rsplit('/', 1)[-1]
    if parsed.scheme == 'https' and parsed.netloc == 'image.tmdb.org' and parsed.path.startswith('/t/p/') and NAME.fullmatch(name):
        return base.rstrip('/') + '/social-image/' + name
    return source


def image_handler(cache_dir):
    cache_dir = Path(cache_dir)

    async def serve(request):
        name = request.match_info['name']
        if not NAME.fullmatch(name):
            raise web.HTTPNotFound()
        path = cache_dir / name
        if not path.exists():
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    async with session.get('https://image.tmdb.org/t/p/w1280/' + name, allow_redirects=False) as response:
                        if response.status != 200:
                            raise web.HTTPBadGateway()
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            data.extend(chunk)
                            if len(data) > 8 * 1024 * 1024:
                                raise web.HTTPBadGateway()
                if not data.startswith(b'\xff\xd8\xff'):
                    raise web.HTTPBadGateway()
                cache_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except web.HTTPException:
                raise
            except Exception:
                logging.getLogger(__name__).warning('Social preview download failed: %s', name)
                raise web.HTTPBadGateway()
        return web.FileResponse(path, headers={'Cache-Control': 'public, max-age=86400'})

    return serve
