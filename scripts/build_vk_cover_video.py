"""Encode the five mobile cover illustrations as a 25-second silent MP4."""
from pathlib import Path
import json
import subprocess
import imageio_ffmpeg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/imagegen'
names=['01-brand','02-dates','03-series','04-discover','05-start']
ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
parts=[]
for i,name in enumerate(names):
    part=OUT/f'video-part-{i+1}.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-loop','1','-i',str(OUT/f'vk-mobile-{name}.png'),
        '-vf',"scale=1080:1920,setsar=1,zoompan=z='1+0.02*on/150':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,fade=t=in:st=0:d=0.2,fade=t=out:st=4.8:d=0.2",
        '-t','5','-an','-c:v','libx264','-preset','fast','-crf','21','-pix_fmt','yuv420p','-threads','2',str(part)],check=True)
    parts.append(part)
listing=OUT/'video-concat.txt'
listing.write_text('\n'.join("file '"+p.name+"'" for p in parts),encoding='utf-8')
target=OUT/'kinojdun-vk-mobile-cover-25s.mp4'
subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(listing),
    '-c','copy','-movflags','+faststart',str(target)],check=True)
assert target.stat().st_size<20_000_000
subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-i',str(target),'-f','null','-'],check=True)
print(json.dumps({'file':str(target),'duration_seconds':25,'width':1080,'height':1920,'codec':'H.264',
    'size_bytes':target.stat().st_size},ensure_ascii=False))
