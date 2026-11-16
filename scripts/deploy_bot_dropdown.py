"""Deploy only the bot chooser, with concurrency checks and rollback."""
import difflib
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, FILES, SSH

OUT = ROOT/'diagnostics/bot-dropdown'
REMOTE = r'''
import fcntl, hashlib, json, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
assert set(p['files'])=={'website/views.py','website/catalog_views.py','website/static/site.css','website/static/site.js','website/__main__.py'}
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for n in p['files']:
 assert hashlib.sha256((root/n).read_text().encode()).hexdigest()==p['before'][n], 'Concurrent source change: '+n
backup=Path('/root/kinozhdun-backups')/('bot-dropdown-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
for n in p['files']:
 target=backup/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target)
print('Backup: '+str(backup),flush=True)
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
def probe():
 subprocess.run(['docker','exec','kinozhdun_site','python','-c',
  "import urllib.request; h=urllib.request.urlopen('http://127.0.0.1:8099/health').read(); assert b'\"status\": \"ok\"' in h; s=urllib.request.urlopen('http://127.0.0.1:8099/').read(); assert b'bot-dropdown-trigger' in s and b'https://max.ru/id5001170357_1_bot' in s"],check=True,capture_output=True)
try:
 for n,s in p['files'].items():(root/n).write_text(s)
 subprocess.run(['python3','-m','compileall','-q','website'],cwd=root,check=True)
 rebuild()
 for attempt in range(20):
  try:probe();break
  except subprocess.CalledProcessError:
   if attempt==19:raise
   time.sleep(1)
except Exception:
 for n in p['files']:shutil.copy2(backup/n,root/n)
 rebuild()
 print('Rolled back.',flush=True)
 raise
print('Site health and chooser: OK',flush=True)
'''

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    before=json.loads((OUT/'before.json').read_text(encoding='utf-8'))
    files={n:(ROOT/n).read_text(encoding='utf-8') for n in FILES}
    # Preserve unrelated unfinished RSS changes in the local main module.
    line=next(line for line in files['website/__main__.py'].splitlines(True) if '"max_bot_url":' in line)
    main=before['website/__main__.py']
    anchor='            "channel_url": channel_url,\n'
    assert main.count(anchor)==1
    files['website/__main__.py']=main.replace(anchor,line+anchor)
    diff=''.join(''.join(difflib.unified_diff(before[n].splitlines(True),files[n].splitlines(True),fromfile=n+' production',tofile=n+' chooser')) for n in FILES)
    (OUT/'deployment.diff').write_text(diff,encoding='utf-8')
    payload={'files':files,'before':{n:hashlib.sha256(s.encode()).hexdigest() for n,s in before.items()}}
    (OUT/'manifest.json').write_text(json.dumps({n:hashlib.sha256(s.encode()).hexdigest() for n,s in files.items()},indent=2),encoding='utf-8')
    if '--deploy' not in sys.argv:
        print('Prepared 5 website files. Diff: '+str(OUT/'deployment.diff'))
        sys.exit(0)
    run=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=240)
    (OUT/'deployment.txt').write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
    print(run.stdout[-3000:]);print(run.stderr[-1500:]);sys.exit(run.returncode)
