import subprocess
from pathlib import Path

key = Path.home() / ".ssh" / "kinojdun_codex_deploy"

test_script = (
    "from bot.config import Settings; "
    "from bot.services.shorts_publisher import ShortsPublisher; "
    "from pathlib import Path; "
    "s = Settings.from_env(); "
    "pub = ShortsPublisher(s); "
    "out_p = Path('/app/output/test_overlay.png'); "
    "pub.render_overlay('КИНОЖДУН | ПРЕМЬЕРА', 'ТЕСТ СЕРВЕРА', 'ТЕСТОВЫЙ ФИЛЬМ', 'NETFLIX • 2026', 'Промо', out_p); "
    "print('REMOTE_CONTAINER_OVERLAY_OK, file size:', out_p.stat().st_size); "
    "out_p.unlink();"
)

remote_cmd = f"cd /root/kinozhdun && docker compose exec -T kinozhdun-bot python -c \"{test_script}\""
res = subprocess.run(["ssh", "-i", str(key), "root@62.217.176.12", remote_cmd], capture_output=True, text=True, timeout=20)
print("STDOUT:\n", res.stdout)
if res.stderr:
    print("STDERR:\n", res.stderr)
