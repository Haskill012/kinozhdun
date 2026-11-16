"""Read safe attachment metadata and record the user's visual verification of post 11."""
from pathlib import Path
import subprocess
import sys

CODE = r'''
import asyncio, json, sqlite3
from bot.config import Settings
from bot.services.vk_client import VKClient

async def main():
    s = Settings.from_env()
    assert abs(s.VK_GROUP_ID) == 242059739
    assert not s.VK_AUTO_PUBLISH
    client = VKClient(s.VK_ACCESS_TOKEN, s.VK_GROUP_ID)
    try:
        result = await client.api_call('wall.getById', {'posts':'-242059739_11'})
        posts = result if isinstance(result, list) else result.get('items', [])
        safe = []
        for post in posts:
            if int(post.get('id', 0)) != 11:
                continue
            attachments = []
            for a in post.get('attachments', []):
                item = {'type':a.get('type')}
                if a.get('type') == 'photo':
                    p = a.get('photo', {})
                    item.update(owner_id=p.get('owner_id'), id=p.get('id'))
                attachments.append(item)
            safe.append({'id':post['id'], 'owner_id':post.get('owner_id'), 'attachments':attachments})
        print(json.dumps({'api_posts':safe}, ensure_ascii=False))
    except Exception:
        print(json.dumps({'api_read':'unavailable with community token; visual confirmation retained'}))
    finally:
        await client.close()
    db = sqlite3.connect('data/kinozhdun.db')
    rows = db.execute('SELECT id,status FROM vk_posts WHERE vk_post_id=11 AND tmdb_id=2734 AND event_type=?', ('miniapp_photo_trial',)).fetchall()
    assert len(rows) == 1, 'Expected one trial journal row'
    db.execute('UPDATE vk_posts SET status=? WHERE id=?', ('published',rows[0][0]))
    db.commit()
    print(json.dumps({'post_id':11, 'status':'published', 'confirmation':'user screenshot and exact post URL', 'automatic':s.VK_AUTO_PUBLISH}))

asyncio.run(main())
'''

if __name__ == '__main__':
    result = subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),
        '-o','BatchMode=yes','-o','ConnectTimeout=10','root@62.217.176.12',
        'docker exec -i kinozhdun_bot python -'],input=CODE,text=True,encoding='utf-8',capture_output=True)
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    print(result.stdout)
    if result.returncode:
        print(result.stderr)
    raise SystemExit(result.returncode)
