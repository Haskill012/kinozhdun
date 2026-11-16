import difflib,json,shlex,subprocess,sys
from pathlib import Path
from inspect_bot_dropdown import ROOT,SSH

FILES=['website/catalog_views.py','website/static/site.css']
OUT=ROOT/'diagnostics/carousel-images'
REMOTE=r'''
import fcntl,json,shutil,subprocess,time
from pathlib import Path
from datetime import datetime
import sys
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
assert set(p['files'])=={'website/catalog_views.py','website/static/site.css'}
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for n,s in p['before'].items():assert (root/n).read_text()==s,'Concurrent source change'
backup=Path('/root/kinozhdun-backups')/('carousel-images-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
for n in p['files']:
 target=backup/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target)
try:
 for n,s in p['files'].items():(root/n).write_text(s)
 subprocess.run(['python3','-m','compileall','-q','website'],cwd=root,check=True)
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
 for attempt in range(20):
  try:
   subprocess.run(['docker','exec','kinozhdun_site','python','-c',"import urllib.request;s=urllib.request.urlopen('http://127.0.0.1:8099/').read();assert b'<div class=\"spotlight-art\">' in s"],check=True,capture_output=True);break
  except subprocess.CalledProcessError:
   if attempt==19:raise
   time.sleep(1)
except Exception:
 for n in p['files']:shutil.copy2(backup/n,root/n)
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
 raise
print('Carousel fix deployed. Backup: '+str(backup))
'''

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(parents=True,exist_ok=True)
 if '--inspect' in sys.argv:
  code="import json;from pathlib import Path;print(json.dumps({n:(Path('/root/kinozhdun')/n).read_text() for n in "+repr(FILES)+"}))"
  result=subprocess.run(SSH+['python3 -'],input=code,text=True,encoding='utf-8',capture_output=True,check=True,timeout=30)
  (OUT/'before.json').write_text(result.stdout,encoding='utf-8');print('Snapshot saved');sys.exit(0)
 before=json.loads((OUT/'before.json').read_text(encoding='utf-8'));files={n:(ROOT/n).read_text(encoding='utf-8') for n in FILES}
 diff=''.join(''.join(difflib.unified_diff(before[n].splitlines(True),files[n].splitlines(True),fromfile=n+' production',tofile=n+' fix')) for n in FILES)
 (OUT/'deployment.diff').write_text(diff,encoding='utf-8')
 if '--deploy' not in sys.argv:print(diff);sys.exit(0)
 result=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps({'files':files,'before':before}),text=True,encoding='utf-8',capture_output=True,timeout=240)
 (OUT/'deployment.txt').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
 print(result.stdout[-700:]);print(result.stderr[-400:]);sys.exit(result.returncode)
