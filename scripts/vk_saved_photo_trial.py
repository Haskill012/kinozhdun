"""Publish at most one trial using the photo ID returned by our Mini App."""
from pathlib import Path
import subprocess

REMOTE = r'''
import asyncio, json, hashlib
from datetime import date
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import Settings
from bot.db.models import Base
from bot.db.repositories import Repository
from bot.services.vk_client import VKClient
from bot.services.vk_spintax import format_vk_post

async def main():
    settings = Settings.from_env()
    assert abs(settings.VK_GROUP_ID) == 242059739
    attachment = 'photo21432243_457248089'
    fingerprint = hashlib.sha256(('miniapp-wall-trial:' + attachment).encode()).hexdigest()
    item = next(i for i in json.loads(Path('website/catalog_seed.json').read_text())['titles'] if i['key'] == 'tv:2734')
    text = format_vk_post(title=item['title'], media_type='tv', event_type='announced',
        season_number=item.get('season'), air_date=date.fromisoformat(item['release_date']),
        genres=item.get('genres'), overview=item.get('overview'), item_id=2734,
        site_url=settings.SITE_BASE_URL, create_poll=False, link_in_comment=False)['text']
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        repo = Repository(session)
        if await repo.is_vk_post_exists(fingerprint):
            print('Trial already attempted; no second post created.')
            await engine.dispose()
            return
        await repo.record_vk_post(fingerprint, item['title'], 'miniapp_photo_trial',
                                 tmdb_id=2734, media_type='tv', status='verification_pending')
        await session.commit()
    client = VKClient(settings.VK_ACCESS_TOKEN, settings.VK_GROUP_ID)
    try:
        response = await client.api_call('wall.post', {
            'owner_id': -242059739, 'from_group': 1, 'message': text,
            'attachments': attachment, 'guid': fingerprint,
        })
        post_id = response.get('post_id')
        if not isinstance(post_id, int) or post_id <= 0:
            raise RuntimeError('VK returned no confirmed post ID')
        async with factory() as session:
            await Repository(session).record_vk_post(fingerprint, item['title'], 'miniapp_photo_trial',
                tmdb_id=2734, media_type='tv', vk_post_id=post_id, status='verification_pending')
            await session.commit()
        print(json.dumps({'post_id': post_id, 'attachment_requested': attachment,
            'url': f'https://vk.ru/wall-242059739_{post_id}', 'photo_verified': False}))
    except Exception as error:
        # Keep the pending guard even on ambiguous network failures; don't blindly repost.
        print(json.dumps({'trial_error': str(error), 'automatic_retry': False}))
    finally:
        await client.close()
        await engine.dispose()

asyncio.run(main())
'''

if __name__ == '__main__':
    subprocess.run(['ssh', '-i', str(Path.home() / '.ssh/kinojdun_codex_deploy'),
                    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@62.217.176.12',
                    'docker exec -i kinozhdun_bot python -'],
                   input=REMOTE, text=True, encoding='utf-8', check=True)
