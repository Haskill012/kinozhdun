"""Install the generated desktop cover through the documented VK cover API."""
import base64
import json
import subprocess
import sys
from inspect_bot_dropdown import ROOT,SSH
CODE=r'''
import asyncio,base64,json,logging
from pathlib import Path
import aiohttp
from vk_bot.config import VKBotSettings
from bot.services.vk_client import VKClient,VKApiError
logging.disable(logging.CRITICAL)
async def main():
 s=VKBotSettings.from_env();assert s.VK_BOT_GROUP_ID==242087163
 c=VKClient(s.VK_BOT_TOKEN,s.VK_BOT_GROUP_ID)
 try:
  before=await c.api_call('groups.getById',{'group_id':s.VK_BOT_GROUP_ID,'fields':'cover'})
  Path('/app/data/vk-cover-before-20261007.json').write_text(json.dumps(before,ensure_ascii=False))
  server=await c.api_call('photos.getOwnerCoverPhotoUploadServer',{'group_id':s.VK_BOT_GROUP_ID,'crop_x':0,'crop_y':0,'crop_x2':1983,'crop_y2':793})
  form=aiohttp.FormData();form.add_field('photo',base64.b64decode(IMAGE),filename='kinojdun-cover.png',content_type='image/png')
  async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as http:
   async with http.post(server['upload_url'],data=form) as r:
    if r.status!=200:
     print(json.dumps({'upload_http_status':r.status}));raise SystemExit(1)
    uploaded=await r.json(content_type=None)
  assert uploaded.get('photo') and uploaded.get('hash'), 'Upload response missing photo/hash'
  saved=await c.api_call('photos.saveOwnerCoverPhoto',{'photo':uploaded['photo'],'hash':uploaded['hash']})
  after=await c.api_call('groups.getById',{'group_id':s.VK_BOT_GROUP_ID,'fields':'cover'})
  groups=after if isinstance(after,list) else after['groups']
  cover=groups[0].get('cover',{})
  print(json.dumps({'group_id':s.VK_BOT_GROUP_ID,'save_confirmed':bool(saved),'cover':cover},ensure_ascii=False))
 except VKApiError as e:print(json.dumps({'error_code':e.error_code,'message':e.error_msg}));raise SystemExit(1)
 finally:await c.close()
asyncio.run(main())
'''
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 encoded=base64.b64encode((ROOT/'output/imagegen/kinojdun-vk-cover-v2.png').read_bytes()).decode('ascii')
 code='IMAGE='+repr(encoded)+'\n'+CODE
 r=subprocess.run(SSH+['docker exec -i kinozhdun_vk_bot python -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=130)
 out=ROOT/'diagnostics/vk-cover-2026-10-07';out.mkdir(exist_ok=True,parents=True)
 (out/'desktop-result.json').write_text(r.stdout,encoding='utf-8')
 print(r.stdout)
 if r.returncode:
  print('Cover installation did not complete; see safe status above.');sys.exit(r.returncode)
