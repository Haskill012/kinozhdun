"""Publish only the third hero card and its real recording, with rollback."""
import base64,difflib,json,shlex,subprocess,sys
from inspect_bot_dropdown import ROOT,SSH
from deploy_telegram_search_demo import REMOTE as SEARCH_REMOTE
OUT=ROOT/'diagnostics/hero-demo/telegram-share'
SOURCES=['website/catalog_views.py']
MEDIA=['website/static/telegram-share-demo.'+ext for ext in ('mp4','jpg','vtt')]
REMOTE=SEARCH_REMOTE.replace('telegram-search-demo','telegram-share-demo').replace('==2','==3').replace('Second Telegram','Third Telegram').replace('two hero','three hero')
SNAP="import json,hashlib;from pathlib import Path;r=Path('/root/kinozhdun');names="+repr(SOURCES+MEDIA)+";print(json.dumps({'hashes':{n:hashlib.sha256((r/n).read_bytes()).hexdigest() if (r/n).exists() else None for n in names},'sources':{n:(r/n).read_text() for n in "+repr(SOURCES)+"}}))"
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 if '--snapshot' in sys.argv:
  r=subprocess.run(SSH+['python3 -c '+shlex.quote(SNAP)],capture_output=True,text=True,encoding='utf-8',check=True)
  (OUT/'production-before.json').write_text(r.stdout,encoding='utf-8')
 before=json.loads((OUT/'production-before.json').read_text(encoding='utf-8'))
 if '--deploy' not in sys.argv:
  for n in SOURCES:print(''.join(difflib.unified_diff(before['sources'][n].splitlines(True),(ROOT/n).read_text(encoding='utf-8').splitlines(True),fromfile='live/'+n,tofile='local/'+n)))
  sys.exit(0)
 payload={'before':before['hashes'],'files':{n:base64.b64encode((ROOT/n).read_bytes()).decode() for n in SOURCES+MEDIA}}
 r=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=240)
 (OUT/'deployment.log').write_text(r.stdout+'\n'+r.stderr,encoding='utf-8');print(r.stdout[-900:]);print(r.stderr[-400:]);sys.exit(r.returncode)
