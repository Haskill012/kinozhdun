"""Read-only verification of the published three-year backfill."""
import json
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

CODE = r'''
import json,sqlite3,urllib.request
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
c=sqlite3.connect('file:/root/kinozhdun/data/website.db?mode=ro',uri=True)
cards=[json.loads(r[0]) for r in c.execute('select data from catalog where published is not null')]
keys={item['key'] for item in cards}
paths=['/','/catalog','/movies','/series','/title/movie/693134','/title/movie/1022789','/title/movie/533535','/title/tv/119051','/title/tv/93405']
def check(path):
 response=urllib.request.urlopen('https://kinojdun.ru'+path,timeout=25)
 html=response.read().decode()
 assert response.status==200,path
 if path=='/':assert 'Громкие фильмы последних трёх лет' in html and 'Популярные сериалы и новые сезоны' in html
 return {'path':path,'status':response.status,'bytes':len(html.encode())}
pages=list(ThreadPoolExecutor(4).map(check,paths))
images=[item['poster'] for item in cards if item.get('poster')][:8]
def image(url):
 try:
  response=urllib.request.urlopen(url,timeout=25)
  assert response.headers.get('Content-Type','').startswith('image/'),url
  return {'url':url,'status':response.status}
 except Exception as exc:
  return {'url':url,'error':str(exc)}
image_statuses=list(ThreadPoolExecutor(4).map(image,images))
assert len(keys)==len(cards)
required={'movie:693134','movie:1022789','movie:533535','tv:119051','tv:93405'}
assert required<=keys,required-keys
print(json.dumps({'count':len(cards),'by_type':dict(Counter(item['media_type'] for item in cards)),
 'missing_description':sum(not item.get('overview') for item in cards),
 'missing_poster':sum(not item.get('poster') for item in cards),
 'pages':pages,'sample_posters':image_statuses,'required_hits_present':True,
 'health':json.load(urllib.request.urlopen('https://kinojdun.ru/health',timeout=25))},ensure_ascii=False))
'''
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result = subprocess.run(SSH + ['python3 -'], input=CODE, text=True,
                            encoding='utf-8', capture_output=True, timeout=100)
    if result.returncode:
        print(result.stderr[-2500:])
        sys.exit(result.returncode)
    report = json.loads(result.stdout)
    (ROOT / 'diagnostics/recent-catalog-2026-10-07/verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
