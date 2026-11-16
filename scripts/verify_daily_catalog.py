"""Read the live website's quota, new cards and worker status."""
import json,subprocess,sys
from pathlib import Path
CODE=r'''
import json,sqlite3,subprocess,urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
day=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
result={'day_moscow':day,'health':json.load(urllib.request.urlopen('https://kinojdun.ru/health',timeout=20))}
c=sqlite3.connect('file:/root/kinozhdun/data/website.db?mode=ro',uri=True)
result['today_cards']=[json.loads(r[0]) for r in c.execute('select data from catalog where published=? order by position',(day,))]
result['discovery_day']=c.execute("select value from state where key='catalog_discovery_day'").fetchone()
c.close()
result['container']=subprocess.check_output(['docker','inspect','--format','{{.State.Status}}','kinozhdun_site']).decode().strip()
logs=subprocess.check_output(['docker','logs','--since','10m','kinozhdun_site'],stderr=subprocess.STDOUT).decode(errors='replace')
result['traceback_present']='Traceback (most recent call last)' in logs
result['latest_sync_log']=[l for l in logs.splitlines() if 'Website sync finished' in l][-1:]
print(json.dumps(result,ensure_ascii=False))
'''
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 run=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
 'root@62.217.176.12','python3 -'],input=CODE,text=True,encoding='utf-8',capture_output=True,timeout=40,check=True)
 data=json.loads(run.stdout)
 out=Path(__file__).resolve().parents[1]/'diagnostics/daily-catalog-2026-10-06/runtime.json'
 out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in data.items() if k!='today_cards'},ensure_ascii=False))
 print('Cards today by type:',{m:sum(c['media_type']==m for c in data['today_cards']) for m in ('movie','tv')})
