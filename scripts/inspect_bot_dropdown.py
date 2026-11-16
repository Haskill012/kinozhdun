import json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ['website/views.py', 'website/catalog_views.py', 'website/static/site.css', 'website/static/site.js', 'website/__main__.py']
SSH = ['ssh', '-i', str(Path.home()/'.ssh/kinojdun_codex_deploy'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@62.217.176.12']
if __name__ == '__main__':
    code = "import json;from pathlib import Path;print(json.dumps({n:(Path('/root/kinozhdun')/n).read_text() for n in " + repr(FILES) + "}))"
    result = subprocess.run(SSH + ['python3 -'], input=code, text=True, encoding='utf-8', capture_output=True, timeout=30, check=True)
    out = ROOT/'diagnostics/bot-dropdown'
    out.mkdir(parents=True, exist_ok=True)
    (out/'before.json').write_text(result.stdout, encoding='utf-8')
    sources = json.loads(result.stdout)
    for name, source in sources.items():
        print(name, 'identical' if source == (ROOT/name).read_text(encoding='utf-8') else 'differs')
