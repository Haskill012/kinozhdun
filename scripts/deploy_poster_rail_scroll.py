"""Publish the scoped rail CSS fix with an exact delta check and rollback."""
import base64,json,shlex,subprocess,sys
from inspect_bot_dropdown import ROOT,SSH
NEEDLE='.tracked-bot-dropdown .bot-dropdown-menu{left:0;right:0;width:100%;min-width:100%}\n'
ADDITION='.poster-rail{overflow-y:hidden}\n.poster-rail .tracked-bot-dropdown .bot-dropdown-menu{top:auto;bottom:calc(100% + 6px)}\n.poster-rail .tracked-bot-dropdown .bot-dropdown-menu:before{top:auto;bottom:-8px}\n'
REMOTE=r'''
import base64,fcntl,hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun');f=root/'website/static/site.css'
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
old=f.read_text();new=base64.b64decode(p['css']).decode()
assert old.count(p['needle'])==1 and old.replace(p['needle'],p['needle']+p['addition'])==new,'Unexpected live CSS changes'
backup=Path('/root/kinozhdun-backups')/('poster-rail-scroll-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True);shutil.copy2(f,backup/'site.css')
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
expected=hashlib.sha256(new.encode()).hexdigest()
probe="import urllib.request,hashlib,json;b='http://127.0.0.1:8099';assert json.load(urllib.request.urlopen(b+'/health'))['status']=='ok';assert hashlib.sha256(urllib.request.urlopen(b+'/static/site.css').read()).hexdigest()=="+repr(expected)
try:
 f.write_text(new);rebuild()
 for attempt in range(25):
  try:subprocess.run(['docker','exec','kinozhdun_site','python','-c',probe],check=True,capture_output=True);break
  except subprocess.CalledProcessError:
   if attempt==24:raise
   time.sleep(1)
except Exception:
 shutil.copy2(backup/'site.css',f);rebuild();raise
print('Poster rail CSS published and served hash verified. Backup: '+str(backup))
'''
if __name__=='__main__':
 p={'css':base64.b64encode((ROOT/'website/static/site.css').read_text(encoding='utf-8').encode()).decode(),'needle':NEEDLE,'addition':ADDITION}
 r=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(p),capture_output=True,text=True,encoding='utf-8',timeout=240)
 (ROOT/'diagnostics/hero-demo/rail-deployment.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8');print(r.stdout[-700:]);print(r.stderr[-300:]);sys.exit(r.returncode)
