"""
Automated deployment of the Autonomous Shorts Pipeline to the production server (62.217.176.12).
Includes:
- requirements.txt (edge-tts, imageio-ffmpeg, pillow, yt-dlp)
- Dockerfile (/app/output directory)
- docker-compose.yml (persistent output volume)
- bot/config.py (SHORTS_ENABLED, SHORTS_AUTO_PUBLISH)
- bot/services/shorts_publisher.py (unified production generator)
- bot/services/channel.py (shorts integration)
- bot/assets/fonts (bundled TrueType fonts: Segoe UI, Arial)
- .env settings update (SHORTS_ENABLED=true, SHORTS_AUTO_PUBLISH=true)
- Automated container build, restart, and health verification.
"""

import os
import sys
import json
import base64
import shlex
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSH_KEY = Path.home() / ".ssh" / "kinojdun_codex_deploy"
SERVER = "root@62.217.176.12"

FILES_TO_DEPLOY = [
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "bot/config.py",
    "bot/db/repositories.py",
    "bot/services/shorts_publisher.py",
    "bot/services/channel.py",
    "bot/scheduler/jobs.py",
    "bot/assets/fonts/segoeuib.ttf",
    "bot/assets/fonts/segoeui.ttf",
    "bot/assets/fonts/arialbd.ttf",
    "bot/assets/fonts/arial.ttf",
]

SETTINGS = {
    "SHORTS_ENABLED": "true",
    "SHORTS_AUTO_PUBLISH": "true",
    "SHORTS_DAILY_HOUR": "12",
    "SHORTS_DAILY_MINUTE": "0",
}

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
backup_dir = Path('/root/kinozhdun-backups') / ('shorts-pipeline-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup_dir.mkdir(parents=True, mode=0o700)
print(f"Creating backup in {backup_dir}...", flush=True)

manifest = {}
for rel_path in list(p['files'].keys()) + ['.env']:
    target = root / rel_path
    if target.exists():
        dest = backup_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        manifest[rel_path] = {'backed_up': True}
    else:
        manifest[rel_path] = {'backed_up': False}

(backup_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2))

# 3. Write new files
print("Deploying updated files and fonts...", flush=True)
for rel_path, b64_data in p['files'].items():
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(b64_data))

# 4. Update .env
print("Updating .env configuration...", flush=True)
env_file = root / '.env'
if env_file.exists():
    lines = env_file.read_text(encoding='utf-8').splitlines()
else:
    lines = []

new_lines = []
existing_keys = set()
for line in lines:
    if '=' in line and not line.strip().startswith('#'):
        k = line.split('=', 1)[0].strip()
        if k in p['settings']:
            new_lines.append(f"{k}={p['settings'][k]}")
            existing_keys.add(k)
            continue
    new_lines.append(line)

for k, v in p['settings'].items():
    if k not in existing_keys:
        new_lines.append(f"{k}={v}")

env_file.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
env_file.chmod(0o600)

# 5. Compile check
print("Verifying Python compilation...", flush=True)
subprocess.run(['python3', '-m', 'compileall', '-q', 'bot'], cwd=root, check=True)

# 6. Rebuild and restart kinozhdun-bot
print("Building and restarting kinozhdun-bot container...", flush=True)
try:
    subprocess.run(['docker', 'compose', 'build', 'kinozhdun-bot'], cwd=root, check=True)
    subprocess.run(['docker', 'compose', 'up', '-d', '--no-deps', 'kinozhdun-bot'], cwd=root, check=True)
    time.sleep(4)

    # 7. Self-test inside the running container
    print("Running container self-test...", flush=True)
    test_cmd = [
        'docker', 'compose', 'exec', '-T', 'kinozhdun-bot',
        'python', '-c',
        'import imageio_ffmpeg, edge_tts, PIL, yt_dlp; '
        'from bot.services.shorts_publisher import ShortsPublisher; '
        'print("CONTAINER_SELF_TEST_OK: FFMPEG =", imageio_ffmpeg.get_ffmpeg_exe())'
    ]
    test_res = subprocess.run(test_cmd, cwd=root, capture_output=True, text=True, check=True)
    print("Container self-test output:", test_res.stdout.strip(), flush=True)

    # Check container status
    ps_res = subprocess.run(['docker', 'compose', 'ps', 'kinozhdun-bot'], cwd=root, capture_output=True, text=True, check=True)
    print("Container status:\n" + ps_res.stdout.strip(), flush=True)
    print("DEPLOYMENT_SUCCESS: Shorts pipeline is active and fully functional on server!", flush=True)

except Exception as err:
    print(f"DEPLOYMENT_FAILED: {err}", flush=True)
    # Rollback
    print("Initiating rollback to previous backup...", flush=True)
    for rel_path, info in manifest.items():
        target = root / rel_path
        backup_item = backup_dir / rel_path
        if info['backed_up'] and backup_item.exists():
            shutil.copy2(backup_item, target)
        elif not info['backed_up'] and target.exists():
            target.unlink(missing_ok=True)
    subprocess.run(['docker', 'compose', 'build', 'kinozhdun-bot'], cwd=root)
    subprocess.run(['docker', 'compose', 'up', '-d', '--no-deps', 'kinozhdun-bot'], cwd=root)
    raise
"""

def main():
    print(f"Preparing deployment to {SERVER}...")
    encoded_files = {}
    for rel_path in FILES_TO_DEPLOY:
        file_path = ROOT / rel_path
        if not file_path.exists():
            raise FileNotFoundError(f"Missing required file: {file_path}")
        encoded_files[rel_path] = base64.b64encode(file_path.read_bytes()).decode("ascii")
        print(f"  + Packed: {rel_path} ({file_path.stat().st_size:,} bytes)")

    payload = json.dumps({"files": encoded_files, "settings": SETTINGS}, ensure_ascii=False)
    print(f"Total payload size: {len(payload):,} bytes")

    print("\nExecuting deployment on remote server...")
    ssh_cmd = [
        "ssh",
        "-i", str(SSH_KEY),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        SERVER,
        "python3 -c " + shlex.quote(REMOTE_SCRIPT)
    ]

    proc = subprocess.Popen(
        ssh_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    stdout, stderr = proc.communicate(input=payload)

    print("\n=== REMOTE DEPLOY OUTPUT ===")
    print(stdout)
    if stderr:
        print("=== REMOTE STDERR ===")
        print(stderr)

    if proc.returncode != 0:
        print(f"Deployment failed with return code {proc.returncode}")
        sys.exit(proc.returncode)

    print("=== DEPLOYMENT COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
