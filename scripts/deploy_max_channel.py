"""Deploy only the MAX channel mirror; preserve existing production services."""
import base64
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'diagnostics/max-channel'
SSH = ['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@62.217.176.12']
FILES = ['max_bot/__init__.py','max_bot/client.py','max_bot/channel_sync.py','max_bot/certs/russian_trusted_root_ca.cer']
REMOTE = r'''
import base64,fcntl,json,shutil,subprocess,sys,time
from datetime import datetime
from pathlib import Path
p=json.load(sys.stdin); root=Path('/root/kinozhdun')
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
assert set(p['files'])=={'max_bot/__init__.py','max_bot/client.py','max_bot/channel_sync.py','max_bot/certs/russian_trusted_root_ca.cer'}
assert set(p['env'])=={'MAX_BOT_TOKEN','MAX_BOT_URL','MAX_CHANNEL_ID','MAX_CHANNEL_POSTING_ENABLED'}
for n,b in p['before'].items():
 current=base64.b64encode((root/n).read_bytes()).decode() if (root/n).exists() else None
 assert current==b, 'Concurrent change: '+n
backup=Path('/root/kinozhdun-backups')/('max-channel-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True,mode=0o700)
for n in list(p['before'])+['.env']:
 if (root/n).exists():
  target=backup/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target)
print('Backup:',backup,flush=True)
try:
 for n,b in p['files'].items():
  target=root/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(b))
 compose=root/'docker-compose.yml';old=compose.read_text()
 if '  kinozhdun-max-channel:' not in old:
  assert old.count('  kinozhdun-site:\n')==1
  compose.write_text(old.replace('  kinozhdun-site:\n',p['service']+'  kinozhdun-site:\n'))
 else:
  assert p['service'] in old
 env=root/'.env';lines=[l for l in env.read_text().splitlines() if not any(l.startswith(k+'=') for k in p['env'])]
 env.write_text('\n'.join(lines+[k+'='+v for k,v in p['env'].items()])+'\n');env.chmod(0o600)
 subprocess.run(['docker','compose','config','--quiet'],cwd=root,check=True)
 subprocess.run(['docker','compose','build','kinozhdun-max-channel'],cwd=root,check=True)
 subprocess.run(['docker','compose','run','--rm','--no-deps','-T','--entrypoint','python','kinozhdun-max-channel','-'],input=p['tests'],text=True,cwd=root,check=True)
 started=time.time()
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-max-channel'],cwd=root,check=True)
 for attempt in range(60):
  ready=root/'data/max_channel_ready.json'
  if ready.exists():
   d=json.loads(ready.read_text())
   if d['ready'] and ready.stat().st_mtime>=started:
    print('MAX mirror ready:',json.dumps(d),flush=True);break
   if d['unresolved']:
    raise RuntimeError('Delivery requires inspection; journal retained')
  time.sleep(1)
 else:
  subprocess.run(['docker','logs','--tail','20','kinozhdun_max_channel']);raise RuntimeError('MAX mirror not ready')
except Exception:
 subprocess.run(['docker','compose','stop','kinozhdun-max-channel'],cwd=root)
 for n in list(p['before'])+['.env']:
  if (backup/n).exists():shutil.copy2(backup/n,root/n)
  elif p['before'].get(n) is None:(root/n).unlink(missing_ok=True)
 print('Sources/environment restored. Delivery journal retained.',flush=True)
 raise
'''

def main():
    sys.stdout.reconfigure(encoding='utf-8'); OUT.mkdir(parents=True,exist_ok=True)
    names=FILES+['docker-compose.yml']
    if '--inspect' in sys.argv:
        code="import base64,json;from pathlib import Path;r=Path('/root/kinozhdun');print(json.dumps({n:base64.b64encode((r/n).read_bytes()).decode() if (r/n).exists() else None for n in "+repr(names)+"}))"
        r=subprocess.run(SSH+['python3 -'],input=code,text=True,encoding='utf-8',capture_output=True,check=True,timeout=30)
        (OUT/'before.json').write_text(r.stdout,encoding='utf-8');print('Production snapshot saved.');return
    env={}
    for l in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in l and not l.lstrip().startswith('#'):
            k,v=l.split('=',1);env[k.strip()]=v.strip().strip('\"\'')
    compose=(ROOT/'docker-compose.yml').read_text(encoding='utf-8')
    service=compose[compose.index('  kinozhdun-max-channel:\n'):compose.index('  kinozhdun-vk-bot:\n')]
    p={'before':json.loads((OUT/'before.json').read_text()),'files':{n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in FILES},
       'service':service,'tests':(ROOT/'tests/test_max_channel_sync.py').read_text(encoding='utf-8'),
       'env':{'MAX_BOT_TOKEN':env['MAX_BOT_TOKEN'],'MAX_BOT_URL':env['MAX_BOT_URL'],'MAX_CHANNEL_ID':'-79850172292508','MAX_CHANNEL_POSTING_ENABLED':'true'}}
    r=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(p),text=True,encoding='utf-8',capture_output=True,timeout=300)
    output=(r.stdout+'\n'+r.stderr).replace(env['MAX_BOT_TOKEN'],'[REDACTED]')
    (OUT/'deployment.txt').write_text(output,encoding='utf-8');print(output[-7000:]);sys.exit(r.returncode)

if __name__=='__main__':main()
