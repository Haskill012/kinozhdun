"""Verify actual server HTML against ranking output and next-day hero projections."""
import json
import shlex
import subprocess
import sys
from inspect_bot_dropdown import ROOT, SSH

CODE=r'''
import json,urllib.request
from urllib.parse import quote
from datetime import timedelta
from html.parser import HTMLParser
from website.content import Store
from website.__main__ import configuration
from website.audience import audience_items
from website.ranking import ranked,load_trends,hero_selection,interest_score,today,long_running
from website.home_state import hero_projects
from website.catalog_views import tracking_events
cfg=configuration();store=Store(cfg['database']);cards=audience_items(store.catalog(),cfg);trends=load_trends(store)
class Tags(HTMLParser):
 def __init__(self):super().__init__();self.posters=[];self.slides=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a' and a.get('class')=='poster-card':self.posters.append(a['href'])
  if tag=='article' and 'spotlight-slide' in a.get('class','').split():self.slides.append(a['aria-label'])
def get(path):
 r=urllib.request.urlopen('https://kinojdun.ru'+path,timeout=25);assert r.status==200
 tags=Tags();tags.feed(r.read().decode());return tags
events=tracking_events(store,6,cfg)
expected_hero=hero_projects(cards,events,trends=trends)
actual=get('/');assert actual.slides==[item['title'] for item in expected_hero],('hero-mismatch',actual.slides)
assert len(actual.slides)==6 and len(set(actual.slides))==6
forbidden={'tv:2734','tv:5920'}
assert not forbidden&{item['key'] for item in expected_hero}
top=ranked(cards,trends)
assert not forbidden&{item['key'] for item in top[:12]}
for path,media in (('/catalog',None),('/movies','movie'),('/series','tv')):
 expected=ranked([item for item in cards if not media or item['media_type']==media],trends)
 actual=get(path).posters
 assert actual==[f"/title/{item['media_type']}/{item['id']}" for item in expected],('catalog-mismatch',path)
projections=[]
for offset in range(5):
 selected=hero_selection(cards,events,trends=trends,current=today()+timedelta(days=offset))
 assert len(selected)==6 and len({item['key'] for item in selected})==6
 assert not any(long_running(item) for item in selected)
 projections.append({'day':(today()+timedelta(days=offset)).isoformat(),'keys':[item['key'] for item in selected],'titles':[item['title'] for item in selected]})
for a,b in zip(projections,projections[1:]):
 assert a['keys']!=b['keys'],'Daily order is stuck'
 assert set(a['keys'])!=set(b['keys']),'Daily membership is stuck'
assert get('/catalog?q='+quote('Менталист')).posters[0]=='/title/tv/5920'
def short(item):return {'key':item['key'],'title':item['title'],'score':round(interest_score(item,trends),2)}
print(json.dumps({'hero':list(map(short,expected_hero)),'catalog_top':list(map(short,top[:12])),
 'legacy_positions':{key:next(i+1 for i,item in enumerate(top) if item['key']==key) for key in forbidden},
 'five_day_rotation':projections,'catalog_routes_match':True,'search_legacy_still_works':True,
 'ranking_updated_at':json.loads(store.state('ranking_trends'))['updated_at'],
 'ranking_error':store.state('ranking_trends_error'),'health':json.load(urllib.request.urlopen('https://kinojdun.ru/health',timeout=25))},ensure_ascii=False))
store.db.close()
'''
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=subprocess.run(SSH+['docker exec -i kinozhdun_site python -c '+shlex.quote(CODE)],
                          text=True,encoding='utf-8',capture_output=True,timeout=100)
    if result.returncode:print(result.stderr[-2000:]);sys.exit(result.returncode)
    report=json.loads(result.stdout)
    (ROOT/'diagnostics/rankings-2026-10-07/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
