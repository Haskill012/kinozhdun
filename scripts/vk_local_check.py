"""VK diagnostics using Windows curl TLS verification and credentials on stdin."""
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import Settings


def api(method, params, token):
    params = dict(params, v='5.199', access_token=token)
    result = subprocess.run(['curl.exe', '--fail', '--silent', '--show-error', '--max-time', '25',
                             '--data-binary', '@-', 'https://api.vk.com/method/' + method],
                            input=urlencode(params).encode(), capture_output=True)
    if result.returncode:
        raise RuntimeError(f'HTTPS request failed (curl {result.returncode})')
    data = json.loads(result.stdout)
    if 'error' in data:
        e = data['error']
        raise RuntimeError(f"VK error {e.get('error_code')}: {e.get('error_msg')}")
    return data['response']


if __name__ == '__main__':
    settings = Settings.from_env()
    for method, params in [
        ('users.get', {}), ('account.getAppPermissions', {}),
        ('photos.getWallUploadServer', {'group_id': abs(settings.VK_GROUP_ID)}),
        ('wall.get', {'owner_id': -abs(settings.VK_GROUP_ID), 'count': 5}),
    ]:
        try:
            response = api(method, params, settings.VK_USER_TOKEN)
            if method == 'photos.getWallUploadServer':
                response = {'upload_available': bool(response.get('upload_url'))}
            elif method == 'users.get':
                response = {'user_token_valid': bool(response)}
            elif method == 'wall.get':
                response = {'count': response.get('count'), 'posts': [
                    {'id': p['id'], 'text': p.get('text'),
                     'attachments': [{'type': a['type'], 'photo_id': a.get('photo', {}).get('id'),
                                      'url': a.get('link', {}).get('url')}
                                     for a in p.get('attachments', [])]}
                    for p in response.get('items', [])]}
            print(json.dumps({'method': method, 'result': response}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({'method': method, 'error': str(e)}, ensure_ascii=False))
