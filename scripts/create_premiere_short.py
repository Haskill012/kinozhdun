"""
Autonomous Premiere Shorts Generator & Publisher for KinoZhdun.
Standard: 1080x1920 (9:16), 30fps, 24-28s duration, edge_tts neural voiceover,
sidechain audio ducking, kinetic ASS subtitles, branded clean overlay,
automated publishing to Telegram channel and VK Stories / Wall.
"""

import os
import sys
import json
import html
import asyncio
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Tooling paths
sys.path.insert(0, r"C:\Users\cvet7\AppData\Roaming\Python\Python313\site-packages")
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(ROOT / "output" / "social-pilot-2026-10-07" / "tooling"))
sys.path.insert(0, str(ROOT / "output" / "social-pilot-2026-10-07" / "speech-tools"))
import imageio_ffmpeg
import edge_tts

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

def load_env():
    env_file = ROOT / ".env"
    env = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return env

def run_ffmpeg(args, cwd=None):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {res.stderr}")
    return res

def format_ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def render_brand_overlay(badge, hook, title, meta, source, out_path):
    """Renders the standard clean KinoZhdun Shorts overlay (NO countdown/subtag)."""
    font_dir = Path("C:/Windows/Fonts")
    f_badge = ImageFont.truetype(str(font_dir / "segoeuib.ttf"), 30)
    f_hook = ImageFont.truetype(str(font_dir / "segoeuib.ttf"), 48)
    f_title = ImageFont.truetype(str(font_dir / "segoeuib.ttf"), 42)
    f_meta = ImageFont.truetype(str(font_dir / "segoeuib.ttf"), 28)
    f_cta = ImageFont.truetype(str(font_dir / "segoeuib.ttf"), 30)
    f_attr = ImageFont.truetype(str(font_dir / "segoeui.ttf"), 22)

    im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # 1. Top Badge Pill
    bx, by = 64, 85
    bbox = f_badge.getbbox(badge)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pill_box = (bx, by, bx + bw + 44, by + bh + 22)
    radius = (pill_box[3] - pill_box[1]) // 2
    draw.rounded_rectangle(pill_box, radius=radius, fill=(18, 26, 17, 230), outline="#d4fa58", width=2)
    draw.text((bx + 22, by + 10 - bbox[1]), badge, font=f_badge, fill="#d4fa58")

    # 2. Hook line (clean under badge, no 'трейлер за 25 секунд')
    draw.text((64, 185), hook, font=f_hook, fill="#ffffff", stroke_width=3, stroke_fill="#000000")
    draw.line([(64, 280), (1016, 280)], fill=(212, 250, 88, 140), width=2)

    # 3. Video center frame outline
    draw.rectangle((0, 318, 1080, 1226), outline=(212, 250, 88, 40), width=2)

    # 4. Bottom footer
    draw.line([(64, 1540), (1016, 1540)], fill=(212, 250, 88, 140), width=2)
    draw.text((64, 1570), title, font=f_title, fill="#d4fa58", stroke_width=2, stroke_fill="#000000")
    draw.text((64, 1630), meta, font=f_meta, fill="#c2c7bd", stroke_width=2, stroke_fill="#000000")

    # 5. CTA Pill
    cta_text = "👉 Сохрани в КиноЖдуне, чтобы не забыть"
    cx, cy = 64, 1690
    c_bbox = f_cta.getbbox(cta_text)
    cw, ch = c_bbox[2] - c_bbox[0], c_bbox[3] - c_bbox[1]
    cta_pill = (cx, cy, cx + cw + 48, cy + ch + 26)
    c_radius = (cta_pill[3] - cta_pill[1]) // 2
    draw.rounded_rectangle(cta_pill, radius=c_radius, fill=(24, 34, 22, 240), outline="#d4fa58", width=2)
    draw.text((cx + 24, cy + 12 - c_bbox[1]), cta_text, font=f_cta, fill="#ffffff")

    # 6. Copyright attribution
    draw.text((64, 1785), source, font=f_attr, fill="#7b8178")

    im.save(out_path)
    return out_path

def generate_ass(captions, out_path):
    """
    Builds ASS kinetic subtitles.
    captions: list of tuples (start_sec, end_sec, line1, line2, highlight_word)
    """
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,62,&H00FFFFFF,&H0058FAD4,&H00101311,&H80101311,-1,0,0,0,100,100,0,0,1,5,3,2,60,60,460,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    for start, end, l1, l2, hl in captions:
        s_str = format_ass_time(start)
        e_str = format_ass_time(end)
        def highlight(line, target):
            words = line.split()
            res = []
            for w in words:
                if target.lower() in w.lower():
                    res.append(f"{{\\c&H58FAD4&}}{w}{{\\c&HFFFFFF&}}")
                else:
                    res.append(w)
            return " ".join(res)
        text = f"{highlight(l1, hl)}\\N{highlight(l2, hl)}"
        tag = r"{\fscx95\fscy95\t(0,70,\fscx100\fscy100)}"
        events.append(f"Dialogue: 0,{s_str},{e_str},Default,,0,0,460,,{tag}{text}")

    Path(out_path).write_text(header + "\n".join(events), encoding="utf-8-sig")
    return out_path

