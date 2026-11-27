"""
Отправка вертикальных шортсов во «Входящие / Черновики» TikTok через официальный
Content Posting API v2 (Inbox Upload: /v2/post/publish/inbox/video/init/),
с маршрутизацией через AWG VPN и ротацией OAuth refresh_token в SQLite.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp

from bot.config import Settings
from bot.db.models import ChannelPost
from bot.services.vpn_http import build_vpn_connector

logger = logging.getLogger(__name__)

TIKTOK_OAUTH_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

_SINGLE_CHUNK_MAX_BYTES = 64 * 1024 * 1024
_MULTI_CHUNK_BYTES = 10_000_000


def _data_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    d = Path(os.getenv("TIKTOK_DATA_DIR", str(root / "data")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_db_path() -> Path:
    return _data_dir() / "tiktok_state.db"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tiktok_uploads (
            post_id INTEGER PRIMARY KEY,
            publish_id TEXT NOT NULL,
            published_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tiktok_auth (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def _already_uploaded(post_id: int) -> Optional[str]:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        row = conn.execute("SELECT publish_id FROM tiktok_uploads WHERE post_id = ?", (post_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _mark_uploaded(post_id: int, publish_id: str) -> None:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        conn.execute(
            "INSERT OR REPLACE INTO tiktok_uploads (post_id, publish_id, published_at) VALUES (?, ?, ?)",
            (post_id, publish_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _load_auth_state(env_refresh_token: str) -> dict[str, str]:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        rows = dict(conn.execute("SELECT key, value FROM tiktok_auth").fetchall())
        if rows.get("seed_refresh_token") != env_refresh_token:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("DELETE FROM tiktok_auth")
            conn.execute("INSERT INTO tiktok_auth VALUES ('seed_refresh_token', ?, ?)", (env_refresh_token, now))
            conn.execute("INSERT INTO tiktok_auth VALUES ('refresh_token', ?, ?)", (env_refresh_token, now))
            conn.commit()
            return {"seed_refresh_token": env_refresh_token, "refresh_token": env_refresh_token}
        return rows
    finally:
        conn.close()


def _save_auth_tokens(access_token: str, refresh_token: str, expires_in: int, open_id: str = "") -> None:
    conn = sqlite3.connect(_state_db_path(), timeout=10)
    try:
        _init_db(conn)
        now_iso = datetime.now(timezone.utc).isoformat()
        expires_at = str(int(time.time()) + max(60, int(expires_in)))
        updates = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
        if open_id:
            updates["open_id"] = open_id
        for k, v in updates.items():
            conn.execute("INSERT OR REPLACE INTO tiktok_auth VALUES (?, ?, ?)", (k, v, now_iso))
        conn.commit()
    finally:
        conn.close()


class TiktokPublisher:
    """Загрузчик роликов в черновики/входящие TikTok через Content Posting API v2."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = bool(
            getattr(settings, "TIKTOK_POSTING_ENABLED", False)
            or os.getenv("TIKTOK_POSTING_ENABLED", "false").lower() in ("true", "1", "yes")
        )
        self.client_key = (getattr(settings, "TIKTOK_CLIENT_KEY", None) or os.getenv("TIKTOK_CLIENT_KEY") or "").strip()
        self.client_secret = (getattr(settings, "TIKTOK_CLIENT_SECRET", None) or os.getenv("TIKTOK_CLIENT_SECRET") or "").strip()
        self.env_refresh_token = (getattr(settings, "TIKTOK_REFRESH_TOKEN", None) or os.getenv("TIKTOK_REFRESH_TOKEN") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.enabled and self.client_key and self.client_secret and self.env_refresh_token)

    async def _ensure_access_token(self, session: aiohttp.ClientSession) -> str:
        state = _load_auth_state(self.env_refresh_token)
        access_tok = state.get("access_token", "")
        expires_at = int(state.get("expires_at") or 0)
        if access_tok and time.time() < expires_at - 300:
            return access_tok

        refresh_tok = state.get("refresh_token") or self.env_refresh_token
        payload = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
        }
        async with session.post(
            TIKTOK_OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json(content_type=None)
            tok_data = data.get("data") if isinstance(data.get("data"), dict) else data
            new_access = (tok_data or {}).get("access_token")
            if resp.status != 200 or not new_access:
                raise RuntimeError(f"TikTok token refresh failed ({resp.status}): {data}")
            new_refresh = str((tok_data or {}).get("refresh_token") or refresh_tok)
            expires_in = int((tok_data or {}).get("expires_in") or 86400)
            open_id = str((tok_data or {}).get("open_id") or "")
            _save_auth_tokens(str(new_access), new_refresh, expires_in, open_id)
            return str(new_access)

    async def publish_short(self, post: ChannelPost, video_path: Path) -> Optional[str]:
        if not self.is_configured():
            return None
        if not video_path.exists() or video_path.stat().st_size < 50_000:
            logger.warning("TikTok skip: видеофайл отсутствует или слишком мал (%s)", video_path)
            return None

        post_id = int(getattr(post, "id", 0) or 0)
        if post_id:
            existing = _already_uploaded(post_id)
            if existing:
                logger.info("TikTok skip: пост #%s уже отправлен во входящие (publish_id=%s)", post_id, existing)
                return existing

        video_size = video_path.stat().st_size
        if video_size <= _SINGLE_CHUNK_MAX_BYTES:
            chunk_size = video_size
            total_chunks = 1
        else:
            chunk_size = _MULTI_CHUNK_BYTES
            total_chunks = max(1, video_size // chunk_size)

        async with aiohttp.ClientSession(connector=build_vpn_connector("TIKTOK_USE_VPN")) as session:
            access_token = await self._ensure_access_token(session)

            # 1. Инициализация отправки во Входящие / Черновики TikTok
            init_payload = {
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunks,
                }
            }
            async with session.post(
                TIKTOK_INBOX_INIT_URL,
                json=init_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                timeout=aiohttp.ClientTimeout(total=40),
            ) as resp:
                init_data = await resp.json(content_type=None)
                err = init_data.get("error") or {}
                body = init_data.get("data") or {}
                if resp.status not in (200, 201) or (err.get("code") not in (None, "", "ok")):
                    raise RuntimeError(f"TikTok inbox init failed ({resp.status}): {init_data}")
                publish_id = str(body.get("publish_id") or "")
                upload_url = str(body.get("upload_url") or "")
                if not publish_id or not upload_url:
                    raise RuntimeError(f"TikTok inbox init missing publish_id/upload_url: {init_data}")

            # 2. Последовательная загрузка чанков MP4
            with video_path.open("rb") as fh:
                for idx in range(total_chunks):
                    start = idx * chunk_size
                    end = (video_size - 1) if (idx == total_chunks - 1) else (start + chunk_size - 1)
                    length = end - start + 1
                    fh.seek(start)
                    chunk_bytes = fh.read(length)
                    async with session.put(
                        upload_url,
                        data=chunk_bytes,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk_bytes)),
                            "Content-Range": f"bytes {start}-{end}/{video_size}",
                        },
                        timeout=aiohttp.ClientTimeout(total=240),
                    ) as up_resp:
                        if up_resp.status not in (200, 201, 206):
                            up_text = await up_resp.text()
                            raise RuntimeError(
                                f"TikTok chunk {idx + 1}/{total_chunks} failed ({up_resp.status}): {up_text[:300]}"
                            )

            # 3. Быстрая проверка статуса доставки во входящие (не блокируем при PROCESSING_UPLOAD)
            try:
                async with session.post(
                    TIKTOK_STATUS_URL,
                    json={"publish_id": publish_id},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as st_resp:
                    st_data = await st_resp.json(content_type=None)
                    st = (st_data.get("data") or {}).get("status")
                    if st == "FAILED":
                        raise RuntimeError(f"TikTok inbox upload FAILED: {st_data}")
                    logger.info("TikTok Inbox upload status для #%s: %s (publish_id=%s)", post_id, st, publish_id)
            except RuntimeError:
                raise
            except Exception as st_err:
                logger.debug("TikTok status check non-fatal: %s", st_err)

        if post_id:
            _mark_uploaded(post_id, publish_id)
        logger.info("Видео отправлено в TikTok Inbox для поста #%s (publish_id=%s)", post_id, publish_id)
        return publish_id
