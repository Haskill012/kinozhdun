"""Publish the four explicitly requested introductory posts exactly once."""
import json
import subprocess
import sys
from inspect_bot_dropdown import ROOT,SSH

CODE=r'''
import asyncio,json,logging,fcntl
from pathlib import Path
from vk_bot.config import VKBotSettings
from bot.services.vk_client import VKClient,VKApiError
logging.disable(logging.CRITICAL)
async def main():
 s=VKBotSettings.from_env();assert s.VK_BOT_GROUP_ID==242087163
 c=VKClient(s.VK_BOT_TOKEN,s.VK_BOT_GROUP_ID)
 path=Path('/app/data/vk-startup-posts-20261007.json')
 lock=open(str(path)+'.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 journal=json.loads(path.read_text()) if path.exists() else {}
 def save():
  temp=path.with_suffix('.tmp');temp.write_text(json.dumps(journal,ensure_ascii=False,indent=2));temp.replace(path)
 try:
  data=await c.api_call('groups.getById',{'group_id':s.VK_BOT_GROUP_ID})
  group=(data if isinstance(data,list) else data['groups'])[0]
  assert group['id']==242087163 and group['name']=='КиноЖдун Бот'
  for post in POSTS:
   key=post['key'];old=journal.get(key,{})
   if old.get('status')=='published':
    print(json.dumps(old,ensure_ascii=False),flush=True);continue
   assert old.get('status') not in ('sending','uncertain'), 'Unconfirmed previous attempt; manual verification required'
   journal[key]={'key':key,'status':'sending','text':post['text']};save()
   try:
    post_id=await c.post_to_wall(post['text'])
   except VKApiError as e:
    journal[key].update(status='failed',error_code=e.error_code,message=e.error_msg);save()
    print(json.dumps({'key':key,'error_code':e.error_code,'message':e.error_msg},ensure_ascii=False),flush=True)
    raise SystemExit(1)
   except Exception as e:
    journal[key].update(status='uncertain',error_type=type(e).__name__);save()
    print(json.dumps({'key':key,'status':'uncertain','error_type':type(e).__name__}),flush=True)
    raise SystemExit(1)
   journal[key].update(status='published',post_id=post_id,url=f'https://vk.com/wall-{s.VK_BOT_GROUP_ID}_{post_id}');save()
   print(json.dumps({k:v for k,v in journal[key].items() if k!='text'},ensure_ascii=False),flush=True)
   await asyncio.sleep(1)
 finally:await c.close()
asyncio.run(main())
'''
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 posts=json.loads((ROOT/'output/vk-startup-posts-2026-10-07.json').read_text(encoding='utf-8'))
 assert len(posts)==4 and len({p['key'] for p in posts})==4
 code='POSTS='+repr(posts)+'\n'+CODE
 run=subprocess.run(SSH+['docker exec -i kinozhdun_vk_bot python -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=120)
 out=ROOT/'diagnostics/vk-startup-posts-2026-10-07';out.mkdir(exist_ok=True,parents=True)
 (out/'result.jsonl').write_text(run.stdout,encoding='utf-8')
 print(run.stdout)
 if run.returncode:
  print('Publication did not complete; do not retry uncertain attempts.');sys.exit(run.returncode)
