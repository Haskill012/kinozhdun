"""Check cover upload capability without uploading or changing the community."""
import subprocess
import sys
from inspect_bot_dropdown import SSH
CODE=r'''
import asyncio,json,logging
from vk_bot.config import VKBotSettings
from bot.services.vk_client import VKClient,VKApiError
logging.disable(logging.CRITICAL)
async def main():
 s=VKBotSettings.from_env();c=VKClient(s.VK_BOT_TOKEN,s.VK_BOT_GROUP_ID)
 try:
  r=await c.api_call('photos.getOwnerCoverPhotoUploadServer',{'group_id':s.VK_BOT_GROUP_ID,'crop_x':0,'crop_y':0,'crop_x2':1983,'crop_y2':793})
  print(json.dumps({'group_id':s.VK_BOT_GROUP_ID,'cover_upload_available':bool(r.get('upload_url'))}))
 except VKApiError as e:print(json.dumps({'error_code':e.error_code,'message':e.error_msg}))
 finally:await c.close()
asyncio.run(main())
'''
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 subprocess.run(SSH+['docker exec -i kinozhdun_vk_bot python -'],input=CODE,text=True,encoding='utf-8',check=True,timeout=60)
