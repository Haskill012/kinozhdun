"""Trim real Playwright recordings into a reusable subscription walkthrough.

The manifest specifies source recordings and time ranges. This script never
generates or substitutes website screens or Telegram messages.
"""
import argparse
import json
import subprocess
from pathlib import Path


def build(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    data = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    root = Path(__file__).resolve().parent.parent
    ffmpeg = root / data['ffmpeg']
    work = manifest_path.parent / 'edit'
    work.mkdir(exist_ok=True)
    subtitles = ['WEBVTT', '']
    elapsed = 0
    clips = []
    def stamp(seconds):
        ms = round(seconds * 1000)
        return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'
    for i, scene in enumerate(data['scenes']):
        text = work / f'caption-{i}.txt'
        text.write_text(scene['caption'], encoding='utf-8')
        relative_text = text.relative_to(root).as_posix()
        clip = work / f'clip-{i}.mp4'
        vf = (scene['filter'] + ',setsar=1,drawbox=x=0:y=720:w=1280:h=80:color=0x111312:t=fill,'
              f"drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':textfile='{relative_text}':fontsize=32:fontcolor=white:x=(w-tw)/2:y=744")
        subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-ss', str(scene['start']),
                        '-i', str(root / scene['source']), '-t', str(scene['duration']),
                        '-vf', vf, '-an', '-r', '25', '-c:v', 'libx264', '-preset', 'fast',
                        '-crf', '21', '-pix_fmt', 'yuv420p', str(clip)], cwd=root, check=True)
        clips.append(clip)
        subtitles.extend([f'{stamp(elapsed)} --> {stamp(elapsed + scene["duration"])}', scene['caption'], ''])
        elapsed += scene['duration']
    concat = work / 'concat.txt'
    concat.write_text(''.join("file '" + clip.as_posix() + "'\n" for clip in clips), encoding='utf-8')
    target = root / 'website/static/subscription-demo.mp4'
    subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                    '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(target)], check=True)
    subprocess.run([str(ffmpeg), '-y', '-loglevel', 'error', '-ss', '7.8', '-i', str(target),
                    '-frames:v', '1', '-q:v', '2', str(target.with_suffix('.jpg'))], check=True)
    target.with_suffix('.vtt').write_text('\n'.join(subtitles), encoding='utf-8')
    print(json.dumps({'video': str(target), 'seconds': elapsed, 'bytes': target.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest')
    build(parser.parse_args().manifest)
