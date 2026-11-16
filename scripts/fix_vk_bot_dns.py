import shlex, subprocess
from inspect_bot_dropdown import SSH

CODE=r'''
import fcntl,shutil,subprocess,time
from pathlib import Path
from datetime import datetime
root=Path('/root/kinozhdun');p=root/'docker-compose.yml'
lock=open('/root/kinozhdun_deploy.lock','a');fcntl.flock(lock,fcntl.LOCK_EX)
s=p.read_text();anchor='    container_name: kinozhdun_vk_bot\n'
assert s.count(anchor)==1
backup=Path('/root/kinozhdun-backups')/('vk-dns-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700);shutil.copy2(p,backup/p.name)
s=s.replace(anchor,anchor+'    dns:\n      - 9.9.9.9\n      - 149.112.112.112\n')
try:
 p.write_text(s)
 subprocess.run(['docker','compose','config','--quiet'],cwd=root,check=True)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-vk-bot'],cwd=root,check=True)
 print('VK bot DNS changed to the same resolvers as the site. Backup: '+str(backup))
except Exception:
 shutil.copy2(backup/p.name,p)
 subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-vk-bot'],cwd=root,check=True)
 raise
'''
if __name__=='__main__':
    result=subprocess.run(SSH+['python3 -c '+shlex.quote(CODE)],text=True,capture_output=True,encoding='utf-8',timeout=60)
    print(result.stdout);print(result.stderr);raise SystemExit(result.returncode)
