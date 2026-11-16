"""Replace tutorial media and its cache revision with concurrency checks."""
import base64
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

OUT=ROOT/'diagnostics/hero-demo/v2'
REMOTE=r'''
import base64,fcntl,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
names={'website/catalog_views.py','website/static/subscription-demo.mp4','website/static/subscription-demo.jpg','website/static/subscription-demo.vtt'}
assert set(p['files'])==names and set(p['before'])==names
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for n,h in p['before'].items():assert hashlib.sha256((root/n).read_bytes()).hexdigest()==h,'Concurrent change: '+n
backup=Path('/root/kinozhdun-backups')/('subscription-demo-polish-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
for n in names:
 target=backup/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target)
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
expected=hashlib.sha256(base64.b64decode(p['files']['website/static/subscription-demo.mp4'])).hexdigest()
probe="import urllib.request,json,hashlib; b='http://127.0.0.1:8099'; assert json.load(urllib.request.urlopen(b+'/health'))['status']=='ok'; assert b'subscription-demo.mp4?v=2' in urllib.request.urlopen(b+'/').read(); assert hashlib.sha256(urllib.request.urlopen(b+'/static/subscription-demo.mp4?v=2').read()).hexdigest()=="+repr(expected)
try:
 for n,s in p['files'].items():(root/n).write_bytes(base64.b64decode(s))
 subprocess.run(['python3','-m','compileall','-q','website'],cwd=root,check=True)
 rebuild()
 for attempt in range(25):
  try:subprocess.run(['docker','exec','kinozhdun_site','python','-c',probe],check=True,capture_output=True);break
  except subprocess.CalledProcessError:
   if attempt==24:raise
   time.sleep(1)
except Exception:
 for n in names:shutil.copy2(backup/n,root/n)
 rebuild();raise
print('Polished tutorial published; media hash and page revision verified. Backup: '+str(backup))
'''

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    before=json.loads((OUT/'production-before.json').read_text(encoding='utf-8'))
    local=(ROOT/'website/catalog_views.py').read_text(encoding='utf-8')
    assert local.replace('?v=2','')==before['source']
    payload={'before':before['hashes'],'files':{name:base64.b64encode((ROOT/name).read_bytes()).decode() for name in before['hashes']}}
    if '--deploy' not in sys.argv:
        print('Prepared video, poster, captions and media cache revision.');sys.exit(0)
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=240)
    (OUT/'deployment.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    print(result.stdout[-1500:]);print(result.stderr[-600:]);sys.exit(result.returncode)