async def synthesize_voice(text, out_wav):
    """Generates Dmitry voiceover with +8% rate."""
    communicate = edge_tts.Communicate(text, "ru-RU-DmitryNeural", rate="+8%")
    temp_mp3 = Path(out_wav).with_suffix(".mp3")
    await communicate.save(str(temp_mp3))
    run_ffmpeg(["-i", str(temp_mp3), "-ar", "48000", "-ac", "2", str(out_wav)])
    if temp_mp3.exists():
        temp_mp3.unlink()
    return out_wav

def assemble_short(trailer_path, trailer_audio_path, overlay_path, ass_path, voice_wav_path, shots, duration, out_mp4):
    out_dir = Path(out_mp4).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    has_separate_audio = bool(trailer_audio_path and Path(trailer_audio_path).exists())
    parts = []
    for i, (ss, dur, cx) in enumerate(shots):
        p = out_dir / f"vshot_{i:02d}.mp4"
        x = max(0, min(1280 - 640, cx - 320))
        if has_separate_audio:
            vf = (
                f"[0:v]crop=1280:536:0:92,split[b][f];"
                f"[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.28[bg];"
                f"[f]crop=640:536:{x}:0,scale=1080:904,setsar=1[fg];"
                f"[bg][fg]overlay=0:320[v];"
                f"[v][2:v]overlay=0:0,format=yuv420p[out]"
            )
            ff_args = [
                "-ss", str(ss), "-i", str(trailer_path),
                "-ss", str(ss), "-i", str(trailer_audio_path),
                "-loop", "1", "-i", str(overlay_path),
                "-filter_complex", vf,
                "-map", "[out]", "-map", "1:a",
                "-t", str(dur), "-r", "30",
                "-af", f"afade=t=in:d=0.03,afade=t=out:st={dur-0.03}:d=0.03",
                "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-threads", "3",
                "-c:a", "aac", "-b:a", "192k",
                str(p)
            ]
        else:
            vf = (
                f"[0:v]crop=1280:536:0:92,split[b][f];"
                f"[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.28[bg];"
                f"[f]crop=640:536:{x}:0,scale=1080:904,setsar=1[fg];"
                f"[bg][fg]overlay=0:320[v];"
                f"[v][1:v]overlay=0:0,format=yuv420p[out]"
            )
            ff_args = [
                "-ss", str(ss), "-i", str(trailer_path),
                "-loop", "1", "-i", str(overlay_path),
                "-filter_complex", vf,
                "-map", "[out]", "-map", "0:a",
                "-t", str(dur), "-r", "30",
                "-af", f"afade=t=in:d=0.03,afade=t=out:st={dur-0.03}:d=0.03",
                "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-threads", "3",
                "-c:a", "aac", "-b:a", "192k",
                str(p)
            ]
        run_ffmpeg(ff_args)
        parts.append(p)

    concat_txt = out_dir / "concat_shots.txt"
    concat_txt.write_text("\n".join(f"file '{p.name}'" for p in parts), encoding="utf-8")
    base_montage = out_dir / "base_montage.mp4"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", "-movflags", "+faststart", str(base_montage)])

    # Ducked Audio mix
    audio_mix = (
        "[1:a]loudnorm=I=-16:TP=-2:LRA=7,asplit=2[voice][key];"
        "[0:a]volume=0.55[bed];"
        "[bed][key]sidechaincompress=threshold=0.025:ratio=10:attack=15:release=250[duck];"
        "[duck][voice]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=8[aout]"
    )

    run_ffmpeg([
        "-i", "base_montage.mp4",
        "-i", Path(voice_wav_path).name,
        "-filter_complex", audio_mix,
        "-vf", f"ass={Path(ass_path).name}",
        "-map", "0:v", "-map", "[aout]",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-ar", "48000", "-b:a", "256k",
        "-movflags", "+faststart",
        Path(out_mp4).name
    ], cwd=str(out_dir))

    # Previews
    run_ffmpeg(["-ss", "2.0", "-i", Path(out_mp4).name, "-frames:v", "1", "shorts_poster.jpg"], cwd=str(out_dir))
    run_ffmpeg(["-i", Path(out_mp4).name, "-vf", "fps=1/3,scale=270:480,tile=3x3", "-frames:v", "1", "shorts_review_tile.jpg"], cwd=str(out_dir))
    return out_mp4

if __name__ == "__main__":
    print("KinoZhdun Shorts Reusable Generator Module loaded successfully.")
