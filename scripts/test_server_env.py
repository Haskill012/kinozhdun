import subprocess
from pathlib import Path

key = Path.home() / ".ssh" / "kinojdun_codex_deploy"
remote_cmd = (
    "docker run --rm --dns 9.9.9.9 python:3.11-slim "
    'python3 -c "import subprocess, sys; subprocess.run([sys.executable, \'-m\', \'pip\', \'install\', \'imageio-ffmpeg\', \'edge-tts\', \'pillow\', \'yt-dlp\'], check=True); import imageio_ffmpeg; print(\'FFMPEG_EXE:\', imageio_ffmpeg.get_ffmpeg_exe())"'
)
cmd = ["ssh", "-i", str(key), "-o", "BatchMode=yes", "root@62.217.176.12", remote_cmd]
res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print("STDOUT:\n", res.stdout)
print("STDERR:\n", res.stderr)
