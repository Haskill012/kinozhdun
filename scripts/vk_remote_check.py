"""Read-only VK checks from production; credentials travel via encrypted SSH stdin."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import Settings

REMOTE = r'''
import json, sys
from urllib.request import urlopen, Request
from urllib.parse import urlencode
p = json.load(sys.stdin)
checks = [
    ('users.get', {}, p['user_token']),
    ('account.getAppPermissions', {}, p['user_token']),
    ('wall.get', {'owner_id': -p['group_id'], 'count': 5}, p['user_token']),
    ('photos.getWallUploadServer', {'group_id': p['group_id']}, p['user_token']),
]
for method, params, token in checks:
    params.update(v='5.199', access_token=token)
    try:
        req = Request('https://api.vk.com/method/' + method, data=urlencode(params).encode())
        with urlopen(req, timeout=20) as response:
            data = json.load(response)
        if 'error' in data:
            error = data['error']
            result = {'error_code': error.get('error_code'), 'message': error.get('error_msg')}
        else:
            r = data['response']
            if method == 'photos.getWallUploadServer':
                result = {'upload_available': bool(r.get('upload_url'))}
            elif method == 'wall.get':
                result = {'count': r.get('count'), 'posts': [
                    {'id': item['id'], 'text': item.get('text'),
                     'attachments': [{'type': a['type'], 'url': a.get('link', {}).get('url'),
                                      'photo_id': a.get('photo', {}).get('id')}
                                     for a in item.get('attachments', [])]}
                    for item in r.get('items', [])]}
            elif method == 'users.get':
                result = {'user_token_valid': bool(r)}
            else:
                result = {'permission_mask': r, 'photos': bool(r & 4)}
        print(json.dumps({'method': method, 'result': result}, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'method': method, 'error_type': type(error).__name__}))
'''

if __name__ == '__main__':
    import shlex
    settings = Settings.from_env()
    payload = json.dumps({'group_id': abs(settings.VK_GROUP_ID), 'user_token': settings.VK_USER_TOKEN})
    command = ['ssh', '-i', str(Path.home() / '.ssh/kinojdun_codex_deploy'),
               '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@62.217.176.12',
               'python3 -c ' + shlex.quote(REMOTE)]
    completed = subprocess.run(command, input=payload, text=True, encoding='utf-8', capture_output=True)
    print(completed.stdout)
    if completed.returncode:
        print('SSH check failed; credentials were not printed.')
        sys.exit(completed.returncode)
