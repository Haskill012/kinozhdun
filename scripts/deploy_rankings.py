"""Publish only the ranking changes, with source checks, backups and rollback."""
import difflib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

OUT=ROOT/'diagnostics/rankings-2026-10-07'
FILES=['website/ranking.py','website/home_state.py','website/catalog_views.py','website/editor.py','website/search.py']
REMOTE=r'''
import fcntl,json,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
allowed={'website/ranking.py','website/home_state.py','website/catalog_views.py','website/editor.py','website/search.py'}
assert set(p['files'])==allowed
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for name,before in p['before'].items():
 target=root/name;assert (target.read_text() if target.exists() else None)==before,'Concurrent source change: '+name
backup=Path('/root/kinozhdun-backups')/('rankings-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
for name,before in p['before'].items():
 if before is not None:
  target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
try:
 for name,source in p['files'].items():(root/name).write_text(source)
 subprocess.run(['python3','-m','compileall','-q','website'],cwd=root,check=True)
 rebuild()
 for attempt in range(20):
  try:
   html=urllib.request.urlopen('https://kinojdun.ru/',timeout=15).read().decode()
   assert html.count('data-slide=')==6
   subprocess.run(['docker','exec','kinozhdun_site','python','-c','from website.ranking import interest_score, hero_selection; assert callable(interest_score)'],check=True,capture_output=True)
   break
  except Exception:
   if attempt==19:raise
   time.sleep(1)
except Exception:
 for name,before in p['before'].items():
  if before is None:(root/name).unlink(missing_ok=True)
  else:shutil.copy2(backup/name,root/name)
 rebuild();raise
print('Ranking changes deployed. Backup: '+str(backup))
'''

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');OUT.mkdir(parents=True,exist_ok=True)
    read="import json;from pathlib import Path;r=Path('/root/kinozhdun');print(json.dumps({n:(r/n).read_text() if (r/n).exists() else None for n in "+repr(FILES)+"}))"
    run=subprocess.run(SSH+['python3 -'],input=read,text=True,encoding='utf-8',capture_output=True,check=True,timeout=40)
    before=json.loads(run.stdout)
    snapshot=json.loads((OUT/'before.json').read_text(encoding='utf-8'))['sources']
    for name,source in snapshot.items():assert before[name]==source,'Source changed since inspection: '+name
    assert before['website/ranking.py'] is None,'Ranking module already exists; inspect before updating'
    files={name:(ROOT/name).read_text(encoding='utf-8') for name in FILES}
    # Apply only our small search delta to the current server search source.
    source=before['website/search.py']
    changes=[('from website.artwork import artwork, allowed_asset\n','from website.artwork import artwork, allowed_asset\nfrom website.ranking import interest_score, load_trends\n'),
             ('def rank(item, query):','def rank(item, query, trends=None):'),
             ('-float(item.get("popularity") or 0), item["title"])','-interest_score(item, trends), item["title"])'),
             ('    found.sort(key=lambda item: rank(item, query))','    trends = load_trends(store)\n    found.sort(key=lambda item: rank(item, query, trends))'),
             ('        published = self.store.catalog()','        published = self.store.catalog()\n        trends = load_trends(self.store)'),
             ('rank(item, query))[:8]','rank(item, query, trends))[:8]')]
    for old,new in changes:
        assert source.count(old)==(2 if old=='rank(item, query))[:8]' else 1),'Unexpected search source: '+old
        source=source.replace(old,new)
    files['website/search.py']=source
    (OUT/'deployment-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'deployment.diff').write_text(''.join(''.join(difflib.unified_diff((before[name] or '').splitlines(True),files[name].splitlines(True),fromfile=name+' server',tofile=name+' new')) for name in FILES),encoding='utf-8')
    run=subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps({'before':before,'files':files}),
                       text=True,encoding='utf-8',capture_output=True,timeout=300)
    (OUT/'deployment.txt').write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
    print(run.stdout[-1200:]);print(run.stderr[-500:]);sys.exit(run.returncode)
