"""Check public wall-image document storage and repair the existing test post if allowed."""
from pathlib import Path
import subprocess

CODE = r'''
import asyncio, json
from pathlib import Path
from datetime import date
import aiohttp
from bot.config import Settings
from bot.services.vk_client import VKClient
from bot.services.vk_spintax import format_vk_post

async def main():
    s = Settings.from_env()
    client = VKClient(s.VK_ACCESS_TOKEN, s.VK_GROUP_ID)
    try:
        item = json.loads(Path('website/catalog_seed.json').read_text())['titles'][1]
        url = item.get('image') or item['poster']
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
            async with http.get(url) as response:
                response.raise_for_status()
                image = await response.read()
            server = await client.api_call('docs.getWallUploadServer',{'group_id':client.group_id})
            form = aiohttp.FormData()
            form.add_field('file',image,filename='kinojdun-cover.jpg',content_type='image/jpeg')
            async with http.post(server['upload_url'],data=form) as response:
                response.raise_for_status()
                upload = await response.json(content_type=None)
        if not upload.get('file'):
            print('Document uploader did not accept the image',flush=True)
            return
        saved = await client.api_call('docs.save',{'file':upload['file'],'title':item['title']+' — обложка'})
        doc = saved[0] if isinstance(saved,list) else saved.get('doc',{})
        ident = str(doc['owner_id']) + '_' + str(doc['id'])
        attachment = 'doc'+ident+('_'+doc['access_key'] if doc.get('access_key') else '')
        preview = bool(doc.get('preview',{}).get('photo',{}).get('sizes'))
        print(json.dumps({'document_id':ident,'image_preview':preview,'type':doc.get('type')}),flush=True)
        readback = await client.api_call('docs.getById',{'docs':ident})
        print(json.dumps({'public_document_readable':bool(readback)}),flush=True)
        if not preview or not readback:
            return
        post = format_vk_post(title=item['title'],media_type=item['media_type'],event_type='announced',
            season_number=item.get('season'),air_date=date.fromisoformat(item['release_date']),
            genres=item.get('genres',[]),overview=item.get('overview'),site_url=s.SITE_BASE_URL,
            item_id=item['id'],link_in_comment=False,create_poll=False)
        try:
            await client.edit_post(10,post['text'],[attachment])
            print(json.dumps({'existing_post_updated':10,'url':'https://vk.ru/wall-242059739_10'}),flush=True)
        except Exception as error:
            print('Existing post unchanged:',type(error).__name__,str(error),flush=True)
    except Exception as error:
        print(type(error).__name__,str(error),flush=True)
    finally:
        await client.close()

asyncio.run(main())
'''

if __name__ == '__main__':
    result = subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
        'root@62.217.176.12','docker exec -i kinozhdun_bot python -'],
        input=CODE,text=True,encoding='utf-8',capture_output=True)
    print(result.stdout)
    if result.returncode:
        print(result.stderr)
    raise SystemExit(result.returncode)
