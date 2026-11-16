import subprocess
from pathlib import Path

key = Path.home() / ".ssh" / "kinojdun_codex_deploy"

script = """
import urllib.request, json
from bot.config import Settings
s = Settings.from_env()
api_key = s.TMDB_API_KEY

# Check upcoming movies
url_m = f"https://api.themoviedb.org/3/movie/upcoming?api_key={api_key}&language=ru-RU&page=1"
data_m = json.loads(urllib.request.urlopen(url_m).read())
print("UPCOMING MOVIES:")
for m in data_m.get("results", [])[:10]:
    print(f"- {m.get('title')} (rel={m.get('release_date')}), id={m.get('id')}, vote={m.get('vote_average')}, pop={m.get('popularity')}")

# Check on the air TV
url_tv = f"https://api.themoviedb.org/3/tv/on_the_air?api_key={api_key}&language=ru-RU&page=1"
data_tv = json.loads(urllib.request.urlopen(url_tv).read())
print("ON THE AIR TV:")
for tv in data_tv.get("results", [])[:10]:
    print(f"- {tv.get('name')} (first_air={tv.get('first_air_date')}), id={tv.get('id')}, vote={tv.get('vote_average')}, pop={tv.get('popularity')}")
"""

cmd = ["ssh", "-i", str(key), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@62.217.176.12", "cd /root/kinozhdun && docker compose exec -T kinozhdun-bot python"]
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
stdout, stderr = proc.communicate(input=script)
print("STDOUT:\n", stdout)
if stderr:
    print("STDERR:\n", stderr)
