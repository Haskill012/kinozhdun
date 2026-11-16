"""Read deployed runtime and prepare factual drafts; never publish new posts."""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CODE=r'''
import asyncio,hashlib,json,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from aiogram import Bot
from bot.config import Settings
from bot.scheduler.jobs import setup_scheduler
from bot.services.tmdb import TMDBClient
from bot.services.social_editorial import catalog_candidates,resolve_catalog_item
from bot.services.vk_spintax import format_vk_post
from bot.services.dzen_publisher import format_dzen_post_text
from bot.services.channel import format_channel_post_text

async def main():
 s=Settings.from_env();result={}
 public=['CHANNEL_POSTING_ENABLED','CHANNEL_AUTO_PUBLISH','DAILY_DIGEST_SKIP_WEEKLY_DAY',
 'DAILY_DIGEST_HOUR','WEEKLY_DIGEST_DAY','WEEKLY_DIGEST_HOUR','VK_POSTING_ENABLED',
 'VK_AUTO_PUBLISH','VK_ATTACHMENT_MODE','VK_POST_HOUR','VK_POST_MINUTE','VK_POST_DAYS',
 'DZEN_POSTING_ENABLED','DZEN_AUTO_PUBLISH','DZEN_SYNC_MODE','DZEN_CHANNEL_URL']
 result['settings']={k:getattr(s,k) for k in public}
 scheduler=setup_scheduler(Mock(),Mock(),Mock(),s)
 now=datetime.now(timezone.utc)
 result['schedules']=[{'id':job.id,'trigger':str(job.trigger),
  'next_moscow':job.trigger.get_next_fire_time(None,now).astimezone(ZoneInfo('Europe/Moscow')).isoformat()}
  for job in scheduler.get_jobs() if job.id in ('channel_daily_digest','channel_weekly_digest','check_vk_feed','check_dzen_feed')]
 bot=Bot(s.TELEGRAM_BOT_TOKEN)
 try:
  me=await bot.get_me();result['bot']={'username':me.username,'api_ok':True}
 finally:await bot.session.close()
 c=sqlite3.connect('file:data/kinozhdun.db?mode=ro',uri=True)
 result['tables']=[r[0] for r in c.execute("select name from sqlite_master where type='table'")]
 result['recent_vk_count']=c.execute('select count(*) from vk_posts').fetchone()[0]
 result['dzen_count']=c.execute('select count(*) from dzen_posts').fetchone()[0]
 c.close()
 result['source_hashes']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest()
  for name in ['bot/config.py','bot/services/channel.py','bot/services/dzen_delivery.py','bot/scheduler/jobs.py','bot/services/social_editorial.py']}
 titles=json.loads(Path('website/catalog_seed.json').read_text())['titles']
 tmdb=TMDBClient(s.TMDB_API_KEY,s.TMDB_BASE_URL)
 drafts=[]
 try:
  for raw in catalog_candidates(titles)[:18]:
   item=await resolve_catalog_item(raw,tmdb,settings=s)
   if not item:continue
   args=dict(title=item['title'],media_type=item['media_type'],event_type=item['event_type'],
    season_number=item.get('season'),air_date=item.get('air_date'),genres=item.get('genres'),
    overview=item.get('overview'),network=item.get('network'),episode_number=item.get('episode_number'))
   drafts.append({'tmdb_id':item['id'],'media_type':item['media_type'],'title':item['title'],
    'checked_at_moscow':now.astimezone(ZoneInfo('Europe/Moscow')).isoformat(),
    'facts':{k:str(v) if k=='air_date' and v else v for k,v in args.items()},
    'vk':format_vk_post(**args,item_id=item['id'],create_poll=False)['text'],
    'dzen':format_dzen_post_text(**args,tmdb_id=item['id']),
    'poster':item.get('poster'),
    'source':f"https://www.themoviedb.org/{item['media_type']}/{item['id']}"})
   if len(drafts)>=7:break
  # Facts for correcting existing local-test copies, independently of the draft selection.
  result['existing_post_facts']={}
  for media,ident in [('tv',2734),('movie',969681)]:
   detail=await (tmdb.get_tv_details(ident) if media=='tv' else tmdb.get_movie_details(ident))
   result['existing_post_facts'][f'{media}:{ident}']=detail
 finally:await tmdb.close()
 result['drafts']=drafts
 print(json.dumps(result,ensure_ascii=False,default=str))
asyncio.run(main())
'''
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 run=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
  '-o','ConnectTimeout=10','root@62.217.176.12','docker exec -i kinozhdun_bot python -'],
  input=CODE,text=True,encoding='utf-8',capture_output=True,timeout=180)
 if run.returncode:
  print('Runtime verification failed:',run.returncode);sys.exit(run.returncode)
 try:data=json.loads(run.stdout)
 except json.JSONDecodeError:
  print('Runtime returned no valid verification JSON.');sys.exit(1)
 out=ROOT/'diagnostics/channel-fixes-2026-10-06/runtime.json'
 out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in data.items() if k not in ['drafts','existing_post_facts','tables']},ensure_ascii=False))
 print('Factual drafts prepared:',len(data['drafts']))
