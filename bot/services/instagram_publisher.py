"""
Публикация вертикальных роликов в Instagram Reels через официальный Meta/Instagram Graph API
с маршрутизацией через AWG VPN (включая DoH-резолвинг зарубежных IP Meta через dns.google)
и прямой бинарной загрузкой (resumable upload) на rupload.facebook.com.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp

from bot.config import Settings
from bot.db.models import ChannelPost
from bot.services.vpn_http import build_vpn_connector
from bot.utils.formatting import format_date_ru

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    d = Path(os.getenv("INSTAGRAM_DATA_DIR", str(root / "data")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_db_path() -> Path:
    return _data_dir() / "instagram_state.db"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS instagram_uploads (
            post_id INTEGER PRIMARY KEY,
            media_id TEXT NOT NULL,
            caption TEXT,
            published_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS instagram_auth (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def _already_uploaded(post_id: int) -> Optional[str]:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        row = conn.execute("SELECT media_id FROM instagram_uploads WHERE post_id = ?", (post_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _mark_uploaded(post_id: int, media_id: str, caption: str) -> None:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        conn.execute(
            "INSERT OR REPLACE INTO instagram_uploads (post_id, media_id, caption, published_at) VALUES (?, ?, ?, ?)",
            (post_id, media_id, caption, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _load_effective_token(env_token: str) -> str:
    """Возвращает сохранённый продлённый токен, если он новее или если совпадает исходный токен."""
    if not env_token:
        return ""
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        seed_row = conn.execute("SELECT value FROM instagram_auth WHERE key = 'seed_token'").fetchone()
        cur_row = conn.execute("SELECT value FROM instagram_auth WHERE key = 'access_token'").fetchone()
        if seed_row and seed_row[0] == env_token and cur_row and cur_row[0]:
            return cur_row[0]
        # Зафиксирован новый токен в .env -> сбрасываем сохранённый
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR REPLACE INTO instagram_auth VALUES ('seed_token', ?, ?)", (env_token, now))
        conn.execute("INSERT OR REPLACE INTO instagram_auth VALUES ('access_token', ?, ?)", (env_token, now))
        conn.execute("INSERT OR REPLACE INTO instagram_auth VALUES ('refreshed_at', ?, ?)", (now, now))
        conn.commit()
        return env_token
    finally:
        conn.close()


def _save_refreshed_token(new_token: str) -> None:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR REPLACE INTO instagram_auth VALUES ('access_token', ?, ?)", (new_token, now))
        conn.execute("INSERT OR REPLACE INTO instagram_auth VALUES ('refreshed_at', ?, ?)", (now, now))
        conn.commit()
    finally:
        conn.close()


def _should_refresh_token() -> bool:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        row = conn.execute("SELECT value FROM instagram_auth WHERE key = 'refreshed_at'").fetchone()
        if not row:
            return True
        dt = datetime.fromisoformat(row[0])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days >= 7
    except Exception:
        return False
    finally:
        conn.close()


def _cleanup_old_reels(reels_dir: Path, max_age_sec: int = 7200) -> None:
    now = time.time()
    for p in reels_dir.glob("*.mp4"):
        try:
            if now - p.stat().st_mtime > max_age_sec:
                p.unlink(missing_ok=True)
        except Exception:
            pass


def _build_caption(post: ChannelPost, settings: Settings) -> str:
    raw_title = (post.title or "Новая премьера").strip()
    date_str = format_date_ru(post.air_date) if post.air_date else "скоро"
    year_str = str(post.air_date.year) if post.air_date else str(datetime.now().year)
    platform = (post.network or "в кино").strip()

    overview = getattr(post, "overview", None) or ""
    if not overview and getattr(post, "payload", None):
        try:
            pdata = json.loads(post.payload)
            if isinstance(pdata, dict):
                overview = pdata.get("overview") or ""
        except Exception:
            pass
    overview = re.sub(r"\s+", " ", overview).strip()
    if len(overview) > 380:
        overview = overview[:377].rstrip() + "..."

    kind_ru = "Сериал" if post.media_type == "tv" else "Фильм"
    season_line = f" • {post.season_number} сезон" if (post.media_type == "tv" and post.season_number and post.season_number > 1) else ""
    clean_tag = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_]", "", raw_title)[:35]
    tags = ["#кинождун", "#премьеры", "#трейлер", "#чтопосмотреть"]
    tags.append("#сериалы" if post.media_type == "tv" else "#кино")
    if len(clean_tag) >= 3:
        tags.append(f"#{clean_tag}")

    parts = [
        f"🍿 {raw_title} ({year_str}){season_line}",
        f"{kind_ru} • {platform} • Премьера: {date_str}",
    ]
    if overview:
        parts.extend(["", overview])
    parts.extend([
        "",
        "🔔 Добавьте проект в личный список ожидания, чтобы не пропустить выход — ссылка на сайт и ботов в шапке профиля (kinojdun.ru).",
        "",
        " ".join(tags),
    ])
    return "\n".join(parts)[:2150]


class InstagramPublisher:
    """Публикатор Instagram Reels через Meta/Instagram Graph API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = bool(
            getattr(settings, "INSTAGRAM_POSTING_ENABLED", False)
            or os.getenv("INSTAGRAM_POSTING_ENABLED", "false").lower() in ("true", "1", "yes")
        )
        self.ig_user_id = (getattr(settings, "INSTAGRAM_USER_ID", None) or os.getenv("INSTAGRAM_USER_ID") or "").strip()
        self.env_token = (getattr(settings, "INSTAGRAM_ACCESS_TOKEN", None) or os.getenv("INSTAGRAM_ACCESS_TOKEN") or "").strip()
        self.api_version = (getattr(settings, "INSTAGRAM_API_VERSION", None) or os.getenv("INSTAGRAM_API_VERSION") or "v21.0").strip()

    def is_configured(self) -> bool:
        return bool(self.enabled and self.ig_user_id and self.env_token)

    def _connector(self) -> aiohttp.TCPConnector:
        return build_vpn_connector("INSTAGRAM_USE_VPN")

    def _api_host(self, token: str) -> str:
        override = (os.getenv("INSTAGRAM_API_HOST") or "").strip().rstrip("/")
        if override:
            return override
        # System User / Facebook Login токены начинаются с 'EAA' -> graph.facebook.com
        if token.startswith("EAA"):
            return "https://graph.facebook.com"
        return "https://graph.instagram.com"

    async def _maybe_refresh_token(self, session: aiohttp.ClientSession, token: str) -> str:
        # System User токен (EAA...) вечный и не обновляется через ig_refresh_token
        if token.startswith("EAA") or not _should_refresh_token():
            return token
        try:
            url = "https://graph.instagram.com/refresh_access_token"
            params = {"grant_type": "ig_refresh_token", "access_token": token}
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as r:
                data = await r.json(content_type=None)
                if r.status == 200 and data.get("access_token"):
                    new_tok = str(data["access_token"])
                    _save_refreshed_token(new_tok)
                    logger.info("Instagram long-lived token продлён (expires_in=%s)", data.get("expires_in"))
                    return new_tok
                logger.warning("Не удалось продлить Instagram token (%s): %s", r.status, data)
        except Exception as e:
            logger.warning("Ошибка продления Instagram token: %s", e)
        return token

    async def publish_short(self, post: ChannelPost, video_path: Path) -> Optional[str]:
        if not self.is_configured():
            return None
        if not video_path.exists() or video_path.stat().st_size < 50_000:
            logger.warning("Instagram skip: видеофайл отсутствует или слишком мал (%s)", video_path)
            return None

        post_id = int(getattr(post, "id", 0) or 0)
        if post_id:
            existing = _already_uploaded(post_id)
            if existing:
                logger.info("Instagram skip: пост #%s уже опубликован (media_id=%s)", post_id, existing)
                return existing

        caption = _build_caption(post, self.settings)
        tmp_path: Optional[Path] = None

        try:
            token = _load_effective_token(self.env_token)
            host = self._api_host(token)
            base = f"{host}/{self.api_version}"
            use_resumable = host == "https://graph.facebook.com"

            async with aiohttp.ClientSession(connector=self._connector()) as session:
                token = await self._maybe_refresh_token(session, token)
                create_url = f"{base}/{self.ig_user_id}/media"

                if use_resumable:
                    # 1a. Прямая бинарная загрузка через rupload.facebook.com
                    payload = {
                        "media_type": "REELS",
                        "upload_type": "resumable",
                        "caption": caption,
                        "share_to_feed": "true",
                        "access_token": token,
                    }
                    async with session.post(create_url, data=payload, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                        c_data = await resp.json(content_type=None)
                        if resp.status not in (200, 201) or not c_data.get("id"):
                            raise RuntimeError(f"Instagram container create failed ({resp.status}): {c_data}")
                        creation_id = str(c_data["id"])
                        upload_uri = str(c_data.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{self.api_version}/{creation_id}")

                    raw_bytes = video_path.read_bytes()
                    async with session.post(
                        upload_uri,
                        data=raw_bytes,
                        headers={
                            "Authorization": f"OAuth {token}",
                            "offset": "0",
                            "file_size": str(len(raw_bytes)),
                            "Content-Type": "application/octet-stream",
                        },
                        timeout=aiohttp.ClientTimeout(total=240),
                    ) as up_resp:
                        up_text = await up_resp.text()
                        if up_resp.status not in (200, 201):
                            raise RuntimeError(f"Instagram rupload failed ({up_resp.status}): {up_text}")
                else:
                    # 1b. Режим Instagram Login с временной URL-раздачей на сайте
                    reels_dir = _data_dir() / "reels_tmp"
                    reels_dir.mkdir(parents=True, exist_ok=True)
                    _cleanup_old_reels(reels_dir)

                    tmp_name = f"{secrets.token_hex(12)}_{post_id or int(time.time())}.mp4"
                    tmp_path = reels_dir / tmp_name
                    shutil.copy2(video_path, tmp_path)

                    site_url = (getattr(self.settings, "SITE_BASE_URL", None) or "https://kinojdun.ru").rstrip("/")
                    video_url = f"{site_url}/media/reels/{tmp_name}"
                    payload = {
                        "media_type": "REELS",
                        "video_url": video_url,
                        "caption": caption,
                        "share_to_feed": "true",
                        "access_token": token,
                    }
                    async with session.post(create_url, data=payload, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                        c_data = await resp.json(content_type=None)
                        if resp.status not in (200, 201) or not c_data.get("id"):
                            raise RuntimeError(f"Instagram container create failed ({resp.status}): {c_data}")
                        creation_id = str(c_data["id"])

                # 2. Ожидание обработки видео на стороне Meta
                status_url = f"{base}/{creation_id}"
                finished = False
                for _ in range(36):  # до 3 минут (36 * 5 сек)
                    await asyncio.sleep(5)
                    async with session.get(
                        status_url,
                        params={"fields": "status_code,status", "access_token": token},
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as st_resp:
                        st_data = await st_resp.json(content_type=None)
                        code = str(st_data.get("status_code") or "").upper()
                        if code == "FINISHED":
                            finished = True
                            break
                        if code in ("ERROR", "EXPIRED"):
                            raise RuntimeError(f"Instagram container processing failed: {st_data}")

                if not finished:
                    raise RuntimeError(f"Instagram container processing timed out (creation_id={creation_id})")

                # 3. Публикация контейнера
                pub_url = f"{base}/{self.ig_user_id}/media_publish"
                async with session.post(
                    pub_url,
                    data={"creation_id": creation_id, "access_token": token},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as p_resp:
                    p_data = await p_resp.json(content_type=None)
                    if p_resp.status not in (200, 201) or not p_data.get("id"):
                        raise RuntimeError(f"Instagram media_publish failed ({p_resp.status}): {p_data}")
                    media_id = str(p_data["id"])

            if post_id:
                _mark_uploaded(post_id, media_id, caption)
            logger.info("Instagram Reels опубликован для поста #%s (media_id=%s)", post_id, media_id)
            return media_id
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
