"""
Автоматизированный сервис генерации и дистрибуции вертикальных шортсов
к премьерам фильмов, сериалов и выходу новых сезонов для «КиноЖдун».
"""

import os
import re
import sys
import json
import html
import wave
import asyncio
import logging
import hashlib
import shutil
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from bot.config import Settings
from bot.db.models import ChannelPost
from bot.utils.formatting import format_date_ru

try:
    from bot.services.tts_accentuator import prepare_tts_text
except Exception:
    def prepare_tts_text(text: str, use_plus: bool = True) -> str:  # type: ignore
        return text

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# Pillow import with system and local fallback
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.path.insert(0, r"C:\Users\cvet7\AppData\Roaming\Python\Python313\site-packages")
    from PIL import Image, ImageDraw, ImageFont

# Local tooling path fallbacks for development
sys.path.insert(0, str(ROOT / "output" / "social-pilot-2026-10-07" / "tooling"))
sys.path.insert(0, str(ROOT / "output" / "social-pilot-2026-10-07" / "speech-tools"))

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = str(Path(FFMPEG_EXE).parent)
    if ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    # Create alias 'ffmpeg' if missing in ffmpeg_dir for yt-dlp
    alias_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    alias_path = Path(ffmpeg_dir) / alias_name
    if not alias_path.exists():
        try:
            shutil.copy2(FFMPEG_EXE, alias_path)
        except Exception:
            pass
except Exception:
    FFMPEG_EXE = shutil.which("ffmpeg") or "ffmpeg"

try:
    import edge_tts
except Exception:
    edge_tts = None


def format_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


