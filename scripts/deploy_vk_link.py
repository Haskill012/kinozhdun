"""Targeted VK deployment with backups; secrets go only through SSH stdin."""
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.config import Settings

FILES = ["bot/config.py", "bot/db/models.py", "bot/db/repositories.py",
         "bot/scheduler/jobs.py", "bot/services/vk_client.py",
         "bot/services/vk_publisher.py", "bot/services/vk_spintax.py",
         "scripts/vk_tool.py", "website/social_images.py", "website/views.py", "website/__main__.py"]
SSH = ["ssh", "-i", str(Path.home() / ".ssh/kinojdun_codex_deploy"),
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@62.217.176.12"]
REMOTE = r'''
import json, sys, shutil, sqlite3, tarfile, subprocess
from pathlib import Path
from datetime import datetime
p = json.load(sys.stdin)
root = Path('/root/kinozhdun')
backup = Path('/root/kinozhdun-backups') / ('vk-link-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, mode=0o700)
for name in p['files'] + ['.env']:
    src = root / name
    if src.exists():
        dst = backup / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
db = root / 'data/kinozhdun.db'
with sqlite3.connect(db) as source, sqlite3.connect(backup / 'kinozhdun.db') as target:
    source.backup(target)
with tarfile.open('/tmp/kinojdun-vk-link.tar.gz') as archive:
    for name in p['files']:
        member = archive.getmember(name)
        if not member.isfile():
            raise RuntimeError('Not a regular file')
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive.extractfile(member).read())
updates = p['env']
envfile = root / '.env'
lines = envfile.read_text().splitlines()
out = []
for line in lines:
    key = line.split('=', 1)[0].strip()
    if key in updates:
        continue
    out.append(line)
out.extend(key + '=' + value for key, value in updates.items())
envfile.write_text('\n'.join(out) + '\n')
envfile.chmod(0o600)
print('Backup:', backup, flush=True)
subprocess.run(['docker','compose','build','kinozhdun-bot'], cwd=root, check=True)
subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'], cwd=root, check=True)
subprocess.run(['docker','compose','build','kinozhdun-site'], cwd=root, check=True)
subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-site'], cwd=root, check=True)
subprocess.run(['docker','exec','kinozhdun_bot','mkdir','-p','/app/scripts'], check=True)
subprocess.run(['docker','cp',str(root / 'scripts/vk_tool.py'),'kinozhdun_bot:/app/scripts/vk_tool.py'], check=True)
print('VK deployment complete', flush=True)
'''

if __name__ == '__main__':
    settings = Settings.from_env()
    archive_path = ROOT / 'diagnostics/vk-link-deploy.tar.gz'
    archive_path.parent.mkdir(exist_ok=True)
    with tarfile.open(archive_path, 'w:gz') as archive:
        for name in FILES:
            archive.add(ROOT / name, arcname=name)
    subprocess.run(['scp', '-i', SSH[2], '-o', 'BatchMode=yes', str(archive_path),
                    'root@62.217.176.12:/tmp/kinojdun-vk-link.tar.gz'], check=True)
    env = {'VK_ACCESS_TOKEN': settings.VK_ACCESS_TOKEN,
           'VK_GROUP_ID': str(abs(settings.VK_GROUP_ID)), 'VK_USER_TOKEN': '',
           'VK_POSTING_ENABLED': 'true', 'VK_AUTO_PUBLISH': 'false',
           'VK_ATTACHMENT_MODE': 'photo', 'VK_LINK_IN_COMMENT': 'false', 'VK_CREATE_POLL': 'false'}
    payload = json.dumps({'files': FILES, 'env': env})
    subprocess.run(SSH + ['python3 -c ' + shlex.quote(REMOTE)],
                   input=payload, text=True, encoding='utf-8', check=True)
