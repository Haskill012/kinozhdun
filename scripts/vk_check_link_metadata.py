"""Read public Open Graph metadata from production as a VK crawler; no VK credentials."""
from pathlib import Path
import subprocess
import sys

CODE = r'''
import json
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = {}
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and a.get('property'):
            self.tags[a['property']] = a.get('content')
items = json.load(open('website/catalog_seed.json'))['titles']
item = next(x for x in items if x['title'] == 'Обитель зла')
urls = ['https://kinojdun.ru/title/tv/2734', 'https://kinojdun.ru/title/'+item['media_type']+'/'+str(item['id'])]
for url in urls:
    with urlopen(Request(url,headers={'User-Agent':'VKRobot/1.0'}),timeout=20) as r:
        m=Metadata(); m.feed(r.read().decode())
        page_status=r.status
    image=m.tags['og:image']
    assert urlsplit(image).netloc == 'kinojdun.ru'
    with urlopen(Request(image,headers={'User-Agent':'VKRobot/1.0'}),timeout=20) as r:
        image_status=r.status
        mime=r.headers.get_content_type()
        jpeg=r.read(3)==b'\xff\xd8\xff'
    assert m.tags['og:title'] and m.tags['og:description'] and image_status==200 and jpeg
    print(json.dumps({'url':url,'page_http':page_status,'og':m.tags,'image_http':image_status,
        'image_mime':mime,'jpeg':jpeg},ensure_ascii=False))
'''

if __name__ == '__main__':
    r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),
        '-o','BatchMode=yes','-o','ConnectTimeout=10','root@62.217.176.12',
        'docker exec -i kinozhdun_bot python -'],input=CODE,text=True,encoding='utf-8',capture_output=True)
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    print(r.stdout)
    if r.returncode:
        print(r.stderr)
    raise SystemExit(r.returncode)