class ShortsPublisher:
    """Сервис автономной генерации и дистрибуции шортсов для премьерных событий."""

    def __init__(self, settings: Settings, bot: Optional[Bot] = None):
        self.settings = settings
        self.bot = bot
        self.output_root = ROOT / "output" / "autonomous_shorts"
        self.output_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def is_premiere_event(post: ChannelPost) -> bool:
        """Определяет, относится ли событие к премьере фильма, сериала или нового сезона."""
        if post.post_type in ("daily_digest", "weekly_digest"):
            return False

        if post.event_type in ("canceled", "ended"):
            return False

        # Фильмы: любые анонсы дат, релизы, трейлеры
        if post.media_type == "movie":
            return True

        # Сериалы: премьера первого сезона или релиз нового сезона
        if post.media_type == "tv":
            return True

        return False

    def get_short_cache_path(self, post: ChannelPost) -> Path:
        """Путь к кэшированному шортсу для данного события."""
        safe_title = "".join(c for c in (post.title or "short") if c.isalnum() or c in ("_", "-")).strip()
        filename = f"{post.media_type or 'media'}_{post.tmdb_id or post.id}_{post.season_number or 1}_{safe_title}.mp4"
        return self.output_root / filename

    def render_overlay(self, badge: str, hook: str, title: str, meta: str, source: str, out_path: Path) -> Path:
        """Генерирует фирменный оверлей КиноЖдуна БЕЗ надписей о тайминге."""
        # Кроссплатформенный поиск шрифтов
        fonts_dir = ROOT / "bot" / "assets" / "fonts"
        if not fonts_dir.exists():
            fonts_dir = Path("C:/Windows/Fonts")

        bold_path = fonts_dir / "segoeuib.ttf"
        if not bold_path.exists():
            bold_path = fonts_dir / "arialbd.ttf"
        reg_path = fonts_dir / "segoeui.ttf"
        if not reg_path.exists():
            reg_path = fonts_dir / "arial.ttf"

        bold_str = str(bold_path) if bold_path.exists() else None
        reg_str = str(reg_path) if reg_path.exists() else None

        if bold_str:
            f_hook = ImageFont.truetype(bold_str, 48)
            f_title = ImageFont.truetype(bold_str, 42)
            f_meta = ImageFont.truetype(bold_str, 28)
        else:
            f_hook = f_title = f_meta = ImageFont.load_default()

        if reg_str:
            f_attr = ImageFont.truetype(reg_str, 22)
        else:
            f_attr = ImageFont.load_default()

        im = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)

        # 1. Крупный интригующий хук в шапке (перенос до 2 строк, если заголовок длинный)
        hook_words = hook.split()
        hook_lines = []
        curr = ""
        for w in hook_words:
            cand = f"{curr} {w}".strip()
            if f_hook.getbbox(cand)[2] <= 950:
                curr = cand
            else:
                if curr:
                    hook_lines.append(curr)
                curr = w
        if curr:
            hook_lines.append(curr)
        hook_lines = hook_lines[:2]
        hy = 120 if len(hook_lines) == 1 else 100
        for idx, hline in enumerate(hook_lines):
            draw.text((64, hy + idx * 58), hline, font=f_hook, fill="#ffffff", stroke_width=3, stroke_fill="#000000")
        line_y = hy + len(hook_lines) * 58 + 26
        draw.line([(64, line_y), (1016, line_y)], fill=(212, 250, 88, 160), width=2)

        # 2. Рамка центрального окна (1080x904 px)
        draw.rectangle((0, 318, 1080, 1226), outline=(212, 250, 88, 55), width=2)

        # 3. Подвал: название, платформа/дата и чистый CTA для перехода
        draw.line([(64, 1525), (1016, 1525)], fill=(212, 250, 88, 160), width=2)
        draw.text((64, 1552), title, font=f_title, fill="#d4fa58", stroke_width=2, stroke_fill="#000000")
        draw.text((64, 1612), meta, font=f_meta, fill="#d8ddd3", stroke_width=2, stroke_fill="#000000")
        draw.text((64, 1670), "КиноЖдун  •  kinojdun.ru  —  уведомления в TG, VK и MAX", font=f_attr, fill="#a7ef46")

        # 4. Атрибуция
        draw.text((64, 1712), source, font=f_attr, fill="#7b8178")

        im.save(out_path)
        return out_path

    def _synthesize_speechkit_wav_sync(
        self, tts_text: str, wav_path: Path, api_key: str, voice: str, speed: str, folder_id: Optional[str]
    ) -> None:
        """Синхронный запрос к Yandex SpeechKit v1 (LPCM 48kHz -> stereo WAV)."""
        payload: dict[str, str] = {
            "text": tts_text,
            "lang": "ru-RU",
            "voice": voice or "filipp",
            "speed": speed or "1.08",
            "format": "lpcm",
            "sampleRateHertz": "48000",
        }
        if folder_id:
            payload["folderId"] = folder_id

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
            data=data,
            headers={
                "Authorization": f"Api-Key {api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            pcm = resp.read()

        if len(pcm) < 5000:
            raise RuntimeError(f"SpeechKit returned too few audio bytes: {len(pcm)}")

        mono_wav = wav_path.with_name("voice_mono.wav")
        with wave.open(str(mono_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(pcm)

        cmd = [FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mono_wav), "-ar", "48000", "-ac", "2", str(wav_path)]
        subprocess.run(cmd, check=True)
        mono_wav.unlink(missing_ok=True)

    async def generate_narration_and_subtitles(
        self, script_sentences: list[dict[str, Any]], work_dir: Path
    ) -> tuple[Path, Path, float]:
        """Синтезирует дикторский голос (SpeechKit с '+' ударениями или fallback edge-tts) и строит ASS субтитры."""
        word_timings = []
        mp3_path = work_dir / "voice.mp3"
        wav_path = work_dir / "voice.wav"

        full_text = " ".join(s["text"] for s in script_sentences)
        api_key = (getattr(self.settings, "YANDEX_SPEECHKIT_API_KEY", None) or os.getenv("YANDEX_SPEECHKIT_API_KEY") or "").strip()
        folder_id = (getattr(self.settings, "YANDEX_SPEECHKIT_FOLDER_ID", None) or os.getenv("YANDEX_SPEECHKIT_FOLDER_ID") or "").strip() or None
        sk_voice = (getattr(self.settings, "YANDEX_SPEECHKIT_VOICE", None) or os.getenv("YANDEX_SPEECHKIT_VOICE") or "filipp").strip()
        sk_speed = str(getattr(self.settings, "YANDEX_SPEECHKIT_SPEED", None) or os.getenv("YANDEX_SPEECHKIT_SPEED") or "1.08").strip()

        synthesized = False
        if api_key:
            sk_text = prepare_tts_text(full_text, use_plus=True)
            for attempt in range(3):
                try:
                    await asyncio.to_thread(
                        self._synthesize_speechkit_wav_sync, sk_text, wav_path, api_key, sk_voice, sk_speed, folder_id
                    )
                    logger.info("Озвучка шортса выполнена через Yandex SpeechKit (voice=%s, speed=%s): %s", sk_voice, sk_speed, sk_text)
                    synthesized = True
                    break
                except Exception as e:
                    logger.warning("SpeechKit попытка %s не удалась (%s): %s", attempt + 1, type(e).__name__, e)
                    await asyncio.sleep(1.5)

        if not synthesized:
            if edge_tts is None:
                raise RuntimeError("Не задан YANDEX_SPEECHKIT_API_KEY и не установлен edge_tts")

            edge_text = prepare_tts_text(full_text, use_plus=False)
            last_err = None
            for attempt in range(6):
                try:
                    word_timings.clear()
                    rate_val = "+8%" if attempt % 2 == 0 else "+0%"
                    voice_val = "ru-RU-DmitryNeural" if attempt < 4 else "ru-RU-SvetlanaNeural"
                    comm = edge_tts.Communicate(edge_text, voice_val, rate=rate_val)
                    audio_written = 0
                    with open(mp3_path, "wb") as f:
                        async for chunk in comm.stream():
                            if chunk["type"] == "audio":
                                f.write(chunk["data"])
                                audio_written += len(chunk["data"])
                            elif chunk["type"] == "WordBoundary":
                                word_timings.append({
                                    "start": chunk["offset"] / 10_000_000,
                                    "duration": chunk["duration"] / 10_000_000,
                                    "text": chunk["text"],
                                })
                    if mp3_path.exists() and audio_written > 5000:
                        logger.info("Озвучка шортса выполнена через edge-tts (%s): %s", voice_val, edge_text)
                        break
                except Exception as e:
                    last_err = e
                    await asyncio.sleep(1.5)
            else:
                raise RuntimeError(f"Edge TTS synthesis failed after 6 retries: {last_err}")

            # Переводим в 48kHz WAV
            cmd = [FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-i", str(mp3_path), "-ar", "48000", "-ac", "2", str(wav_path)]
            subprocess.run(cmd, check=True)

        actual_voice_dur = self.get_media_duration(wav_path)
        if actual_voice_dur > 1.0:
            total_duration = actual_voice_dur + 0.6
        elif word_timings:
            total_duration = word_timings[-1]["start"] + word_timings[-1]["duration"] + 0.6
        else:
            total_duration = 21.0

        speech_dur = max(1.0, total_duration - 0.6)
        header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,52,&H00FFFFFF,&H0058FAD4,&H00101311,&H80101311,-1,0,0,0,100,100,0,0,1,4,2,2,80,80,460,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
        weights = [max(1, len(s.get("text", ""))) for s in script_sentences]
        total_w = sum(weights) or 1
        cursor = 0.0
        events = []
        for s, w in zip(script_sentences, weights):
            seg_dur = speech_dur * (w / total_w)
            s_str = format_ass_time(cursor)
            e_str = format_ass_time(cursor + seg_dur)
            cursor += seg_dur
            hl = s.get("highlight", "")

            def highlight_line(line: str) -> str:
                if not hl:
                    return line
                words = line.split()
                res = []
                for wd in words:
                    if hl.lower() in wd.lower():
                        res.append(f"{{\\c&H58FAD4&}}{wd}{{\\c&HFFFFFF&}}")
                    else:
                        res.append(wd)
                return " ".join(res)

            l1 = highlight_line(s["line1"])
            l2 = highlight_line(s.get("line2", ""))
            tag = r"{\fscx95\fscy95\t(0,70,\fscx100\fscy100)}"
            full_ass = f"{l1} {l2}".strip() if (len(s["line1"]) > 24 or len(s.get("line2", "")) > 24) else (f"{l1}\\N{l2}" if l2 else l1)
            events.append(f"Dialogue: 0,{s_str},{e_str},Default,,0,0,460,,{tag}{full_ass}")

        ass_path = work_dir / "captions.ass"
        ass_path.write_text(header + "\n".join(events), encoding="utf-8-sig")

        return wav_path, ass_path, total_duration

    @staticmethod
    def get_media_duration(path: Path) -> float:
        """Получает точную длительность медиафайла через wave/FFmpeg."""
        if path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as w:
                    frames = w.getnframes()
                    rate = w.getframerate()
                    if rate > 0:
                        return frames / float(rate)
            except Exception:
                pass
        try:
            cmd = [FFMPEG_EXE, "-i", str(path)]
            res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, errors="replace")
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr)
            if m:
                h, mi, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                return h * 3600 + mi * 60 + s
        except Exception:
            pass
        return 80.0

    def _select_dynamic_shots(
        self, trailer_path: Path, trailer_dur: float, target_dur: float
    ) -> list[tuple[float, float, int]]:
        """Подбирает динамичные шоты по склейкам сцен без логотипов и чёрных экранов."""
        left = max(3.5, trailer_dur * 0.10)
        right = max(left + 6.0, trailer_dur * 0.86)
        shot_len = 1.7
        needed = max(6, int((target_dur + 2.0) / shot_len) + 1)

        cuts: list[float] = []
        dark: list[tuple[float, float]] = []
        try:
            res = subprocess.run(
                [
                    FFMPEG_EXE, "-hide_banner", "-i", str(trailer_path),
                    "-vf", "scale=256:-2,scdet=t=9,blackdetect=d=0.12:pix_th=0.12",
                    "-an", "-f", "null", "-",
                ],
                stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, errors="replace", timeout=25,
            )
            cuts = [float(x) for x in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", res.stderr)]
            dark = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)", res.stderr)]
        except Exception:
            pass

        def is_dark(st: float, en: float) -> bool:
            return any(min(en, y) - max(st, x) > 0.10 for x, y in dark)

        valid_cuts = sorted(c for c in cuts if left <= c <= right - shot_len and not is_dark(c, c + shot_len))
        chosen: list[tuple[float, float, int]] = []
        span = (right - left) / needed
        for i in range(needed):
            win_a = left + i * span
            win_b = left + (i + 1) * span
            win_mid = (win_a + win_b) / 2
            cands = [c for c in valid_cuts if win_a <= c <= win_b]
            if cands:
                start = min(cands, key=lambda c: abs(c - win_mid))
            else:
                start = min(max(left, win_a), right - shot_len)
            if chosen and start < chosen[-1][0] + 0.8:
                start = min(right - shot_len, chosen[-1][0] + 1.2)
            chosen.append((round(start, 2), shot_len, 640))
        return chosen

    def assemble_short_video(
        self,
        trailer_path: Path,
        overlay_path: Path,
        voice_wav_path: Path,
        ass_path: Path,
        shots: list[tuple[float, float, int]],
        duration: float,
        out_mp4: Path,
    ) -> Path:
        """Собирает итоговый 1080x1920 MP4 шортс с сайдчейн-даккингом и кинетическими субтитрами."""
        work_dir = voice_wav_path.parent
        work_dir.mkdir(parents=True, exist_ok=True)
        out_mp4.parent.mkdir(parents=True, exist_ok=True)

        trailer_dur = self.get_media_duration(trailer_path)
        actual_shots = shots
        if not shots and trailer_dur > 6.0:
            actual_shots = self._select_dynamic_shots(trailer_path, trailer_dur, duration)
        elif 15.0 < trailer_dur < 75.0:
            scale = max(0.2, (trailer_dur - 5.0) / 72.0)
            actual_shots = [(round(s * scale + 1.0, 1), dur, cx) for s, dur, cx in shots]

        parts = []
        for i, (ss, dur, cx) in enumerate(actual_shots):
            p = work_dir / f"vshot_{i:02d}.mp4"
            x = max(0, min(1280 - 640, cx - 320))
            vf = (
                "[0:v]scale=1280:720:force_original_aspect_ratio=increase,"
                "crop=1280:720,setsar=1,crop=1280:536:0:92,split[b][f];"
                f"[b]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.28[bg];"
                f"[f]crop=640:536:{x}:0,scale=1080:904,setsar=1[fg];"
                f"[bg][fg]overlay=0:320[v];"
                f"[v][1:v]overlay=0:0,format=yuv420p[out]"
            )
            cmd = [
                FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y",
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
            subprocess.run(cmd, check=True)
            parts.append(p)

        concat_txt = work_dir / "concat_shots.txt"
        concat_txt.write_text("\n".join(f"file '{p.name}'" for p in parts), encoding="utf-8")
        base_montage = work_dir / "base_montage.mp4"
        subprocess.run([FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", "-movflags", "+faststart", str(base_montage)], check=True)

        montage_dur = self.get_media_duration(base_montage)
        final_dur = min(duration, montage_dur) if montage_dur > 1.0 else duration
        fade_start = max(0.1, final_dur - 0.6)

        audio_mix = (
            "[1:a]loudnorm=I=-16:TP=-2:LRA=7,asplit=2[voice][key];"
            "[0:a]volume=0.55[bed];"
            "[bed][key]sidechaincompress=threshold=0.025:ratio=10:attack=15:release=250[duck];"
            f"[duck][voice]amix=inputs=2:duration=first:normalize=0,afade=t=out:st={fade_start:.2f}:d=0.6,loudnorm=I=-14:TP=-1.5:LRA=8[aout]"
        )

        fonts_dir = ROOT / "bot" / "assets" / "fonts"
        fonts_opt = f":fontsdir={fonts_dir.as_posix()}" if fonts_dir.exists() else ""
        ass_filter = f"ass={ass_path.name}{fonts_opt}"

        # Вызов с cwd=work_dir для безопасного парсинга ass субтитров
        subprocess.run([
            FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y",
            "-i", "base_montage.mp4",
            "-i", voice_wav_path.name,
            "-filter_complex", audio_mix,
            "-vf", ass_filter,
            "-map", "0:v", "-map", "[aout]",
            "-t", str(final_dur),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-ar", "48000", "-b:a", "256k",
            "-movflags", "+faststart",
            str(out_mp4.resolve())
        ], cwd=str(work_dir), check=True)

        # Постер
        poster_path = work_dir / "shorts_poster.jpg"
        subprocess.run([FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y", "-ss", "2.0", "-i", str(out_mp4.resolve()), "-frames:v", "1", str(poster_path)], check=True)
        try:
            shutil.copy2(poster_path, out_mp4.parent / "shorts_poster.jpg")
        except Exception:
            pass

        return out_mp4

    def assemble_artwork_short(self, artwork, overlay, voice, captions, duration, target):
        """Render a vertical premiere card when the trailer is unavailable."""
        work_dir = voice.parent
        frames = max(1, round(duration * 30))
        filters = (
            "[0:v]scale=1800:3200:force_original_aspect_ratio=increase,"
            "crop=1800:3200,zoompan=z='min(1+on*0.00016,1.12)':"
            "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
            f"d={frames}:s=1080x1920:fps=30[art];"
            f"[art][1:v]overlay,ass={captions.name}:fontsdir=/app/bot/assets/fonts[out]"
        )
        rendering = target.with_suffix(".rendering.mp4")
        subprocess.run([
            FFMPEG_EXE, "-hide_banner", "-loglevel", "error", "-y",
            "-filter_complex_threads", "2", "-i", artwork.name,
            "-i", overlay.name, "-i", voice.name, "-filter_complex", filters,
            "-map", "[out]", "-map", "2:a", "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(rendering.resolve()),
        ], cwd=work_dir, check=True, timeout=180)
        rendering.replace(target)

    async def ensure_short_for_post(self, post: ChannelPost) -> Optional[Path]:
        """Возвращает существующий или генерирует новый шортс для премьерного поста."""
        if getattr(self.settings, "TELEGRAM_BOT_TOKEN", "") == "mock_token":
            return None

        from shared.audience import is_readable_title
        if not is_readable_title(getattr(post, "title", None)):
            logger.warning("Пропуск генерации шортса для поста #%s: нечитаемое название «%s»", post.id, post.title)
            return None

        target_path = self.get_short_cache_path(post)
        if target_path.exists() and target_path.stat().st_size > 100_000:
            logger.info("Найден готовый шортс в кэше: %s", target_path)
            return target_path

        # Если шортса нет в кэше, проверяем наличие трейлера
        work_dir = self.output_root / f"gen_{post.id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        trailer_raw = work_dir / "trailer_raw.mp4"
        if not trailer_raw.exists():
            trailer_target = None
            if post.trailer_url:
                t_str = post.trailer_url.strip()
                if t_str.startswith("http"):
                    trailer_target = t_str
                elif len(t_str) == 11 and " " not in t_str:
                    trailer_target = f"https://www.youtube.com/watch?v={t_str}"

            if not trailer_target:
                trailer_target = f"ytsearch1:{post.title} трейлер официальный на русском"

            logger.info("Скачивание трейлера для поста #%s: %s", post.id, trailer_target)
            try:
                import yt_dlp
                ydl_opts = {
                    "format": "best[ext=mp4][height<=720]/bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[height<=720]",
                    "ffmpeg_location": FFMPEG_EXE,
                    "noprogress": True,
                    "outtmpl": str(trailer_raw),
                    "merge_output_format": "mp4",
                    "quiet": True,
                    "noplaylist": True,
                    "socket_timeout": 6,
                    "retries": 0,
                    "extractor_retries": 0,
                }
                hostname = (urllib.parse.urlsplit(trailer_target).hostname or "").lower()
                is_youtube = (
                    trailer_target.startswith("ytsearch")
                    or hostname in {"youtube.com", "youtu.be", "youtube-nocookie.com"}
                    or hostname.endswith((".youtube.com", ".youtu.be", ".youtube-nocookie.com"))
                )
                if is_youtube:
                    vpn_source = os.getenv("SHORTS_YOUTUBE_SOURCE")
                    if vpn_source:
                        ydl_opts["source_address"] = vpn_source
                    if shutil.which("node"):
                        ydl_opts["js_runtimes"] = {"node": {}}

                def download():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([trailer_target])

                await asyncio.to_thread(download)
            except Exception as e:
                logger.warning("Не удалось скачать трейлер через yt-dlp (%s)", type(e).__name__)

        artwork = None
        if not trailer_raw.exists() or trailer_raw.stat().st_size < 100_000:
            poster = post.poster_path or ""
            url = poster if poster.startswith("https://") else f"{self.settings.TMDB_IMAGE_BASE_URL.rstrip('/')}/{poster.lstrip('/')}"
            if not poster or urllib.parse.urlsplit(url).hostname != "image.tmdb.org":
                logger.warning("Для поста #%s нет доступного трейлера или постера TMDB", post.id)
                return None
            artwork = work_dir / "premiere_artwork.jpg"
            with urllib.request.urlopen(url, timeout=12) as response:
                with artwork.open("wb") as image_file:
                    shutil.copyfileobj(response, image_file)
            with Image.open(artwork) as image:
                image.verify()
            logger.info("Для поста #%s используем постер TMDB", post.id)

        # Определяем тип бейджа
        if post.media_type == "tv":
            badge = "🍿 КИНОЖДУН | НОВЫЙ СЕЗОН" if (post.season_number and post.season_number > 1) else "🍿 КИНОЖДУН | ПРЕМЬЕРА СЕРИАЛА"
        else:
            badge = "🍿 КИНОЖДУН | ПРЕМЬЕРА"

        hook = f"ПРЕМЬЕРА: {post.title.upper()}!"
        meta_date = format_date_ru(post.air_date) if post.air_date else "СКОРО"
        meta_platform = post.network or "В КИНО"
        meta_str = f"{meta_platform.upper()} • {meta_date.upper()}"
        source_str = "Изображение: TMDB" if artwork else f"Кадры и звук: официальный промо-трейлер {post.network or ''}".strip()

        # Оверлей
        overlay_path = work_dir / "brand_overlay.png"
        self.render_overlay(badge, hook, f"{post.title.upper()} ({post.air_date.year if post.air_date else datetime.now().year})", meta_str, source_str, overlay_path)

        # Сценарий: законченные предложения + синхронные субтитры
        overview_text = getattr(post, "overview", None)
        if not overview_text and getattr(post, "payload", None):
            try:
                p_data = json.loads(post.payload)
                if isinstance(p_data, dict):
                    overview_text = p_data.get("overview")
            except Exception:
                pass
        if not overview_text:
            overview_text = f"Долгожданная премьера проекта {post.title}."

        raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", overview_text.strip()) if s.strip()]
        chosen_story = []
        word_budget = 0
        for sent in raw_sentences:
            w_cnt = len(sent.split())
            if chosen_story and word_budget + w_cnt > 24:
                break
            chosen_story.append(sent)
            word_budget += w_cnt
            if word_budget >= 14:
                break
        if not chosen_story:
            words = overview_text.split()
            chosen_story = [" ".join(words[:18]).rstrip(",;:") + "."]
        story_text = " ".join(chosen_story)

        # Разбиваем сюжет на 2-строчные субтитры, точно совпадающие с речью
        story_words = story_text.split()
        story_chunks = [story_words[i:i + 7] for i in range(0, len(story_words), 7)]
        story_entries = []
        for chunk in story_chunks:
            half = max(1, (len(chunk) + 1) // 2)
            l1 = " ".join(chunk[:half])
            l2 = " ".join(chunk[half:])
            story_entries.append({
                "line1": l1,
                "line2": l2,
                "highlight": "",
                "text": " ".join(chunk),
            })

        selector = abs(int(getattr(post, "id", 0) or getattr(post, "tmdb_id", 0) or 0))

        if post.media_type == "tv":
            if post.season_number and post.season_number > 1:
                openings = [
                    ("Возвращение, которого ждали —", f"новый сезон «{post.title}»!", f"Возвращение, которого ждали — новый сезон {post.title}!"),
                    ("Продолжение истории", f"уже близко — «{post.title}»!", f"Продолжение истории уже близко — {post.title}!"),
                    ("Новый сезон любимого", f"сериала — «{post.title}»!", f"Новый сезон любимого сериала — {post.title}!"),
                ]
            else:
                openings = [
                    ("Новый сериал, который", f"стоит увидеть — «{post.title}»!", f"Новый сериал, который стоит увидеть — {post.title}!"),
                    ("Свежая сериальная", f"новинка — «{post.title}»!", f"Свежая сериальная новинка — {post.title}!"),
                    ("Ищете новый сериал?", f"Присмотритесь к «{post.title}»!", f"Ищете новый сериал на вечер? Присмотритесь к {post.title}!"),
                ]
        else:
            openings = [
                ("Главная кинопремьера,", f"которую ждут — «{post.title}»!", f"Главная кинопремьера, которую ждут — {post.title}!"),
                ("Что посмотреть скоро?", f"Обратите внимание на «{post.title}»!", f"Что посмотреть скоро? Обратите внимание на {post.title}!"),
                ("Этот фильм стоит добавить", f"в список ожидания — «{post.title}»!", f"Этот фильм стоит добавить в список ожидания — {post.title}!"),
                ("Новая громкая история", f"на подходе — «{post.title}»!", f"Новая громкая история на подходе — {post.title}!"),
            ]

        endings = [
            ("Добавьте в КиноЖдун —", "бот напомнит о выходе!", "Добавьте в КиноЖдун — бот напомнит в день выхода."),
            ("Сохраните на kinojdun.ru,", "чтобы не пропустить!", "Чтобы не пропустить релиз, сохраните его на КиноЖдуне."),
            ("Включите уведомление", "в боте КиноЖдун!", "Уведомление о выходе можно включить в боте КиноЖдун."),
            ("Отслеживайте премьеру", "в боте КиноЖдун!", "Отслеживайте премьеру в боте КиноЖдун — ссылка в описании."),
        ]

        open_l1, open_l2, open_text = openings[selector % len(openings)]
        end_l1, end_l2, end_text = endings[selector % len(endings)]

        script = [
            {"line1": open_l1, "line2": open_l2, "highlight": post.title, "text": open_text},
            *story_entries,
            {"line1": f"{meta_platform.upper()}:", "line2": f"Премьера {meta_date}!", "highlight": meta_date, "text": f"Релиз состоится {meta_date} на {meta_platform}."},
            {"line1": end_l1, "line2": end_l2, "highlight": "КиноЖдун", "text": end_text},
        ]

        voice_wav, ass_path, dur = await self.generate_narration_and_subtitles(script, work_dir)
        shots = []

        logger.info("Монтаж и композитинг шортса для поста #%s...", post.id)
        if artwork:
            await asyncio.to_thread(self.assemble_artwork_short, artwork, overlay_path, voice_wav, ass_path, dur, target_path)
        else:
            await asyncio.to_thread(self.assemble_short_video, trailer_raw, overlay_path, voice_wav, ass_path, shots, dur, target_path)
        logger.info("Шортс успешно сгенерирован и сохранён: %s", target_path)
        return target_path

    async def publish_to_telegram(
        self,
        chat_id: str | int,
        video_path: Path,
        post_text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        poster_path: Optional[str] = None,
    ) -> Optional[int]:
        """Публикация шортса в Telegram как нативное 9:16 видео."""
        if not self.bot:
            return None

        thumb_input = None
        if poster_path and Path(poster_path).exists():
            thumb_input = FSInputFile(poster_path)
        else:
            local_poster = video_path.parent / "shorts_poster.jpg"
            if local_poster.exists():
                thumb_input = FSInputFile(str(local_poster))

        try:
            msg = await self.bot.send_video(
                chat_id=chat_id,
                video=FSInputFile(str(video_path)),
                thumbnail=thumb_input,
                caption=post_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
                supports_streaming=True,
                width=1080,
                height=1920,
            )
            return msg.message_id
        except Exception as e:
            logger.warning("Ошибка публикации шортса в Telegram: %s", e)
            return None

    async def publish_to_vk_stories(self, video_path: Path, link_url: str = "https://kinojdun.ru") -> Optional[int]:
        """Публикация вертикального шортса в VK Истории сообщества."""
        token = self.settings.VK_ACCESS_TOKEN
        group = self.settings.VK_GROUP_ID
        if not token or not group:
            return None

        try:
            srv_url = (
                f"https://api.vk.com/method/stories.getVideoUploadServer?"
                f"group_id={group}&add_to_news=1&link_text=open&link_url={urllib.parse.quote(link_url)}&"
                f"access_token={token}&v=5.199"
            )
            req = urllib.request.Request(srv_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.load(resp)

            if "error" in res or "upload_url" not in res.get("response", {}):
                logger.warning("VK Stories upload server error: %s", res.get("error", {}).get("error_code"))
                return None

            upload_url = res["response"]["upload_url"]

            upload_result = None
            # Попытка 1: чистое асинхронное aiohttp без внешних зависимостей
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    with open(video_path, "rb") as f:
                        form = aiohttp.FormData()
                        form.add_field("video_file", f, filename=video_path.name, content_type="video/mp4")
                        async with session.post(upload_url, data=form, timeout=aiohttp.ClientTimeout(total=90)) as cresp:
                            up_json = await cresp.json(content_type=None)
                            upload_result = up_json.get("response", {}).get("upload_result") or up_json.get("upload_result")
            except Exception as aio_err:
                logger.debug("Aiohttp stories upload fallback: %s", aio_err)

            # Попытка 2: curl как надежный системный fallback
            if not upload_result:
                curl_bin = shutil.which("curl") or shutil.which("curl.exe") or "curl"
                cmd = [curl_bin, "-s", "-F", f"video_file=@{str(video_path)}", upload_url]
                cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
                if cp.returncode == 0:
                    try:
                        up_json = json.loads(cp.stdout)
                        upload_result = up_json.get("response", {}).get("upload_result") or up_json.get("upload_result")
                    except Exception:
                        pass

            if not upload_result:
                logger.warning("Не удалось получить upload_result для VK Stories")
                return None

            save_url = (
                f"https://api.vk.com/method/stories.save?"
                f"upload_results={urllib.parse.quote(upload_result)}&"
                f"access_token={token}&v=5.199"
            )
            req_save = urllib.request.Request(save_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_save, timeout=15) as sresp:
                s_json = json.load(sresp)

            if "response" in s_json and "items" in s_json["response"]:
                story_id = s_json["response"]["items"][0]["id"]
                logger.info("VK Story опубликована успешно (ID: %s)", story_id)
                return story_id
        except Exception as e:
            logger.warning("Не удалось опубликовать VK Story: %s", e)
        return None

    def publish_to_vk_wall(self, post: ChannelPost, story_id: Optional[int] = None) -> Optional[int]:
        """Публикация анонса премьеры на стене сообщества ВКонтакте."""
        token = self.settings.VK_ACCESS_TOKEN
        group = self.settings.VK_GROUP_ID
        if not token or not group:
            return None

        try:
            overview_desc = getattr(post, "overview", None)
            if not overview_desc and getattr(post, "payload", None):
                try:
                    p_data = json.loads(post.payload)
                    if isinstance(p_data, dict):
                        overview_desc = p_data.get("overview")
                except Exception:
                    pass
            desc_block = f"📝 {overview_desc}\n\n" if overview_desc else ""
            card_url = (
                f"https://kinojdun.ru/title/{post.media_type}/{post.tmdb_id}?from=vk-wall"
                if post.media_type and post.tmdb_id else "https://kinojdun.ru/?from=vk-wall"
            )
            vk_bot_url = os.getenv("VK_BOT_URL", "https://vk.me/club242087163").strip()
            tag_title = "#" + re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", post.title or "")[:28]
            kind_tag = "#сериалы" if post.media_type == "tv" else "#фильмы"

            wall_msg = (
                f"🍿 ПРЕМЬЕРА: {post.title}\n\n"
                f"📅 Дата: {format_date_ru(post.air_date) if post.air_date else 'Скоро'}\n"
                f"🎬 Платформа: {post.network or 'В кинотеатрах'}\n\n"
                f"{desc_block}"
                f"💬 Ждёте премьеру? Пишите в комментариях!\n\n"
                f"👉 Карточка и трейлер: {card_url}\n"
                f"🔔 Напоминание в VK-боте: {vk_bot_url}\n"
                f"🤖 Telegram-бот: https://t.me/kinojdun_bot\n\n"
                f"{tag_title} #премьера #кино {kind_tag} #чтопосмотреть"
            )

            attachment_str = ""
            if getattr(post, "poster_path", None):
                try:
                    poster_url = (
                        post.poster_path if str(post.poster_path).startswith("http")
                        else f"{self.settings.TMDB_IMAGE_BASE_URL}{post.poster_path}"
                    )
                    up_srv_url = f"https://api.vk.com/method/photos.getWallUploadServer?group_id={group}&access_token={token}&v=5.199"
                    with urllib.request.urlopen(urllib.request.Request(up_srv_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as ur:
                        up_srv = json.load(ur)
                    up_url = up_srv.get("response", {}).get("upload_url")
                    if up_url:
                        with urllib.request.urlopen(urllib.request.Request(poster_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as pr:
                            img_bytes = pr.read()
                        boundary = "----KinojdunBoundary7MA4YWxkTrZu0gW"
                        body = (
                            f"--{boundary}\r\n"
                            f'Content-Disposition: form-data; name="photo"; filename="poster.jpg"\r\n'
                            f"Content-Type: image/jpeg\r\n\r\n"
                        ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
                        up_req = urllib.request.Request(up_url, data=body, headers={
                            "Content-Type": f"multipart/form-data; boundary={boundary}",
                            "User-Agent": "Mozilla/5.0",
                        })
                        with urllib.request.urlopen(up_req, timeout=15) as upr:
                            up_res = json.load(upr)
                        if up_res.get("photo") and up_res.get("hash"):
                            save_q = urllib.parse.urlencode({
                                "group_id": group,
                                "photo": up_res["photo"],
                                "server": up_res["server"],
                                "hash": up_res["hash"],
                                "access_token": token,
                                "v": "5.199",
                            }).encode("utf-8")
                            with urllib.request.urlopen(urllib.request.Request("https://api.vk.com/method/photos.saveWallPhoto", data=save_q), timeout=10) as svr:
                                sv_res = json.load(svr)
                            ph = (sv_res.get("response") or [{}])[0]
                            if ph.get("owner_id") and ph.get("id"):
                                attachment_str = f"photo{ph['owner_id']}_{ph['id']}"
                except Exception as img_err:
                    logger.warning("Не удалось прикрепить постер к посту VK: %s", img_err)

            payload_dict = {
                "owner_id": f"-{group}",
                "from_group": "1",
                "message": wall_msg,
                "access_token": token,
                "v": "5.199",
            }
            if attachment_str:
                payload_dict["attachments"] = attachment_str
            data = urllib.parse.urlencode(payload_dict).encode("utf-8")

            req = urllib.request.Request("https://api.vk.com/method/wall.post", data=data, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.load(resp)

            if "response" in res:
                post_id = res["response"]["post_id"]
                logger.info("Пост на стене VK опубликован (ID: %s)", post_id)
                return post_id
        except Exception as e:
            logger.warning("Не удалось опубликовать пост на стене VK: %s", e)
        return None

    async def publish_to_max_channel(self, post: ChannelPost, video_path: Optional[Path] = None) -> Optional[str]:
        """Публикация анонса премьеры в канал MAX Messenger."""
        max_token = getattr(self.settings, "MAX_BOT_TOKEN", None) or os.getenv("MAX_BOT_TOKEN")
        max_channel = getattr(self.settings, "MAX_CHANNEL_ID", None) or os.getenv("MAX_CHANNEL_ID")
        max_enabled = getattr(self.settings, "MAX_CHANNEL_POSTING_ENABLED", False) or os.getenv("MAX_CHANNEL_POSTING_ENABLED", "false").lower() == "true"

        if not max_token or not max_channel or not max_enabled:
            return None

        try:
            from max_bot.client import MaxBotClient
            client = MaxBotClient(max_token)
            site_url = self.settings.SITE_BASE_URL.rstrip("/")
            bot_url = os.getenv("MAX_BOT_URL", "https://max.ru/id5001170357_1_bot")

            attachments = []
            if post.poster_path:
                url = post.poster_path if post.poster_path.startswith("http") else f"{self.settings.TMDB_IMAGE_BASE_URL}{post.poster_path}"
                token = await client.upload_image_from_url(url)
                if token:
                    attachments.append({"type": "image", "payload": {"token": token}})

            card_url = (
                f"{site_url}/title/{post.media_type}/{post.tmdb_id}?from=max"
                if post.media_type and post.tmdb_id else f"{site_url}/?from=max"
            )
            attachments.append({"type": "inline_keyboard", "payload": {"buttons": [
                [{"type": "link", "text": "🍿 Смотреть на сайте", "url": card_url}],
                [{"type": "link", "text": "🔔 Личные напоминания", "url": bot_url}],
            ]}})

            res = await client.send_message(
                chat_id=int(max_channel),
                text=post.post_text or f"🍿 Премьера: {post.title}!",
                attachments=attachments
            )
            await client.close()
            msg_id = res.get("message", {}).get("body", {}).get("mid")
            logger.info("MAX Channel опубликовал премьеру #%s (mid: %s)", post.id, msg_id)
            return msg_id
        except Exception as e:
            logger.warning("Не удалось опубликовать в MAX Channel: %s", e)
        return None

    async def distribute_all_channels(self, post: ChannelPost, video_path: Path) -> dict[str, Any]:
        """Единый метод дистрибуции сгенерированного шортса по всем соцсетям."""
        results = {}
        # 1. VK Stories
        story_url = (
            f"https://kinojdun.ru/title/{post.media_type}/{post.tmdb_id}?from=vk-story"
            if post.media_type and post.tmdb_id else "https://kinojdun.ru/?from=vk-story"
        )
        story_id = await self.publish_to_vk_stories(video_path, link_url=story_url)
        results["vk_story_id"] = story_id

        # 2. VK Wall
        wall_id = self.publish_to_vk_wall(post, story_id)
        results["vk_wall_id"] = wall_id

        # 3. MAX Messenger
        max_mid = await self.publish_to_max_channel(post, video_path)
        results["max_mid"] = max_mid

        # 4. YouTube Shorts
        try:
            from bot.services.youtube_publisher import YouTubePublisher
            yt_pub = YouTubePublisher(self.settings)
            if yt_pub.is_configured():
                yt_id = await yt_pub.publish_short(post, video_path)
                results["youtube_video_id"] = yt_id
        except Exception as yt_err:
            logger.warning("Не удалось опубликовать шортс на YouTube: %s", yt_err)

        # 5. Instagram Reels
        try:
            from bot.services.instagram_publisher import InstagramPublisher
            ig_pub = InstagramPublisher(self.settings)
            if ig_pub.is_configured():
                ig_id = await ig_pub.publish_short(post, video_path)
                results["instagram_media_id"] = ig_id
        except Exception as ig_err:
            logger.warning("Не удалось опубликовать шортс в Instagram: %s", ig_err)

        return results
