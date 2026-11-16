"""Enable the proven text-only schedule without creating an immediate post."""
from pathlib import Path
import subprocess
import shlex
CODE = r'''
from pathlib import Path
from datetime import datetime
import shutil,subprocess
root=Path('/root/kinozhdun')
env=root/'.env'
backup=Path('/root/kinozhdun-backups')/('vk-text-schedule-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(parents=True,mode=0o700)
shutil.copy2(env,backup/'.env')
updates={'VK_ATTACHMENT_MODE':'text','VK_AUTO_PUBLISH':'true','VK_POSTING_ENABLED':'true',
         'VK_CREATE_POLL':'false','VK_LINK_IN_COMMENT':'false'}
lines=[x for x in env.read_text().splitlines() if x.split('=',1)[0].strip() not in updates]
env.write_text('\n'.join(lines+[k+'='+v for k,v in updates.items()])+'\n'); env.chmod(0o600)
subprocess.run(['docker','compose','up','-d','--no-deps','kinozhdun-bot'],cwd=root,check=True)
print('Text schedule enabled; no immediate wall.post; interval 6 hours. Backup:',backup)
'''
if __name__=='__main__':
    subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
        '-o','ConnectTimeout=10','root@62.217.176.12','python3 -c '+shlex.quote(CODE)],check=True)
