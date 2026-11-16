"""Deploy the VK messenger bot and website choice without touching wall publishing."""
import difflib, hashlib, json, shlex, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values
from inspect_bot_dropdown import ROOT, SSH

OUT=ROOT/'diagnostics/vk-bot'
EXISTING=['website/views.py','website/catalog_views.py','website/static/site.css','website/static/site.js','website/__main__.py','Dockerfile','docker-compose.yml']
LIBRARY=['max_bot/'+name for name in ['__init__.py','client.py','config.py','handlers.py','keyboards.py','state.py','scheduler.py']]
NEW=LIBRARY+['vk_bot/'+p.name for p in (ROOT/'vk_bot').glob('*.py')]
FILES=EXISTING+NEW

REMOTE=r'''
import fcntl,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
assert all(n.startswith(('website/','max_bot/','vk_bot/')) or n in ('Dockerfile','docker-compose.yml') for n in p['files'])
assert all('..' not in Path(n).parts and not Path(n).is_absolute() for n in p['files'])
assert set(p['env'])=={'VK_BOT_TOKEN','VK_BOT_GROUP_ID','VK_BOT_URL','VK_DATABASE_URL'}
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for n,s in p['before'].items():
 current=(root/n).read_text() if (root/n).exists() else None
 assert current==s, 'Concurrent source change: '+n
backup=Path('/root/kinozhdun-backups')/('vk-bot-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
for n in list(p['files'])+['.env']:
 if (root/n).exists():
  target=backup/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target)
(backup/'manifest.json').write_text(json.dumps({n:s is not None for n,s in p['before'].items()}))
print('Backup: '+str(backup),flush=True)
try:
 for n,s in p['files'].items():
  target=root/n;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(s)
 env=root/'.env';lines=[line for line in env.read_text().splitlines() if not any(line.startswith(k+'=') for k in p['env'])]
 env.write_text('\n'.join(lines+[k+'='+v for k,v in p['env'].items()])+'\n');env.chmod(0o600)
 subprocess.run(['python3','-m','compileall','-q','vk_bot','max_bot','website'],cwd=root,check=True)
 subprocess.run(['docker','compose','config','--quiet'],cwd=root,check=True)
 subprocess.run(['docker','compose','build','kinozhdun-vk-bot','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','run','--rm','--no-deps','-T','--entrypoint','python','kinozhdun-vk-bot','-'],
                input=p['smoke_tests']+'\n\nunittest.main()\n',text=True,cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-vk-bot','kinozhdun-site'],cwd=root,check=True)
 for attempt in range(60):
  try:
   subprocess.run(['docker','exec','kinozhdun_vk_bot','python','-c',
    "from pathlib import Path;import json,time;p=Path('/app/data/vk_bot_ready.json');d=json.loads(p.read_text());assert d['ready'] and d['group_id']==242087163 and time.time()-p.stat().st_mtime<60"],check=True,capture_output=True)
   subprocess.run(['docker','exec','kinozhdun_site','python','-c',
    "import urllib.request,json;assert json.loads(urllib.request.urlopen('http://127.0.0.1:8099/health').read())['status']=='ok';s=urllib.request.urlopen('http://127.0.0.1:8099/').read();assert b'bot-dropdown-vk' in s and b'https://vk.me/club242087163' in s"],check=True,capture_output=True)
   break
  except subprocess.CalledProcessError:
   if attempt==59:raise
   time.sleep(1)
except Exception:
 subprocess.run(['docker','compose','stop','kinozhdun-vk-bot'],cwd=root)
 for n in list(p['files'])+['.env']:
  if (backup/n).exists():shutil.copy2(backup/n,root/n)
  elif n in p['files'] and p['before'].get(n) is None:(root/n).unlink(missing_ok=True)
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
 print('Rolled back bot/site sources and environment.',flush=True)
 raise
print('VK bot polling and scheduler: ready. Website: healthy.',flush=True)
'''

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(parents=True,exist_ok=True)
    if '--inspect' in sys.argv:
        code="import json;from pathlib import Path;r=Path('/root/kinozhdun');print(json.dumps({n:(r/n).read_text() if (r/n).exists() else None for n in "+repr(FILES)+"}))"
        run=subprocess.run(SSH+['python3 -'],input=code,text=True,encoding='utf-8',capture_output=True,check=True,timeout=30)
        (OUT/'before.json').write_text(run.stdout,encoding='utf-8');print('Production source snapshot saved.');sys.exit(0)
    before=json.loads((OUT/'before.json').read_text(encoding='utf-8'))
    files={n:(ROOT/n).read_text(encoding='utf-8') for n in FILES}
    main=before['website/__main__.py'];anchor='            "channel_url": channel_url,\n'
    assert main.count(anchor)==1 and '"vk_bot_url":' not in main
    line=next(line for line in files['website/__main__.py'].splitlines(True) if '"vk_bot_url":' in line)
    files['website/__main__.py']=main.replace(anchor,line+anchor)
    docker=before['Dockerfile'];anchor='COPY shared/ ./shared/\n';assert docker.count(anchor)==1
    files['Dockerfile']=docker.replace(anchor,anchor+'COPY max_bot/ ./max_bot/\nCOPY vk_bot/ ./vk_bot/\n')
    compose=before['docker-compose.yml'];anchor='  kinozhdun-site:\n';assert compose.count(anchor)==1
    local_compose=files['docker-compose.yml'];start=local_compose.index('  kinozhdun-vk-bot:\n');end=local_compose.index(anchor,start)
    files['docker-compose.yml']=compose.replace(anchor,local_compose[start:end]+anchor)
    diff=''.join(''.join(difflib.unified_diff((before[n] or '').splitlines(True),s.splitlines(True),fromfile=n+' production',tofile=n+' VK')) for n,s in files.items())
    (OUT/'deployment.diff').write_text(diff,encoding='utf-8')
    (OUT/'manifest.json').write_text(json.dumps({n:hashlib.sha256(s.encode()).hexdigest() for n,s in files.items()},indent=2),encoding='utf-8')
    if '--deploy' not in sys.argv:print('Prepared '+str(len(files))+' source files.');sys.exit(0)
    env=dotenv_values(ROOT/'.env')
    payload={'files':files,'before':before,'env':{key:env[key] for key in ('VK_BOT_TOKEN','VK_BOT_GROUP_ID','VK_BOT_URL')}}
    payload['env']['VK_DATABASE_URL']='sqlite+aiosqlite:///./data/kinozhdun_vk.db'
    payload['smoke_tests']=(ROOT/'tests/test_vk_bot.py').read_text(encoding='utf-8')
    run=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=300)
    (OUT/'deployment.txt').write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
    print(run.stdout[-2000:]);print(run.stderr[-1000:]);sys.exit(run.returncode)
