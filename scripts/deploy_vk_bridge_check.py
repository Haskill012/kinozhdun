"""Deploy only the read-only Mini App diagnostic page, with a remote backup."""
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = ['website/static/vk-connect.html', 'website/static/vk-connect.js', 'website/static/vk-post-trial.json', 'website/vk_upload_check.py']
REMOTE = r'''
import json, sys, shutil, subprocess
from pathlib import Path
from datetime import datetime
root = Path('/root/kinozhdun')
payload = json.load(sys.stdin)
allowed = {'website/static/vk-connect.html', 'website/static/vk-connect.js', 'website/static/vk-post-trial.json', 'website/vk_upload_check.py'}
if set(payload) != allowed:
    raise RuntimeError('Unexpected deployment files')
backup = Path('/root/kinozhdun-backups') / ('vk-bridge-check-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, mode=0o700)
entry = root / 'website/__main__.py'
text = entry.read_text(encoding='utf-8')
marker = '    app.router.add_get("/api/search", search)'
if '/api/vk/poster-check' not in text:
    if text.count(marker) != 1:
        raise RuntimeError('Website entry point changed; abort before modifying files')
    shutil.copy2(entry, backup / '__main__.py')
    text = text.replace(marker, marker + "\n    from website.vk_upload_check import upload_check_handler\n    app.router.add_post('/api/vk/poster-check', upload_check_handler(ROOT / 'website' / 'catalog_seed.json'))")
    entry.write_text(text, encoding='utf-8')
for name, content in payload.items():
    path = root / name
    if path.exists():
        shutil.copy2(path, backup / path.name)
    path.write_text(content, encoding='utf-8')
    subprocess.run(['docker', 'cp', str(path), 'kinozhdun_site:/app/' + name], check=True)
subprocess.run(['docker', 'cp', str(entry), 'kinozhdun_site:/app/website/__main__.py'], check=True)
subprocess.run(['docker', 'restart', 'kinozhdun_site'], check=True)
print('Diagnostic page deployed. Backup:', backup)
'''

if __name__ == '__main__':
    payload = {name: (ROOT / name).read_text(encoding='utf-8-sig') for name in FILES}
    subprocess.run(['ssh', '-i', str(Path.home() / '.ssh/kinojdun_codex_deploy'),
                    '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@62.217.176.12',
                    'python3 -c ' + shlex.quote(REMOTE)],
                   input=json.dumps(payload, ensure_ascii=False), text=True, encoding='utf-8', check=True)
