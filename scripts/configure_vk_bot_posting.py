"""Retarget the existing VK editorial scheduler without exposing credentials."""
import subprocess
import sys
from inspect_bot_dropdown import SSH

REMOTE = r'''
import json, subprocess, sys, shutil, fcntl
from pathlib import Path
from datetime import datetime
root=Path('/root/kinozhdun')
lock=open(root/'.vk-posting-config.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
probe=r"""
import json,os
from bot.config import Settings
s=Settings.from_env()
print(json.dumps({'group_id':s.VK_GROUP_ID,'enabled':s.VK_POSTING_ENABLED,'automatic':s.VK_AUTO_PUBLISH,
'mode':s.VK_ATTACHMENT_MODE,'hour':s.VK_POST_HOUR,'minute':s.VK_POST_MINUTE,'days':s.VK_POST_DAYS,
'bot_group_id':os.getenv('VK_BOT_GROUP_ID'),'bot_token_available':bool(os.getenv('VK_BOT_TOKEN'))}))
"""
subprocess.run(['docker','exec','-i','kinozhdun_bot','python','-'],input=probe,text=True,check=True)
if sys.argv[-1]=='inspect':sys.exit(0)
env=root/'.env'
# Read secrets locally on the server; never return or log them.
values={}
for line in env.read_text().splitlines():
 if '=' in line and not line.lstrip().startswith('#'):
  k,v=line.split('=',1);values[k.strip()]=v.strip().strip('\"').strip("'")
assert values.get('VK_BOT_TOKEN'), 'New community token missing'
group=abs(int(values.get('VK_BOT_GROUP_ID','242087163')))
assert group==242087163, 'Unexpected destination'
backup=Path('/root/kinozhdun-backups')/('vk-bot-posting-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700,parents=True)
shutil.copy2(env,backup/'.env');(backup/'.env').chmod(0o600)
def configure(automatic):
 updates={'VK_ACCESS_TOKEN':values['VK_BOT_TOKEN'],'VK_GROUP_ID':str(group),
 'VK_POSTING_ENABLED':'true','VK_AUTO_PUBLISH':str(automatic).lower(),
 'VK_ATTACHMENT_MODE':'text','VK_CREATE_POLL':'false','VK_LINK_IN_COMMENT':'false'}
 lines=[l for l in env.read_text().splitlines() if l.split('=',1)[0].strip() not in updates]
 env.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n');env.chmod(0o600)
def recreate():
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
configure(False);recreate()
trial=r"""
import asyncio,json,logging
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy import text
from bot.config import Settings
from bot.services.vk_client import VKClient
from bot.scheduler.jobs import check_vk_feed_job,setup_scheduler
from bot.services.tmdb import TMDBClient
logging.disable(logging.CRITICAL)
async def main():
 s=Settings.from_env();assert s.VK_GROUP_ID==242087163 and s.VK_ATTACHMENT_MODE=='text' and not s.VK_AUTO_PUBLISH
 client=VKClient(s.VK_ACCESS_TOKEN,s.VK_GROUP_ID)
 try:
  data=await client.api_call('groups.getById',{'group_id':s.VK_GROUP_ID})
  groups=data if isinstance(data,list) else data['groups']
  assert groups[0]['id']==242087163 and groups[0]['name']=='КиноЖдун Бот'
 finally:await client.close()
 engine=create_async_engine(s.DATABASE_URL)
 tmdb=TMDBClient(s.TMDB_API_KEY)
 try:
  async with engine.connect() as conn:
   before=(await conn.execute(text('SELECT coalesce(max(id),0) FROM vk_posts'))).scalar()
  s.VK_AUTO_PUBLISH=True
  await check_vk_feed_job(async_sessionmaker(engine,expire_on_commit=False),s,tmdb)
  async with engine.connect() as conn:
   row=(await conn.execute(text('SELECT id,title,vk_post_id,status FROM vk_posts ORDER BY id DESC LIMIT 1'))).mappings().first()
  assert row and row['id']>before and row['status']=='published' and row['vk_post_id'], 'Publication failed; automatic posting remains disabled'
  scheduler=setup_scheduler(None,async_sessionmaker(engine,expire_on_commit=False),tmdb,s)
  job=scheduler.get_job('check_vk_feed');assert job
  print(json.dumps({'title':row['title'],'post_id':row['vk_post_id'],'status':row['status'],
   'url':f"https://vk.com/wall-{s.VK_GROUP_ID}_{row['vk_post_id']}",
   'schedule':str(job.trigger),'timezone':str(scheduler.timezone)},ensure_ascii=False),flush=True)
 finally:
  await tmdb.close();await engine.dispose()
asyncio.run(main())
"""
subprocess.run(['docker','exec','-i','kinozhdun_bot','python','-'],input=trial,text=True,check=True)
configure(True);recreate()
subprocess.run(['docker','exec','-i','kinozhdun_bot','python','-'],input=probe,text=True,check=True)
print('Backup:',str(backup))
'''

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    mode='inspect' if '--inspect' in sys.argv else 'apply'
    # stdin carries code, and the argument contains only a fixed operation name.
    subprocess.run(SSH+['python3 - '+mode],input=REMOTE,text=True,encoding='utf-8',check=True,timeout=240)
