"""Correct existing factual cards and verify production health without new posts."""
import asyncio, html, json, subprocess, sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from aiogram import Bot
from bot.config import Settings
from bot.services.social_editorial import event_copy

async def main():
    s=Settings.from_env(); b=Bot(s.TELEGRAM_BOT_TOKEN)
    data=json.loads((ROOT/'diagnostics/channel-fixes-2026-10-06/runtime.json').read_text(encoding='utf-8'))
    results=[]
    try:
        for mid,key in [(21,'tv:2734'),(23,'movie:969681')]:
            d=data['existing_post_facts'][key]; media,ident=key.split(':')
            episode=d.get('next_episode_to_air') or {}
            when=episode.get('air_date') if media=='tv' else d.get('release_date')
            args=dict(title=d.get('title') or d.get('name'),media_type=media,tmdb_id=int(ident),
                overview=d.get('overview'),air_date=date.fromisoformat(when) if when else None,
                season_number=episode.get('season_number'),episode_number=episode.get('episode_number'),
                event_type='episode_date' if episode else 'announced')
            parts,past=event_copy(**args)
            text='<b>'+html.escape(parts[0])+'</b>\n\n'+'\n\n'.join(html.escape(p) for p in parts[1:])
            text+='\n\n'+('Сохраните фильм в список просмотра' if past else 'Добавьте сериал в личный трекер')+': @kinojdun_bot'
            row={'message_id':mid,'caption':text}
            try:
                await b.edit_message_caption(chat_id=s.TELEGRAM_CHANNEL_ID,message_id=mid,caption=text,parse_mode='HTML')
                row['corrected']=True
            except Exception as e:row['error_type']=type(e).__name__
            results.append(row)
        # A false "premiere today / already available" post with a September date.
        row={'message_id':18,'reason':'False October premiere and unverified viewing availability'}
        try:row['deleted']=await b.delete_message(s.TELEGRAM_CHANNEL_ID,18)
        except Exception as e:row['error_type']=type(e).__name__
        results.append(row)
    finally:await b.session.close()
    out=ROOT/'diagnostics/channel-fixes-2026-10-06/final-cleanup.json'
    out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k!='caption'} for r in results],ensure_ascii=False))
    deleted=any(r.get('message_id')==18 and r.get('deleted') for r in results)
    code="""
import json, sqlite3, subprocess, urllib.request
from pathlib import Path
result={}
if DELETE_CONFIRMED:
 c=sqlite3.connect('/root/kinozhdun/data/kinozhdun.db')
 c.execute("update channel_posts set status='deleted' where telegram_message_id=18")
 c.commit();c.close()
result['container']=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}','kinozhdun_bot']))['Status']
logs=subprocess.check_output(['docker','logs','--since','20m','kinozhdun_bot'],stderr=subprocess.STDOUT).decode(errors='replace')
result['polling_started']='Start polling' in logs or 'Run polling' in logs
result['traceback_present']='Traceback (most recent call last)' in logs
try:
 result['website_health']=json.load(urllib.request.urlopen('https://kinojdun.ru/health',timeout=15))
except Exception as e:result['website_health_error_type']=type(e).__name__
print(json.dumps(result))
""".replace('DELETE_CONFIRMED',repr(deleted))
    run=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
        'root@62.217.176.12','python3 -'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=60)
    if run.returncode:raise RuntimeError('Server health check failed, exit '+str(run.returncode))
    health=json.loads(run.stdout)
    out.with_name('health.json').write_text(json.dumps(health,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(health,ensure_ascii=False))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(main())
