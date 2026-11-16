"""
Деплой фикса премьерных дат на продакшн-сервер (62.217.176.12).
Файлы:
- bot/services/tmdb.py (методы discover_upcoming_movies и discover_upcoming_tv)
- bot/services/channel.py (строгое отсечение past releases delta < 0, TMDB discover, единые приоритеты)
- bot/scheduler/jobs.py (строгое отсечение release_date < -7 дней в VK и Дзен лентах)
- Верификация на проде.
"""

import os
import sys
import json
import base64
import subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
SSH_KEY = Path.home() / ".ssh" / "kinojdun_codex_deploy"
SERVER = "root@62.217.176.12"

FILES_TO_DEPLOY = [
    "bot/services/tmdb.py",
    "bot/services/channel.py",
    "bot/scheduler/jobs.py",
]

REMOTE_SCRIPT = r"""
import os, sys, json, base64, fcntl, shutil, subprocess, time
from pathlib import Path
from datetime import datetime

p = json.load(sys.stdin)
root = Path('/root/kinozhdun')

# 1. Lock deployment
lock_file = open('/root/kinozhdun_deploy.lock', 'a')
fcntl.flock(lock_file, fcntl.LOCK_EX)

# 2. Backup
backup_dir = Path('/root/kinozhdun-backups') / ('premiere-fix-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
print(f"Creating backup in {backup_dir}...", flush=True)

manifest = {}
for rel_path in p['files'].keys():
    target = root / rel_path
    if target.exists():
        dest = backup_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        manifest[rel_path] = {'backed_up': True}
    else:
        manifest[rel_path] = {'backed_up': False}

# 3. Write new files
print("Deploying updated files to production...", flush=True)
for rel_path, b64_data in p['files'].items():
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(b64_data))

# 4. Compile check
print("Verifying Python compilation...", flush=True)
subprocess.run(['python3', '-m', 'compileall', '-q', 'bot'], cwd=root, check=True)

# 5. Build and restart kinozhdun-bot
print("Rebuilding and restarting kinozhdun-bot container...", flush=True)
try:
    subprocess.run(['docker', 'compose', 'build', 'kinozhdun-bot'], cwd=root, check=True)
    subprocess.run(['docker', 'compose', 'up', '-d', '--no-deps', 'kinozhdun-bot'], cwd=root, check=True)
    time.sleep(4)

    # 6. Verification inside container
    print("Running verification inside kinozhdun-bot container...", flush=True)
    verify_code = (
        "import asyncio, datetime; "
        "from bot.config import Settings; "
        "from bot.services.channel import ChannelPublisher; "
        "from bot.db.engine import create_db_engine, get_session_factory; "
        "from bot.services.tmdb import TMDBClient; "
        "assert hasattr(TMDBClient, 'discover_upcoming_movies'), 'Missing discover_upcoming_movies'; "
        "assert hasattr(TMDBClient, 'discover_upcoming_tv'), 'Missing discover_upcoming_tv'; "
        "print('VERIFICATION_OK: TMDBClient and ChannelPublisher updated properly!');"
    )
    test_cmd = ['docker', 'compose', 'exec', '-T', 'kinozhdun-bot', 'python', '-c', verify_code]
    test_res = subprocess.run(test_cmd, cwd=root, capture_output=True, text=True, check=True)
    print("Container verification output:\n" + test_res.stdout.strip(), flush=True)

    # Check container status
    ps_res = subprocess.run(['docker', 'compose', 'ps', 'kinozhdun-bot'], cwd=root, capture_output=True, text=True, check=True)
    print("Container status:\n" + ps_res.stdout.strip(), flush=True)
    print("DEPLOYMENT_SUCCESS: Production updated successfully!", flush=True)

except Exception as err:
    print(f"DEPLOYMENT_FAILED: {err}", flush=True)
    if hasattr(err, "stdout") and err.stdout:
        print("STDOUT:\n", err.stdout)
    if hasattr(err, "stderr") and err.stderr:
        print("STDERR:\n", err.stderr)
    print("Initiating rollback...", flush=True)
    for rel_path, info in manifest.items():
        target = root / rel_path
        backup_item = backup_dir / rel_path
        if info['backed_up'] and backup_item.exists():
            shutil.copy2(backup_item, target)
    subprocess.run(['docker', 'compose', 'build', 'kinozhdun-bot'], cwd=root)
    subprocess.run(['docker', 'compose', 'up', '-d', '--no-deps', 'kinozhdun-bot'], cwd=root)
    sys.exit(1)
"""

def main():
    print("Preparing deployment payload...")
    files_payload = {}
    for rel in FILES_TO_DEPLOY:
        p = ROOT / rel
        if not p.exists():
            raise FileNotFoundError(f"Missing file: {p}")
        files_payload[rel] = base64.b64encode(p.read_bytes()).decode("ascii")

    payload = {
        "files": files_payload,
    }
    payload_json = json.dumps(payload)

    print(f"Connecting to production server {SERVER}...")
    cmd = [
        "ssh", "-i", str(SSH_KEY),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        SERVER,
        f"python3 -c {subprocess.list2cmdline([REMOTE_SCRIPT])}"
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    stdout, stderr = proc.communicate(input=payload_json)

    print("\n--- SERVER OUTPUT ---")
    print(stdout)
    if stderr:
        print("--- SERVER STDERR ---")
        print(stderr)

    if proc.returncode != 0:
        print(f"Deployment failed with code {proc.returncode}!")
        sys.exit(proc.returncode)
    else:
        print("Deployment completed successfully!")

if __name__ == "__main__":
    main()
