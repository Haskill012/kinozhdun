"""Verify every imported page, sitemap inclusion and crawlable catalogue links."""
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

CODE = r'''
import json,sys,urllib.request,xml.etree.ElementTree as ET,html as html_module,sqlite3
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
cards=json.load(sys.stdin);base='https://kinojdun.ru'
class Tags(HTMLParser):
 def __init__(self):
  super().__init__();self.meta={};self.canonical=None;self.links=set();self.heading='';self.title='';self.in_h1=False;self.in_title=False;self.in_schema=False;self.schema_text='';self.schemas=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='meta' and a.get('name'):self.meta[a['name']]=a.get('content','')
  if tag=='link' and a.get('rel')=='canonical':self.canonical=a.get('href')
  if tag=='a' and a.get('href'):self.links.add(a['href'])
  if tag=='h1':self.in_h1=True
  if tag=='title':self.in_title=True
  if tag=='script' and a.get('type')=='application/ld+json':self.in_schema=True;self.schema_text=''
 def handle_data(self,data):
  if self.in_h1:self.heading+=data
  if self.in_title:self.title+=data
  if self.in_schema:self.schema_text+=data
 def handle_endtag(self,tag):
  if tag=='h1':self.in_h1=False
  if tag=='title':self.in_title=False
  if tag=='script' and self.in_schema:
   self.schemas.append(json.loads(self.schema_text));self.in_schema=False
def fetch(path):
 r=urllib.request.urlopen(base+path,timeout=40);assert r.status==200,path
 if path!='/health':assert 'noindex' not in r.headers.get('X-Robots-Tag','').lower(),path
 return r.read().decode()
sitemap=ET.fromstring(fetch('/sitemap.xml'))
locations={e.text for e in sitemap.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc')}
robots=fetch('/robots.txt');assert 'Disallow: /\n' not in robots and base+'/sitemap.xml' in robots
catalog_links=set()
for path in ('/catalog','/movies','/series'):
 tags=Tags();tags.feed(fetch(path));catalog_links.update(tags.links)
def verify(card):
 path=f"/title/{card['media_type']}/{card['id']}";url=base+path
 assert url in locations,('missing-sitemap',path)
 assert path in catalog_links,('no-crawlable-internal-link',path)
 document=fetch(path);tags=Tags();tags.feed(document)
 assert tags.canonical==url,('canonical',path)
 assert 'noindex' not in tags.meta.get('robots','').lower(),('robots',path)
 assert 'index' in tags.meta.get('robots',''),('missing-index',path)
 assert tags.heading==card['title'],('heading',path)
 assert card['title'] in tags.title and card['first_release'][:4] in tags.title,('title',path)
 assert card['title'] in tags.meta.get('description',''),('description',path)
 assert card['overview'] in html_module.unescape(document),('full-description',path)
 schema=next(s for s in tags.schemas if s.get('@type') in ('Movie','TVSeries'))
 assert schema['url']==url and schema['name']==card['title'] and schema['description']==card['overview'],('schema',path)
 return {'key':card['key'],'title':tags.title,'description':tags.meta['description'],'status':200,'canonical':url}
with ThreadPoolExecutor(4) as pool:results=list(pool.map(verify,cards))
assert len({r['title'] for r in results})==len(cards),'duplicate titles'
assert len({r['description'] for r in results})==len(cards),'duplicate descriptions'
c=sqlite3.connect('file:/root/kinozhdun/data/website.db?mode=ro',uri=True)
live_keys={r[0] for r in c.execute('select key from catalog where published is not null')}
assert {card['key'] for card in cards}<=live_keys
print(json.dumps({'verified_pages':len(results),'catalog_total':len(live_keys),'sitemap_urls':len(locations),
 'all_in_sitemap':True,'all_have_internal_links':True,'all_indexable':True,
 'unique_titles_and_descriptions':True,'health':json.loads(fetch('/health')),'pages':results},ensure_ascii=False))
'''

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    out = ROOT / 'diagnostics/seo-catalog-500-2026-10-07'
    report = json.loads((out / 'import.json').read_text(encoding='utf-8'))
    result = subprocess.run(SSH + ['python3 -c ' + shlex.quote(CODE)],
                            input=json.dumps(report['cards']), text=True, encoding='utf-8',
                            capture_output=True, timeout=600)
    if result.returncode:
        print(result.stderr[-2500:]);sys.exit(result.returncode)
    verification = json.loads(result.stdout)
    (out / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in verification.items() if k != 'pages'}, ensure_ascii=False, indent=2))
