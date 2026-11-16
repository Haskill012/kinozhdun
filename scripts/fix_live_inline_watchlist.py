"""Deploy only the persisted watchlist field correction, retaining live changes."""
import base64,json,shlex,subprocess,sys
from inspect_bot_dropdown import ROOT,SSH
out=ROOT/'diagnostics/hero-demo/telegram-share';out.mkdir(parents=True,exist_ok=True)
remote=r'''
import fcntl,hashlib,json,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime
root=Path('/root/kinozhdun');f=root/'bot/handlers/inline.py'
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
s=f.read_text();old='items = json.loads(shared.items_json) if shared.items_json else []';new='items = json.loads(shared.items_snapshot) if shared.items_snapshot else []'
assert s.count(old)==1
backup=Path('/root/kinozhdun-backups')/('inline-watchlist-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True);shutil.copy2(f,backup/'inline.py')
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-bot'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
try:
 f.write_text(s.replace(old,new));rebuild()
 subprocess.run(['docker','exec','kinozhdun_bot','python','-c',"import inspect;from bot.handlers.inline import process_inline_query;assert 'json.loads(shared.items_snapshot)' in inspect.getsource(process_inline_query)"],check=True)
except Exception:
 shutil.copy2(backup/'inline.py',f);rebuild();raise
print('Inline watchlist field fixed and container source verified. Backup: '+str(backup))
'''
if __name__=='__main__':
 r=subprocess.run(SSH+['python3 -c '+shlex.quote(remote)],capture_output=True,text=True,encoding='utf-8',timeout=240)
 (out/'bot-fix-deployment.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8')
 print(r.stdout[-800:]);print(r.stderr[-400:]);sys.exit(r.returncode)
