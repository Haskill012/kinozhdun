"""Publish only the subscription walkthrough over a saved live-source snapshot."""
import ast
import base64
import difflib
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

OUT = ROOT / 'diagnostics/hero-demo'
REMOTE = r'''
import base64,fcntl,hashlib,json,shutil,subprocess,sys,time,urllib.request
from datetime import datetime
from pathlib import Path
p=json.load(sys.stdin);root=Path('/root/kinozhdun')
allowed={'website/catalog_views.py','website/__main__.py','website/static/site.css','website/static/site.js'}
assets={'website/static/subscription-demo.mp4','website/static/subscription-demo.jpg','website/static/subscription-demo.vtt'}
assert set(p['files'])==allowed and set(p['assets'])==assets
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
for n,h in p['before'].items():assert hashlib.sha256((root/n).read_bytes()).hexdigest()==h,'Concurrent source change: '+n
backup=Path('/root/kinozhdun-backups')/('subscription-demo-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
existed=[]
for n in allowed|assets:
 if (root/n).exists():
  existed.append(n);target=backup/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,target)
def rebuild():
 subprocess.run(['docker','compose','build','kinozhdun-site'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'],cwd=root,check=True)
probe="""import urllib.request,json
base='http://127.0.0.1:8099'
assert json.load(urllib.request.urlopen(base+'/health'))['status']=='ok'
assert b'subscription-demo-video' in urllib.request.urlopen(base+'/').read()
assert b'c_movie_1294189' in urllib.request.urlopen(base+'/how-to-subscribe?project=movie:1294189').read()
r=urllib.request.urlopen(urllib.request.Request(base+'/static/subscription-demo.mp4',headers={'Range':'bytes=0-1023'}))
assert r.status==206 and len(r.read())==1024
"""
try:
 for n,s in p['files'].items():(root/n).write_text(s,encoding='utf-8')
 for n,s in p['assets'].items():(root/n).write_bytes(base64.b64decode(s))
 subprocess.run(['python3','-m','compileall','-q','website'],cwd=root,check=True)
 rebuild()
 for attempt in range(25):
  try:
   subprocess.run(['docker','exec','kinozhdun_site','python','-c',probe],check=True,capture_output=True);break
  except subprocess.CalledProcessError:
   if attempt==24:raise
   time.sleep(1)
except Exception:
 for n in allowed|assets:
  if n in existed:shutil.copy2(backup/n,root/n)
  else:(root/n).unlink(missing_ok=True)
 rebuild();raise
print('Video hero, project guide and MP4 range delivery deployed. Backup: '+str(backup))
'''


def function_sources(source):
    lines = source.splitlines(True)
    return {node.name: ''.join(lines[node.lineno-1:node.end_lineno])
            for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    before = json.loads((OUT / 'production-before.json').read_text(encoding='utf-8'))
    local = {name: (ROOT/name).read_text(encoding='utf-8') for name in before}
    # Confirm that the catalogue includes only this request's changed functions.
    old, new = function_sources(before['website/catalog_views.py']), function_sources(local['website/catalog_views.py'])
    assert {name for name in new if old.get(name) != new[name]} == {
        'project_page','streaming_home','subscription_demo_available','subscription_help_page','subscription_demo_slide'}
    assert local['website/static/site.css'].startswith(before['website/static/site.css'])
    marker = "document.querySelectorAll('.site-search')"
    assert before['website/static/site.js'].split(marker,1)[1] == local['website/static/site.js'].split(marker,1)[1]
    files = dict(local)
    # Keep all unrelated unfinished local changes in __main__.py out of production.
    start = local['website/__main__.py'].index('    async def subscription_guide(request):')
    end = local['website/__main__.py'].index("    app.router.add_get('/how-to-subscribe', subscription_guide)",start)
    end = local['website/__main__.py'].index('\n',end) + 1
    insertion = local['website/__main__.py'][start:end]
    anchor = '    async def listing(request):'
    assert before['website/__main__.py'].count(anchor) == 1
    files['website/__main__.py'] = before['website/__main__.py'].replace(anchor, insertion + '\n' + anchor)
    for name, source in files.items():
        if name.endswith('.py'): ast.parse(source)
    diff = ''.join(''.join(difflib.unified_diff(before[n].splitlines(True),s.splitlines(True),fromfile=n+' production',tofile=n+' video')) for n,s in files.items())
    (OUT/'deployment.diff').write_text(diff,encoding='utf-8')
    payload = {'files':files,'before':{n:hashlib.sha256(s.encode()).hexdigest() for n,s in before.items()},
               'assets':{f'website/static/subscription-demo.{ext}':base64.b64encode((ROOT/f'website/static/subscription-demo.{ext}').read_bytes()).decode() for ext in ['mp4','jpg','vtt']}}
    if '--deploy' not in sys.argv:
        print('Prepared 4 source files and MP4/JPG/VTT. Diff:',OUT/'deployment.diff')
        sys.exit(0)
    result = subprocess.run(SSH+['python3 -c '+shlex.quote(REMOTE)],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,timeout=240)
    (OUT/'deployment.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    print(result.stdout[-2000:]);print(result.stderr[-1000:]);sys.exit(result.returncode)
