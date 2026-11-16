"""Enable independent text-only VK posts after one real queue publication succeeds."""
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REMOTE = r'''
import json, sys, shutil, subprocess
from pathlib import Path
from datetime import datetime
root = Path('/root/kinozhdun')
files = json.load(sys.stdin)
assert set(files) == {'bot/config.py', 'bot/services/vk_publisher.py'}
backup = Path('/root/kinozhdun-backups') / ('vk-text-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True, mode=0o700)
for name in list(files) + ['.env']:
    target = backup / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / name, target)
for name, content in files.items():
    (root / name).write_text(content, encoding='utf-8')
env = root / '.env'
def configure(automatic):
    updates = {'VK_ATTACHMENT_MODE': 'text', 'VK_AUTO_PUBLISH': str(automatic).lower(),
               'VK_POSTING_ENABLED': 'true', 'VK_CREATE_POLL': 'false', 'VK_LINK_IN_COMMENT': 'false'}
    lines = [line for line in env.read_text().splitlines() if line.split('=',1)[0].strip() not in updates]
    env.write_text('\n'.join(lines + [k + '=' + v for k,v in updates.items()]) + '\n')
    env.chmod(0o600)
configure(False)
subprocess.run(['docker','compose','build','kinozhdun-bot'],cwd=root,check=True)
subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
trial = r"""
import asyncio, json
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from bot.config import Settings
from bot.scheduler.jobs import check_vk_feed_job
async def main():
    settings = Settings.from_env()
    assert settings.VK_ATTACHMENT_MODE == 'text'
    settings.VK_AUTO_PUBLISH = True
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        before = (await conn.execute(text('SELECT coalesce(max(id),0) FROM vk_posts'))).scalar()
    await check_vk_feed_job(async_sessionmaker(engine, expire_on_commit=False), settings)
    async with engine.connect() as conn:
        row = (await conn.execute(text('SELECT id,title,vk_post_id,status FROM vk_posts ORDER BY id DESC LIMIT 1'))).mappings().first()
    assert row and row['id'] > before and row['status'] == 'published' and row['vk_post_id'], 'Queue publication failed; automatic mode remains disabled'
    print(json.dumps({'title':row['title'],'post_id':row['vk_post_id'],'status':row['status'],
        'url':f"https://vk.ru/wall-{abs(settings.VK_GROUP_ID)}_{row['vk_post_id']}"},ensure_ascii=False),flush=True)
    await engine.dispose()
asyncio.run(main())
"""
subprocess.run(['docker','exec','-i','kinozhdun_bot','python','-'],input=trial,text=True,check=True)
configure(True)
subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
print('VK text-only automatic posting enabled. Interval: 6 hours. Backup:', backup)
'''

if __name__ == '__main__':
    files = {name: (ROOT / name).read_text(encoding='utf-8-sig')
             for name in ['bot/config.py', 'bot/services/vk_publisher.py']}
    subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),
                    '-o','BatchMode=yes','-o','ConnectTimeout=10','root@62.217.176.12',
                    'python3 -c ' + shlex.quote(REMOTE)],
                   input=json.dumps(files,ensure_ascii=False),text=True,encoding='utf-8',check=True)
