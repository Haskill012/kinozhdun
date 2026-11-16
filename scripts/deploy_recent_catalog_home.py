"""Deploy only the recent catalogue home collections; preserve other server changes."""
import difflib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

OUT = ROOT / 'diagnostics/recent-catalog-2026-10-07'
REMOTE = r'''
import fcntl,json,shutil,subprocess,sys,time,urllib.request
from pathlib import Path
from datetime import datetime
p=json.load(sys.stdin);root=Path('/root/kinozhdun');name='website/catalog_views.py'
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
assert (root/name).read_text()==p['before'],'Concurrent source change'
backup=Path('/root/kinozhdun-backups')/('recent-catalog-home-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700);shutil.copy2(root/name,backup/'catalog_views.py')
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
try:
 (root/name).write_text(p['after']);rebuild()
 for attempt in range(20):
  try:
   html=urllib.request.urlopen('https://kinojdun.ru/',timeout=15).read().decode()
   assert 'Громкие фильмы последних трёх лет' in html and 'Популярные сериалы и новые сезоны' in html
   break
  except Exception:
   if attempt==19:raise
   time.sleep(1)
except Exception:
 shutil.copy2(backup/'catalog_views.py',root/name);rebuild();raise
print('Recent collections deployed; backup: '+str(backup))
'''

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True, exist_ok=True)
    run = subprocess.run(SSH + ['python3 -'], input="from pathlib import Path;print(Path('/root/kinozhdun/website/catalog_views.py').read_text(),end='')",
                         text=True, encoding='utf-8', capture_output=True, check=True, timeout=40)
    before = run.stdout
    local = (ROOT / 'website/catalog_views.py').read_text(encoding='utf-8')
    start = local.index('    current = today()\n', local.index('def streaming_home('))
    end = local.index('    disc_btn = ', start)
    anchor = '    disc_btn = '
    assert before.count(anchor) == 1
    after = before.replace(anchor, local[start:end] + anchor)
    assert after.count('{anticipated}{changes}{telegram}') == 1
    after = after.replace('{anticipated}{changes}{telegram}', '{anticipated}{recent_collections}{changes}{telegram}')
    (OUT / 'home-before.py').write_text(before, encoding='utf-8')
    (OUT / 'home.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True))), encoding='utf-8')
    result = subprocess.run(SSH + ['python3 -c ' + shlex.quote(REMOTE)], input=json.dumps({'before': before, 'after': after}),
                            text=True, encoding='utf-8', capture_output=True, timeout=300)
    (OUT / 'home-deployment.txt').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
    print(result.stdout[-1600:]);print(result.stderr[-400:]);sys.exit(result.returncode)
