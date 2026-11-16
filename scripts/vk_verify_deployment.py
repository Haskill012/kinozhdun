"""Read-only production verification without exposing credentials."""
from pathlib import Path
import subprocess
import sys

CODE = r'''
import json, sqlite3
from urllib.request import urlopen
from bot.config import Settings
s = Settings.from_env()
print(json.dumps({'mode':s.VK_ATTACHMENT_MODE, 'posting':s.VK_POSTING_ENABLED,
                  'automatic':s.VK_AUTO_PUBLISH,'group_id':s.VK_GROUP_ID,
                  'poll':s.VK_CREATE_POLL,'link_in_comment':s.VK_LINK_IN_COMMENT,
                  'user_token_required':s.VK_ATTACHMENT_MODE == 'photo'}))
db = sqlite3.connect('data/kinozhdun.db')
db.row_factory = sqlite3.Row
rows = db.execute('SELECT title,vk_post_id,status,event_type,tmdb_id FROM vk_posts ORDER BY id DESC LIMIT 5').fetchall()
print(json.dumps({'journal':[dict(row) for row in rows]},ensure_ascii=False))
with urlopen('https://kinojdun.ru/health',timeout=15) as response:
    print(json.dumps({'site_http':response.status,'site_ok':json.load(response).get('ok')}))
'''

if __name__ == '__main__':
    command = ['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
               'root@62.217.176.12','docker exec -i kinozhdun_bot python -']
    result = subprocess.run(command,input=CODE,text=True,encoding='utf-8',capture_output=True)
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    print(result.stdout)
    if result.returncode:
        print(result.stderr)
    raise SystemExit(result.returncode)
