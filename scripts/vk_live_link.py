"""Verify production metadata and publish one catalogue link card through the real publisher."""
from pathlib import Path
import subprocess

REMOTE = r'''
import asyncio, json
from html.parser import HTMLParser
from urllib.request import urlopen
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import Settings
from bot.db.models import Base
from bot.services.vk_publisher import VKPublisher

class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('property'):
            self.meta[attrs['property']] = attrs.get('content')

async def main():
    settings = Settings.from_env()
    assert settings.VK_ATTACHMENT_MODE == 'photo'
    item = json.loads(Path('website/catalog_seed.json').read_text())['titles'][1]
    url = settings.SITE_BASE_URL.rstrip('/') + '/title/' + item['media_type'] + '/' + str(item['id'])
    with urlopen(url, timeout=30) as response:
        assert response.status == 200
        page = response.read().decode()
    parser = Metadata()
    parser.feed(page)
    cover = parser.meta.get('og:image')
    assert cover and parser.meta.get('og:title') and parser.meta.get('og:description')
    with urlopen(cover, timeout=30) as response:
        assert response.status == 200 and response.headers.get_content_type().startswith('image/')
        assert len(response.read(1024)) > 100
    print(json.dumps({'page':url,'title':item['title'],'release_date':item.get('release_date'),
                      'season':item.get('season'),'og_title':parser.meta['og:title'],'cover':cover,
                      'metadata_and_image_checked':True},ensure_ascii=False),flush=True)
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    publisher = VKPublisher(async_sessionmaker(engine, expire_on_commit=False), settings)
    try:
        release = date.fromisoformat(item['release_date']) if item.get('release_date') else None
        event = 'announced' if release and release >= datetime.now(ZoneInfo('Europe/Moscow')).date() else 'catalog_feature'
        post_id = await publisher.publish_event(title=item['title'], media_type=item['media_type'],
            event_type=event, tmdb_id=item['id'], season_number=item.get('season'), air_date=release,
            genres=item.get('genres',[]), overview=item.get('overview'), network=item.get('network'),
            poster_path=cover)
        print(json.dumps({'post_id':post_id,'url':f'https://vk.ru/wall-{abs(settings.VK_GROUP_ID)}_{post_id}' if post_id else None}),flush=True)
        if post_id:
            try:
                result = await publisher.vk_client.api_call('wall.getById', {'posts':f'-{abs(settings.VK_GROUP_ID)}_{post_id}'})
                print(json.dumps({'readback':result},ensure_ascii=False),flush=True)
            except Exception as error:
                print('Readback unavailable:',type(error).__name__,str(error),flush=True)
    finally:
        await publisher.close()
        await engine.dispose()

asyncio.run(main())
'''

if __name__ == '__main__':
    command = ['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),
               '-o','BatchMode=yes','root@62.217.176.12',
               'cd /root/kinozhdun && docker exec -i kinozhdun_bot python -']
    result = subprocess.run(command,input=REMOTE,text=True,encoding='utf-8',capture_output=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    raise SystemExit(result.returncode)
