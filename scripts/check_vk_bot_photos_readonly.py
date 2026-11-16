"""Read-only capability checks for the VK tracker community; no uploads or posts."""
import json
import subprocess
import sys
from inspect_bot_dropdown import ROOT, SSH

CODE = r'''
import asyncio,json,logging,os
from vk_bot.config import VKBotSettings
from bot.services.vk_client import VKClient,VKApiError
logging.disable(logging.CRITICAL)
async def main():
 s=VKBotSettings.from_env();client=VKClient(s.VK_BOT_TOKEN,s.VK_BOT_GROUP_ID)
 result={'bot_group_id':client.group_id,'channel_group_id':int(os.getenv('VK_GROUP_ID','0') or 0),'checks':[]}
 async def check(method,params,token=None,label='bot-community-token'):
  try:
   value=await client.api_call(method,params,token=token)
   if method=='groups.getById':
    groups=value if isinstance(value,list) else value.get('groups',[])
    safe=[{k:g.get(k) for k in ('id','name','screen_name','type','wall','can_post','can_upload_photo')} for g in groups]
   elif method=='groups.getTokenPermissions':safe=value
   elif method=='wall.get':
    safe={'count':value.get('count'),'posts':[{'id':p.get('id'),'owner_id':p.get('owner_id'),
     'text':p.get('text','')[:220],'url':f"https://vk.com/wall{p.get('owner_id')}_{p.get('id')}",
     'attachments':[{'type':a.get('type'),'photo_id':a.get('photo',{}).get('id')} for a in p.get('attachments',[])]}
     for p in value.get('items',[])]}
   else:safe={'upload_server_available':bool(value.get('upload_url'))}
   result['checks'].append({'method':method,'authorization':label,'result':safe})
   return True
  except VKApiError as exc:
   result['checks'].append({'method':method,'authorization':label,'error_code':exc.error_code,'message':exc.error_msg})
  except Exception as exc:
   result['checks'].append({'method':method,'authorization':label,'error_type':type(exc).__name__})
  return False
 try:
  await check('groups.getById',{'group_id':client.group_id,'fields':'wall,can_post,can_upload_photo'})
  await check('groups.getTokenPermissions',{})
  readable=await check('wall.get',{'owner_id':-client.group_id,'count':5})
  if not readable and os.getenv('VK_USER_TOKEN'):
   await check('wall.get',{'owner_id':-client.group_id,'count':5},os.getenv('VK_USER_TOKEN'),'existing-user-token')
  await check('photos.getMessagesUploadServer',{})
  await check('photos.getWallUploadServer',{'group_id':client.group_id})
  if os.getenv('VK_USER_TOKEN'):
   await check('photos.getWallUploadServer',{'group_id':client.group_id},os.getenv('VK_USER_TOKEN'),'existing-user-token')
 finally:await client.close()
 print(json.dumps(result,ensure_ascii=False))
asyncio.run(main())
'''
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run=subprocess.run(SSH+['docker exec -i kinozhdun_vk_bot python -'],input=CODE,
                       text=True,encoding='utf-8',capture_output=True,timeout=150)
    if run.returncode:print('Read-only check failed:',run.stderr[-1200:]);sys.exit(run.returncode)
    data=json.loads(run.stdout)
    out=ROOT/'diagnostics/vk-bot-photo-check-2026-10-07';out.mkdir(parents=True,exist_ok=True)
    (out/'check.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data,ensure_ascii=False,indent=2))
