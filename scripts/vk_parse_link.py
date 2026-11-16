"""Read-only VK link parser diagnostic, credentials stay in the container."""
from pathlib import Path
import subprocess

CODE = r'''
import asyncio, json
from bot.config import Settings
from bot.services.vk_client import VKClient
async def main():
    s = Settings.from_env()
    client = VKClient(s.VK_ACCESS_TOKEN,s.VK_GROUP_ID)
    try:
        try:
            r = await client.api_call('photos.getMessagesUploadServer')
            print(json.dumps({'photo_storage_available':bool(r.get('upload_url'))}),flush=True)
        except Exception as error:
            print(type(error).__name__,str(error),flush=True)
        for url in ['https://kinojdun.ru/title/tv/2734','https://kinojdun.ru/']:
            try:
                r = await client.api_call('wall.parseAttachedLink',{'links':json.dumps([{'url':url}]),'extended':1})
                print(json.dumps({'url':url,'response':r},ensure_ascii=False),flush=True)
            except Exception as error:
                print(type(error).__name__,str(error),flush=True)
    finally:
        await client.close()
asyncio.run(main())
'''
subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
                'root@62.217.176.12','docker exec -i kinozhdun_bot python -'],
               input=CODE,text=True,encoding='utf-8',check=True)
