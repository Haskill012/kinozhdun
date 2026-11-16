"""Inspect then deploy website quota and discovery changes; preserve bot deployment."""
import hashlib, json, subprocess, sys, difflib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'diagnostics/daily-catalog-2026-10-06'
FILES=['website/__main__.py','website/editor.py']
SSH=['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
     '-o','ConnectTimeout=10','root@62.217.176.12','python3 -']
READ="import json;from pathlib import Path;print(json.dumps({n:(Path('/root/kinozhdun')/n).read_text() for n in "+repr(FILES)+"}))"
REMOTE=r'''
import fcntl,hashlib,json,shutil,sqlite3,subprocess,sys
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
assert set(p['files'])=={'website/__main__.py','website/editor.py'}
for n in p['files']:
 assert hashlib.sha256((root/n).read_text().encode()).hexdigest()==p['before'][n], 'Concurrent source change'
backup=Path('/root/kinozhdun-backups')/('daily-catalog-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
for name in list(p['files'])+['.env']:
 target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
c=sqlite3.connect(root/'data/website.db');destination=sqlite3.connect(backup/'website.db');c.backup(destination);destination.close();c.close()
for n,t in p['files'].items():(root/n).write_text(t)
env=root/'.env';lines=[l for l in env.read_text().splitlines() if not l.startswith('SITE_DAILY_CARDS=')]
env.write_text('\n'.join(lines+['SITE_DAILY_CARDS=30'])+'\n');env.chmod(0o600)
try:
 subprocess.run(['python3','-m','compileall','-q','website'],cwd=root,check=True)
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 # Force a fresh discovery pass; keep per-day quota and all published cards.
 c=sqlite3.connect(root/'data/website.db');c.execute("delete from state where key='catalog_discovery_day'");c.commit();c.close()
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
except Exception:
 for n in list(p['files'])+['.env']:shutil.copy2(backup/n,root/n)
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
 raise
print('Daily quota: 30. Backup: '+str(backup),flush=True)
'''

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(parents=True,exist_ok=True)
 result=subprocess.run(SSH,input=READ,text=True,encoding='utf-8',capture_output=True,timeout=30,check=True)
 before=json.loads(result.stdout)
 files={n:(ROOT/n).read_text(encoding='utf-8') for n in FILES}
 # Keep unrelated local RSS work out of this deployment.
 source=before['website/__main__.py']
 changes=[('from website.content import Store\n','from website.content import Store, today\n'),
          ('"daily_cards": max(1, min(10, int(os.getenv("SITE_DAILY_CARDS", "3")))),',
           '"daily_cards": max(1, min(100, int(os.getenv("SITE_DAILY_CARDS", "30")))),'),
          ('            "catalog_selected": store.state("catalog_selected"),',
           '            "daily_cards_limit": config.get("daily_cards", 30),\n'
           '            "cards_added_today": int(store.state("cards_published:" + today().isoformat()) or 0),\n'
           '            "catalog_selected": store.state("catalog_selected"),')]
 for old,new in changes:
  assert source.count(old)==1, 'Unexpected production main source'
  source=source.replace(old,new)
 files['website/__main__.py']=source
 (OUT/'before-sources.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
 diff=''.join(''.join(difflib.unified_diff(before[n].splitlines(True),files[n].splitlines(True),fromfile=n+' server',tofile=n+' local')) for n in FILES)
 (OUT/'deployment.diff').write_text(diff,encoding='utf-8')
 if '--deploy' not in sys.argv:
  print(diff);sys.exit(0)
 payload={'files':files,'before':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in before.items()}}
 run=subprocess.run(
  SSH[:-1]+['python3 -c '+__import__('shlex').quote(REMOTE)],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=180)
 (OUT/'deployment.txt').write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
 print(run.stdout);print('Deployment exit:',run.returncode)
 sys.exit(run.returncode)
