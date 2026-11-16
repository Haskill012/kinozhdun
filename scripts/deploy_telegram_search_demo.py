"""Publish the second real tutorial with checked source hashes and rollback."""
import base64, json, shlex, subprocess, sys, difflib
from inspect_bot_dropdown import ROOT, SSH
OUT=ROOT/'diagnostics/hero-demo/telegram-search'
SOURCES=['website/catalog_views.py','website/static/site.js','website/static/site.css']
MEDIA=['website/static/telegram-search-demo.'+ext for ext in ('mp4','jpg','vtt')]
SNAP="import json,hashlib;from pathlib import Path;r=Path('/root/kinozhdun');names="+repr(SOURCES+MEDIA)+";print(json.dumps({'hashes':{n:hashlib.sha256((r/n).read_bytes()).hexdigest() if (r/n).exists() else None for n in names},'sources':{n:(r/n).read_text() for n in "+repr(SOURCES)+"}}))"
REMOTE=r'''
import base64,fcntl,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for n,h in p['before'].items():
 f=root/n;assert (hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None)==h,'Concurrent change: '+n
backup=Path('/root/kinozhdun-backups')/('telegram-search-demo-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
for n,h in p['before'].items():
 if h is not None:
  f=backup/n;f.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,f)
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
expected=hashlib.sha256(base64.b64decode(p['files']['website/static/telegram-search-demo.mp4'])).hexdigest()
probe="import urllib.request,json,hashlib;b='http://127.0.0.1:8099';assert json.load(urllib.request.urlopen(b+'/health'))['status']=='ok';html=urllib.request.urlopen(b+'/').read();assert html.count(b'class=\"subscription-demo-video\"')==2;assert hashlib.sha256(urllib.request.urlopen(b+'/static/telegram-search-demo.mp4').read()).hexdigest()=="+repr(expected)
try:
 for n,s in p['files'].items():(root/n).write_bytes(base64.b64decode(s))
 rebuild()
 for attempt in range(25):
  try:subprocess.run(['docker','exec','kinozhdun_site','python','-c',probe],check=True,capture_output=True);break
  except subprocess.CalledProcessError:
   if attempt==24:raise
   time.sleep(1)
except Exception:
 for n,h in p['before'].items():
  if h is None:(root/n).unlink(missing_ok=True)
  else:shutil.copy2(backup/n,root/n)
 rebuild();raise
print('Second Telegram tutorial published; hashes and two hero videos verified. Backup: '+str(backup))
'''
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 if '--snapshot' in sys.argv:
  result=subprocess.run(SSH+['python3 -c '+shlex.quote(SNAP)],capture_output=True,text=True,encoding='utf-8',check=True)
  (OUT/'production-before.json').write_text(result.stdout,encoding='utf-8')
 before=json.loads((OUT/'production-before.json').read_text(encoding='utf-8'))
 if '--deploy' not in sys.argv:
  for n in SOURCES:print(''.join(difflib.unified_diff(before['sources'][n].splitlines(True),(ROOT/n).read_text(encoding='utf-8').splitlines(True),fromfile='live/'+n,tofile='local/'+n)))
  sys.exit(0)
 payload={'before':before['hashes'],'files':{n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in SOURCES+MEDIA}}
 r=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=240)
 (OUT/'deployment.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8')
 print(r.stdout[-1500:]);print(r.stderr[-600:]);sys.exit(r.returncode)
