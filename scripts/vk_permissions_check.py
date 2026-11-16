"""Read current community-token capabilities without printing credentials."""
from pathlib import Path
import subprocess

CODE = r'''
import asyncio,json
from bot.config import Settings
from bot.services.vk_client import VKClient
async def main():
    s=Settings.from_env()
    c=VKClient(s.VK_ACCESS_TOKEN,s.VK_GROUP_ID)
    try:
        for method,params in [('groups.getTokenPermissions',{}),
                              ('groups.getById',{'group_id':c.group_id,'fields':'wall,photos,docs'}),
                              ('docs.getWallUploadServer',{'group_id':c.group_id})]:
            try:
                r=await c.api_call(method,params)
                if method.endswith('UploadServer'):
                    r={'upload_available':bool(r.get('upload_url'))}
                print(json.dumps({'method':method,'result':r},ensure_ascii=False),flush=True)
            except Exception as error:
                print(json.dumps({'method':method,'error':str(error)},ensure_ascii=False),flush=True)
    finally:
        await c.close()
asyncio.run(main())
'''
if __name__=='__main__':
    r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
       'root@62.217.176.12','docker exec -i kinozhdun_bot python -'],input=CODE,text=True,
       encoding='utf-8',capture_output=True)
    print(r.stdout)
    raise SystemExit(r.returncode)
