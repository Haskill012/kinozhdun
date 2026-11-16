"""Verify live API connectivity without sending any chat messages."""
import subprocess
from inspect_bot_dropdown import SSH

CODE=r'''
import asyncio,logging,json,time
from pathlib import Path
from vk_bot.config import VKBotSettings
from vk_bot.client import VKBotClient
from bot.services.tmdb import TMDBClient
logging.disable(logging.CRITICAL)
async def main():
 settings=VKBotSettings.from_env();vk=VKBotClient(settings.VK_BOT_TOKEN,settings.VK_BOT_GROUP_ID)
 tmdb=TMDBClient(settings.TMDB_API_KEY,settings.TMDB_BASE_URL)
 try:
  import aiohttp
  params={'query':'Dune','language':'ru-RU'}
  if len(settings.TMDB_API_KEY)<=50:params['api_key']=settings.TMDB_API_KEY
  async with aiohttp.ClientSession(headers=tmdb._get_headers()) as probe:
   async with probe.get(settings.TMDB_BASE_URL+'/search/multi',params=params) as response:
    data=await response.json(content_type=None)
    print('TMDB HTTP status: '+str(response.status)+'; API status: '+str(data.get('status_code')))
  results=await tmdb.search_multi('Dune');assert results,'TMDB search returned no matches'
  item=next(r for r in results if r.get('media_type') in ('movie','tv'))
  details=await (tmdb.get_movie_details(item['tmdb_id']) if item['media_type']=='movie' else tmdb.get_tv_details(item['tmdb_id']))
  assert details,'TMDB details unavailable'
  print('TMDB live search and details: OK ('+str(len(results))+' matches)')
  server=await vk.api_call('photos.getMessagesUploadServer',{})
  assert server.get('upload_url');print('VK poster upload permission: OK')
  lp=await vk.api_call('groups.getLongPollSettings',{'group_id':vk.group_id})
  assert lp['is_enabled'] and lp['events']['message_new'] and lp['events']['message_event']
  print('VK message and button events: enabled')
  path=Path('data/vk_bot_ready.json');assert time.time()-path.stat().st_mtime<90
  print('Polling heartbeat: fresh')
 except Exception as exc:
  message=str(exc).replace(settings.VK_BOT_TOKEN,'[redacted]').replace(settings.TMDB_API_KEY,'[redacted]')
  print(type(exc).__name__+': '+message[:200]);raise
 finally:await tmdb.close();await vk.close()
asyncio.run(main())
'''
if __name__=='__main__':
    result=subprocess.run(SSH+['docker exec -i kinozhdun_vk_bot python -'],input=CODE,text=True,encoding='utf-8',capture_output=True,timeout=60)
    print(result.stdout)
    if result.returncode:print('Live verification failed; inspect runtime connectivity.')
    raise SystemExit(result.returncode)
