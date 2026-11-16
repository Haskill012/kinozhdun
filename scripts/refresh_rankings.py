"""Refresh TMDB day/week trends on the live site and save a reviewable snapshot."""
import json
import shlex
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

CODE = r'''
import asyncio,json,sys,types
import aiohttp
from website.content import Store
from website.editor import Editor
from website.__main__ import configuration
source=json.load(sys.stdin)['source']
module=types.ModuleType('website.ranking');exec(compile(source,'website/ranking.py','exec'),module.__dict__)
sys.modules['website.ranking']=module
async def main():
 cfg=configuration();store=Store(cfg['database']);editor=Editor(store,cfg)
 async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30),trust_env=True) as session:
  editor.session=session;await module.refresh_trends(editor,force=True)
 trends=module.load_trends(store)
 cards=store.catalog()
 from website.audience import audience_items
 cards=audience_items(cards,cfg)
 def short(item):return {'key':item['key'],'title':item['title'],'score':round(module.interest_score(item,trends),2)}
 print(json.dumps({'trends':json.loads(store.state('ranking_trends')),
  'top':list(map(short,module.ranked(cards,trends)[:20])),
  'hero':list(map(short,module.hero_selection(cards,trends=trends)))},ensure_ascii=False))
 store.db.close()
asyncio.run(main())
'''
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=subprocess.run(SSH+['docker exec -i kinozhdun_site python -c '+shlex.quote(CODE)],
                          input=json.dumps({'source':(ROOT/'website/ranking.py').read_text(encoding='utf-8')}),
                          text=True,encoding='utf-8',capture_output=True,timeout=120)
    if result.returncode:print(result.stderr[-2000:]);sys.exit(result.returncode)
    report=json.loads(result.stdout)
    out=ROOT/'diagnostics/rankings-2026-10-07';out.mkdir(parents=True,exist_ok=True)
    (out/'preview.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='trends'},ensure_ascii=False,indent=2))
