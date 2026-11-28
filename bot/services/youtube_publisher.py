"""
Публикация вертикальных шортсов в YouTube Shorts через официальный YouTube Data API v3
(OAuth2 refresh_token + Resumable Upload) с защитой от дублирования.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import asyncio
import aiohttp

from bot.config import Settings
from bot.db.models import ChannelPost
from bot.utils.formatting import format_date_ru

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB (кратен 256 KiB согласно требованиям YouTube Resumable Upload)


def _state_db_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.getenv("YOUTUBE_STATE_DIR", str(root / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "youtube_state.db"


def _already_uploaded(post_id: int) -> Optional[str]:
    db_path = _state_db_path()
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS youtube_uploads (
                post_id INTEGER PRIMARY KEY,
                video_id TEXT NOT NULL,
                privacy_status TEXT,
                title TEXT,
                uploaded_at TEXT NOT NULL
            )"""
        )
        row = conn.execute("SELECT video_id FROM youtube_uploads WHERE post_id = ?", (post_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _mark_uploaded(post_id: int, video_id: str, privacy_status: str, title: str) -> None:
    db_path = _state_db_path()
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS youtube_uploads (
                post_id INTEGER PRIMARY KEY,
                video_id TEXT NOT NULL,
                privacy_status TEXT,
                title TEXT,
                uploaded_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO youtube_uploads (post_id, video_id, privacy_status, title, uploaded_at) VALUES (?, ?, ?, ?, ?)",
            (post_id, video_id, privacy_status, title, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _clean_hashtag(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]", "", text or "")
    return cleaned[:40]


def _build_metadata(post: ChannelPost, settings: Settings) -> dict[str, Any]:
    site_url = (getattr(settings, "SITE_BASE_URL", None) or "https://kinojdun.ru").rstrip("/")
    bot_url = f"https://t.me/{(getattr(settings, 'BOT_USERNAME', None) or 'kinojdun_bot').lstrip('@')}"
    max_bot_url = os.getenv("MAX_BOT_URL", "https://max.ru/id5001170357_1_bot")

    date_str = format_date_ru(post.air_date) if post.air_date else "скоро"
    year_str = str(post.air_date.year) if post.air_date else str(datetime.now().year)
    platform = (post.network or "в кино").strip()

    # Заголовок YouTube <= 100 символов с #shorts
    if post.media_type == "tv" and post.season_number and post.season_number > 1:
        suffix = f" — {post.season_number} сезон: дата выхода #shorts"
    else:
        suffix = f" ({year_str}) — дата выхода и трейлер #shorts"

    raw_title = (post.title or "Новая премьера").strip()
    max_title_len = max(12, 100 - len(suffix))
    short_name = raw_title[:max_title_len].rstrip(" .,:;-")
    yt_title = f"{short_name}{suffix}"[:100]

    # Сюжет
    overview = getattr(post, "overview", None) or ""
    if not overview and getattr(post, "payload", None):
        try:
            pdata = json.loads(post.payload)
            if isinstance(pdata, dict):
                overview = pdata.get("overview") or ""
        except Exception:
            pass
    overview = re.sub(r"\s+", " ", overview).strip()
    if len(overview) > 450:
        overview = overview[:447].rstrip() + "..."

    link_url = (
        f"{site_url}/title/{post.media_type}/{post.tmdb_id}?from=youtube-shorts"
        if post.media_type and post.tmdb_id
        else f"{site_url}/?from=youtube-shorts"
    )

    kind_ru = "Сериал" if post.media_type == "tv" else "Фильм"
    season_line = f" • {post.season_number} сезон" if (post.media_type == "tv" and post.season_number and post.season_number > 1) else ""

    title_tag = _clean_hashtag(raw_title)
    hashtags = ["#shorts", "#кинождун", "#премьеры", "#трейлер"]
    hashtags.append("#сериалы" if post.media_type == "tv" else "#кино")
    if title_tag and len(title_tag) >= 3:
        hashtags.append(f"#{title_tag}")

    desc_parts = [
        f"🍿 {raw_title} ({year_str}){season_line}",
        f"{kind_ru} • {platform} • Премьера: {date_str}",
    ]
    if overview:
        desc_parts.extend(["", overview])
    desc_parts.extend([
        "",
        "🔔 Хотите получить напоминание в день выхода?",
        f"🎬 Страница проекта и календарь: {link_url}",
        f"🤖 Бот в Telegram: {bot_url}",
        f"💬 Бот в MAX: {max_bot_url}",
        "💙 ВКонтакте: https://vk.com/kinojdun",
        "",
        " ".join(hashtags),
    ])
    description = "\n".join(desc_parts)[:4900]

    # Теги (лимит YouTube 500 символов суммарно)
    raw_tags = [
        "КиноЖдун",
        raw_title,
        "трейлер",
        "дата выхода",
        "премьера",
        "shorts",
        "сериалы" if post.media_type == "tv" else "кино",
        "что посмотреть",
        platform if len(platform) <= 40 else "",
    ]
    tags: list[str] = []
    total_len = 0
    for t in raw_tags:
        t = (t or "").strip()
        if not t or t in tags:
            continue
        if total_len + len(t) + 2 > 450:
            break
        tags.append(t)
        total_len += len(t) + 2

    privacy = (getattr(settings, "YOUTUBE_PRIVACY_STATUS", None) or os.getenv("YOUTUBE_PRIVACY_STATUS") or "private").strip().lower()
    if privacy not in ("private", "unlisted", "public"):
        privacy = "private"

    category_id = str(getattr(settings, "YOUTUBE_CATEGORY_ID", None) or os.getenv("YOUTUBE_CATEGORY_ID") or "1").strip()

    return {
        "snippet": {
            "title": yt_title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": "ru",
            "defaultAudioLanguage": "ru",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }


class YouTubePublisher:
    """Клиент публикации вертикальных видео в YouTube Shorts через Data API v3."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = bool(
            getattr(settings, "YOUTUBE_POSTING_ENABLED", False)
            or os.getenv("YOUTUBE_POSTING_ENABLED", "false").lower() in ("true", "1", "yes")
        )
        self.client_id = (getattr(settings, "YOUTUBE_CLIENT_ID", None) or os.getenv("YOUTUBE_CLIENT_ID") or "").strip()
        self.client_secret = (getattr(settings, "YOUTUBE_CLIENT_SECRET", None) or os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip()
        self.refresh_token = (getattr(settings, "YOUTUBE_REFRESH_TOKEN", None) or os.getenv("YOUTUBE_REFRESH_TOKEN") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.enabled and self.client_id and self.client_secret and self.refresh_token)

    async def _fetch_access_token(self, session: aiohttp.ClientSession) -> str:
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        async with session.post(_TOKEN_URL, data=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or not data.get("access_token"):
                raise RuntimeError(f"Google OAuth refresh failed ({resp.status}): {data}")
            return str(data["access_token"])

    async def _confirm_processing(self, video_id: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                token = await self._fetch_access_token(session)
                for attempt in range(10):
                    async with session.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={"part": "status,processingDetails", "id": video_id},
                        headers={"Authorization": f"Bearer {token}"},
                    ) as response:
                        response.raise_for_status()
                        items = (await response.json()).get("items", [])
                    if items:
                        upload_status = items[0].get("status", {}).get("uploadStatus")
                        processing = items[0].get("processingDetails", {}).get("processingStatus")
                        if processing in ("failed", "terminated") or upload_status in ("failed", "rejected", "deleted"):
                            logger.error("YouTube отклонил видео %s (%s/%s)", video_id, upload_status, processing)
                            return None
                        if processing == "succeeded" or upload_status == "processed":
                            logger.info("YouTube подтвердил обработку видео %s", video_id)
                            return video_id
                    if attempt < 9:
                        await asyncio.sleep(8)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            logger.warning("Не удалось проверить обработку YouTube %s (%s)", video_id, type(exc).__name__)
        logger.warning("YouTube принял видео %s, обработка не подтверждена", video_id)
        return None

    async def publish_short(self, post: ChannelPost, video_path: Path) -> Optional[str]:
        """Загружает шортс на YouTube и возвращает video_id (либо None при пропуске/ошибке)."""
        if not self.is_configured():
            return None
        if not video_path.exists() or video_path.stat().st_size < 50_000:
            logger.warning("YouTube skip: видеофайл отсутствует или слишком мал (%s)", video_path)
            return None

        post_id = getattr(post, "id", None)
        if post_id is not None:
            existing = _already_uploaded(int(post_id))
            if existing:
                logger.info("YouTube skip: пост #%s уже загружен (video_id=%s)", post_id, existing)
                return await self._confirm_processing(existing)

        metadata = _build_metadata(post, self.settings)
        privacy = metadata["status"]["privacyStatus"]
        yt_title = metadata["snippet"]["title"]
        file_size = video_path.stat().st_size

        connector = aiohttp.TCPConnector()
        use_vpn = os.getenv("YOUTUBE_USE_VPN", "false").lower() in ("true", "1", "yes")
        vpn_source = os.getenv("SHORTS_YOUTUBE_SOURCE", "").strip()
        if use_vpn and vpn_source:
            connector = aiohttp.TCPConnector(local_addr=(vpn_source, 0))

        async with aiohttp.ClientSession(connector=connector) as session:
            access_token = await self._fetch_access_token(session)
            init_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(file_size),
                "X-Upload-Content-Type": "video/mp4",
            }
            async with session.post(
                _UPLOAD_URL,
                headers=init_headers,
                data=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as init_resp:
                if init_resp.status not in (200, 201):
                    body = await init_resp.text()
                    raise RuntimeError(f"YouTube upload init failed ({init_resp.status}): {body[:500]}")
                upload_url = init_resp.headers.get("Location")
                if not upload_url:
                    raise RuntimeError("YouTube upload init did not return Location header")

            video_id: Optional[str] = None
            with video_path.open("rb") as f:
                offset = 0
                while offset < file_size:
                    chunk = f.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    end = offset + len(chunk) - 1
                    put_headers = {
                        "Content-Length": str(len(chunk)),
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes {offset}-{end}/{file_size}",
                    }
                    async with session.put(
                        upload_url,
                        headers=put_headers,
                        data=chunk,
                        timeout=aiohttp.ClientTimeout(total=180),
                    ) as put_resp:
                        if put_resp.status in (200, 201):
                            res_json = await put_resp.json(content_type=None)
                            video_id = str(res_json.get("id") or "")
                            break
                        if put_resp.status == 308:
                            offset += len(chunk)
                            continue
                        err_body = await put_resp.text()
                        raise RuntimeError(f"YouTube chunk upload failed ({put_resp.status}): {err_body[:500]}")

        if not video_id:
            raise RuntimeError("YouTube upload completed without returning video_id")

        if post_id is not None:
            _mark_uploaded(int(post_id), video_id, privacy, yt_title)

        logger.info(
            "YouTube Shorts загружен для поста #%s: https://youtube.com/shorts/%s (privacy=%s)",
            post_id, video_id, privacy,
        )
        return await self._confirm_processing(video_id)
