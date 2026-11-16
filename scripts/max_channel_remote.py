"""Run a saved MAX administration script inside the production container via SSH."""
import json
import base64
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("\"'")
source = Path(sys.argv[1]).read_text(encoding="utf-8")
code = "MAX_TOKEN = " + repr(env["MAX_BOT_TOKEN"]) + "\n" + source
if len(sys.argv) > 2:
    asset = base64.b64encode(Path(sys.argv[2]).read_bytes()).decode()
    code = "import base64\nAVATAR_BYTES = base64.b64decode(" + repr(asset) + ")\n" + code
run = subprocess.run(
    ["ssh", "-i", str(Path.home() / ".ssh/kinojdun_codex_deploy"),
     "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "root@62.217.176.12",
     "docker exec -i kinozhdun_bot python -"],
    input=code, text=True, encoding="utf-8", capture_output=True, timeout=120,
)
print(run.stdout)
if run.returncode:
    print(run.stderr.replace(env["MAX_BOT_TOKEN"], "[REDACTED]"))
sys.exit(run.returncode)
