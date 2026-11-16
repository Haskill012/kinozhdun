"""Deploy the approved editorial changes with private backups and no test posts."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['bot/config.py','bot/db/models.py','bot/db/repositories.py','bot/services/channel.py',
       'bot/services/digest_style.py','bot/services/social_editorial.py','bot/services/dzen_publisher.py',
       'bot/services/dzen_delivery.py','bot/services/vk_spintax.py','bot/services/vk_publisher.py',
       'bot/services/vk_client.py','bot/services/tmdb.py','bot/scheduler/jobs.py']
REMOTE=r'''
import fcntl,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin)
root=Path('/root/kinozhdun')
lock=open('/root/kinozhdun_deploy.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX)
backup=Path('/root/kinozhdun-backups')/('channel-editorial-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
allowed={'bot/config.py','bot/db/models.py','bot/db/repositories.py','bot/services/channel.py',
 'bot/services/digest_style.py','bot/services/social_editorial.py','bot/services/dzen_publisher.py',
 'bot/services/dzen_delivery.py','bot/services/vk_spintax.py','bot/services/vk_publisher.py',
 'bot/services/vk_client.py','bot/services/tmdb.py','bot/scheduler/jobs.py'}
assert set(p['files'])==allowed
manifest={}
for name in list(p['files'])+['.env']:
 target=root/name
 manifest[name]={'existed':target.exists()}
 if target.exists():
  dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,dest)
  manifest[name]['before_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
for name,content in p['files'].items():
 target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding='utf-8')
env=root/'.env'
updates=p['settings']
lines=[line for line in env.read_text().splitlines() if line.split('=',1)[0].strip() not in updates]
env.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n');env.chmod(0o600)
print('Private backup:',str(backup),flush=True)
try:
 subprocess.run(['python3','-m','compileall','-q','bot'],cwd=root,check=True)
 subprocess.run(['docker','compose','build','kinozhdun-bot'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
except Exception:
 # Restore only the files managed by this deployment, preserving databases and other work.
 for name,info in manifest.items():
  target=root/name
  if info['existed']:shutil.copy2(backup/name,target)
  elif target.exists():target.unlink()
 subprocess.run(['docker','compose','build','kinozhdun-bot'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
 raise
print('Channel editorial deployment complete; no test posts were sent.',flush=True)
'''

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    settings={'CHANNEL_AUTO_PUBLISH':'true','CHANNEL_POSTING_ENABLED':'true',
              'DAILY_DIGEST_SKIP_WEEKLY_DAY':'true','DAILY_DIGEST_HOUR':'9',
              'WEEKLY_DIGEST_DAY':'0','WEEKLY_DIGEST_HOUR':'10',
              'VK_AUTO_PUBLISH':'true','VK_POSTING_ENABLED':'true','VK_ATTACHMENT_MODE':'text',
              'VK_CREATE_POLL':'false','VK_LINK_IN_COMMENT':'false',
              'VK_POST_HOUR':'18','VK_POST_MINUTE':'30','VK_POST_DAYS':'mon-sat',
              'DZEN_POSTING_ENABLED':'true','DZEN_AUTO_PUBLISH':'true','DZEN_SYNC_MODE':'telegram_sync',
              'DZEN_CHANNEL_URL':'https://dzen.ru/id/6ac51db3089f1b4285477e70',
              'DZEN_CHANNEL_ID':'6ac51db3089f1b4285477e70',
              'DZEN_POST_HOUR':'18','DZEN_POST_MINUTE':'30','DZEN_POST_DAYS':'mon,wed,fri,sun'}
    files={name:(ROOT/name).read_text(encoding='utf-8-sig') for name in FILES}
    # Persist only hashes and non-secret settings locally.
    (ROOT/'diagnostics/channel-fixes-2026-10-06/deployment-manifest.json').write_text(
        json.dumps({'files':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in files.items()},'settings':settings},indent=2),encoding='utf-8')
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),
        '-o','BatchMode=yes','-o','ConnectTimeout=10','root@62.217.176.12',
        'python3 -c '+__import__('shlex').quote(REMOTE)],
        input=json.dumps({'files':files,'settings':settings},ensure_ascii=False),
        text=True,encoding='utf-8',capture_output=True,timeout=300)
    (ROOT/'diagnostics/channel-fixes-2026-10-06/deployment.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    print(result.stdout)
    if result.returncode:print(result.stderr[-2500:])
    sys.exit(result.returncode)
