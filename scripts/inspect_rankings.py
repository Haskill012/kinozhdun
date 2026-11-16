"""Save the live catalogue and ranking sources without exposing configuration."""
import json
import subprocess
import sys
from pathlib import Path
from inspect_bot_dropdown import ROOT, SSH

CODE = r'''
import json,sqlite3,subprocess
from pathlib import Path
root=Path('/root/kinozhdun')
c=sqlite3.connect('file:'+str(root/'data/website.db')+'?mode=ro',uri=True)
cards=[json.loads(r[0]) for r in c.execute('select data from catalog where published is not null')]
files=['website/home_state.py','website/catalog_views.py','website/editor.py']
print(json.dumps({'cards':cards,'sources':{n:(root/n).read_text() for n in files},
 'state':dict(c.execute("select key,value from state where key in ('last_sync','sync_error','ranking_trends')"))},ensure_ascii=False))
'''
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result=subprocess.run(SSH+['python3 -'],input=CODE,text=True,encoding='utf-8',capture_output=True,timeout=40,check=True)
    data=json.loads(result.stdout)
    out=ROOT/'diagnostics/rankings-2026-10-07';out.mkdir(parents=True,exist_ok=True)
    (out/'before.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Cards:',len(data['cards']),'State:',data['state'])
    for item in sorted(data['cards'],key=lambda t:float(t.get('popularity') or 0),reverse=True)[:16]:
        print(item['key'],item['title'],item.get('popularity'),item.get('first_release'),item.get('season_premiere'))
    print('Sources:',{n:'same' if (ROOT/n).read_text(encoding='utf-8')==s else 'differs' for n,s in data['sources'].items()})
