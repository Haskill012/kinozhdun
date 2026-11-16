"""Stop unattended VK posts while image rendering is unverified."""
from pathlib import Path
import subprocess

CODE = r'''
from pathlib import Path
import subprocess
import sqlite3
root = Path('/root/kinozhdun')
path = root / '.env'
lines = [line for line in path.read_text().splitlines() if line.split('=',1)[0].strip() != 'VK_AUTO_PUBLISH']
path.write_text('\n'.join(lines) + '\nVK_AUTO_PUBLISH=false\n')
path.chmod(0o600)
with sqlite3.connect(root / 'data/kinozhdun.db', timeout=30) as db:
    db.execute("UPDATE vk_posts SET status='image_missing' WHERE vk_post_id IN (10,11) AND tmdb_id=2734 AND status IN ('published','verification_pending')")
subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
print('VK_AUTO_PUBLISH=false')
'''
subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
                'root@62.217.176.12','python3 -'],input=CODE,text=True,encoding='utf-8',check=True)
