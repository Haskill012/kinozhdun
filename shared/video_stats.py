"""
Общий модуль сбора и исторического хранения статистики видео по платформам
(YouTube Shorts, VK Клипы, Instagram Reels, Дзен) в /app/data/stats_history.db.
Используется как ботом (периодические снимки каждые 10 мин), так и сайтом (/stats).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

PLATFORMS = ("yt", "vk", "ig", "dz")


async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    timeout_s: float = 8.0,
) -> dict:
    try:
        async with session.get(
            url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=timeout_s)
        ) as resp:
            if resp.status >= 400:
                return {"_http_error": resp.status, "_body": (await resp.text())[:200]}
            return await resp.json(content_type=None)
    except Exception as exc:
        return {"_exc": str(exc)}


async def fetch_youtube_stats(session: aiohttp.ClientSession) -> dict:
    out: dict[str, Any] = {
        "ok": False,
        "enabled": False,
        "followers": None,
        "channel_views": None,
        "videos": [],
        "error": "",
    }
    cid = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    csec = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    rtok = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()
    if not (cid and csec and rtok):
        return out
    out["enabled"] = True

    try:
        async with session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": cid,
                "client_secret": csec,
                "refresh_token": rtok,
                "grant_type": "refresh_token",
            },
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            tok_data = await resp.json(content_type=None)
            access_tok = tok_data.get("access_token")
            if resp.status >= 400 or not access_tok:
                out["error"] = str(tok_data.get("error_description") or tok_data.get("error") or resp.status)
                return out

        hdrs = {"Authorization": f"Bearer {access_tok}"}
        ch = await fetch_json(
            session,
            "https://www.googleapis.com/youtube/v3/channels",
            headers=hdrs,
            params={"part": "statistics,contentDetails", "mine": "true"},
        )
        items = ch.get("items") or []
        if not items:
            out["ok"] = True
            return out

        ch_stat = items[0].get("statistics") or {}
        out["followers"] = int(ch_stat.get("subscriberCount") or 0)
        out["channel_views"] = int(ch_stat.get("viewCount") or 0)
        uploads_pl = ((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if not uploads_pl:
            out["ok"] = True
            return out

        pl = await fetch_json(
            session,
            "https://www.googleapis.com/youtube/v3/playlistItems",
            headers=hdrs,
            params={"part": "contentDetails", "playlistId": uploads_pl, "maxResults": "25"},
        )
        vid_ids = [
            str((it.get("contentDetails") or {}).get("videoId") or "")
            for it in (pl.get("items") or [])
            if (it.get("contentDetails") or {}).get("videoId")
        ]
        if vid_ids:
            vdata = await fetch_json(
                session,
                "https://www.googleapis.com/youtube/v3/videos",
                headers=hdrs,
                params={"part": "snippet,statistics,status", "id": ",".join(vid_ids[:25])},
            )
            for v in (vdata.get("items") or []):
                vid = str(v.get("id") or "")
                sn = v.get("snippet") or {}
                st = v.get("statistics") or {}
                priv = str((v.get("status") or {}).get("privacyStatus") or "")
                pub_raw = str(sn.get("publishedAt") or "")
                pub_ts = None
                if pub_raw:
                    try:
                        pub_ts = int(datetime.fromisoformat(pub_raw.replace("Z", "+00:00")).timestamp())
                    except Exception:
                        pub_ts = None
                out["videos"].append({
                    "id": vid,
                    "title": str(sn.get("title") or "YouTube Short")[:90],
                    "url": f"https://youtube.com/shorts/{vid}" if vid else "",
                    "date": pub_raw[:16].replace("T", " "),
                    "ts": pub_ts,
                    "status": "Открыт" if priv == "public" else ("По ссылке" if priv == "unlisted" else "Приватный"),
                    "views": int(st.get("viewCount") or 0),
                    "likes": int(st.get("likeCount") or 0),
                    "comments": int(st.get("commentCount") or 0),
                    "reposts": None,
                })
        out["ok"] = True
    except Exception as exc:
        out["error"] = str(exc)
    return out


async def fetch_vk_group_stats(session: aiohttp.ClientSession) -> dict:
    """Возвращает подписчиков, посты стены и клипы ВК сообщества."""
    res: dict[str, Any] = {
        "vk_members": None,
        "vk_wall": [],
        "vk_clips": [],
        "vk_service_missing": False,
    }
    vk_token = os.getenv("VK_BOT_TOKEN", "").strip()
    vk_service = os.getenv("VK_SERVICE_TOKEN", "").strip()
    vk_gid = os.getenv("VK_GROUP_ID", "242087163").strip()

    if vk_token and vk_gid:
        d = await fetch_json(
            session,
            "https://api.vk.com/method/groups.getById",
            params={"access_token": vk_token, "v": "5.199", "group_id": vk_gid, "fields": "members_count"},
        )
        groups = (d.get("response") or {}).get("groups") or []
        if groups:
            res["vk_members"] = groups[0].get("members_count")

    if not (vk_service and vk_gid):
        res["vk_service_missing"] = True
        return res

    wall = await fetch_json(
        session,
        "https://api.vk.com/method/wall.get",
        params={"access_token": vk_service, "v": "5.199", "owner_id": f"-{vk_gid}", "count": "40"},
    )
    clip_ids: list[str] = []
    for idx, item in enumerate((wall.get("response") or {}).get("items") or []):
        if idx < 10:
            res["vk_wall"].append({
                "id": item.get("id"),
                "date": datetime.fromtimestamp(item.get("date", 0), tz=timezone.utc).strftime("%d.%m %H:%M"),
                "text": (item.get("text") or "").replace("\n", " ")[:70],
                "views": (item.get("views") or {}).get("count", 0),
                "likes": (item.get("likes") or {}).get("count", 0),
                "comments": (item.get("comments") or {}).get("count", 0),
                "reposts": (item.get("reposts") or {}).get("count", 0),
            })
        for att in (item.get("attachments") or []):
            if att.get("type") == "video":
                vid = att.get("video") or {}
                oid, vid_id = vid.get("owner_id"), vid.get("id")
                if oid is not None and vid_id is not None:
                    pair = f"{oid}_{vid_id}"
                    if pair not in clip_ids:
                        clip_ids.append(pair)

    if clip_ids:
        clips = await fetch_json(
            session,
            "https://api.vk.com/method/video.get",
            params={"access_token": vk_service, "v": "5.199", "videos": ",".join(clip_ids[:25]), "extended": "1"},
        )
        for v in (clips.get("response") or {}).get("items") or []:
            desc_line = ((v.get("description") or "").splitlines()[0] if v.get("description") else "").strip()
            raw_title = str(v.get("title") or "")
            clean_title = desc_line if (not raw_title or raw_title.startswith("Clip by")) and desc_line else raw_title
            oid, vid_id = v.get("owner_id"), v.get("id")
            v_ts = int(v.get("date") or 0) or None
            res["vk_clips"].append({
                "id": str(vid_id or ""),
                "title": (clean_title or "VK Клип")[:90],
                "url": f"https://vk.ru/clip{oid}_{vid_id}" if (oid is not None and vid_id is not None) else "",
                "date": datetime.fromtimestamp(v_ts, tz=timezone.utc).strftime("%d.%m %H:%M") if v_ts else "—",
                "ts": v_ts,
                "status": f"{v.get('duration', 0)}с" if v.get("duration") else "Опубликован",
                "views": int(v.get("views") or 0),
                "likes": int((v.get("likes") or {}).get("count") or 0),
                "comments": int(v.get("comments") or 0),
                "reposts": int((v.get("reposts") or {}).get("count") or 0),
            })

    return res


def read_json_first(paths: list[Path]) -> dict:
    for fpath in paths:
        if fpath.is_file():
            try:
                return json.loads(fpath.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("stats: %s read error: %s", fpath, exc)
    return {}


def _history_db(data_dir: Path) -> Path:
    return data_dir / "stats_history.db"


def _init_history_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS platform_snapshots (
            ts INTEGER NOT NULL,
            platform TEXT NOT NULL,
            subscribers INTEGER,
            videos INTEGER NOT NULL,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            reposts INTEGER,
            PRIMARY KEY (ts, platform)
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plat_ts ON platform_snapshots(platform, ts)")


def _agg_platform(items: list[dict], subs: int | None) -> tuple[int | None, int, int | None, int | None, int | None, int | None]:
    def _sum_opt(field: str) -> int | None:
        vals = [it.get(field) for it in items if it.get(field) is not None]
        if vals:
            return int(sum(vals))
        return 0 if items else None

    return subs, len(items), _sum_opt("views"), _sum_opt("likes"), _sum_opt("comments"), _sum_opt("reposts")


def record_snapshots(
    data_dir: Path,
    *,
    yt: dict | None = None,
    vk_members: int | None = None,
    vk_clips: list[dict] | None = None,
    ig: dict | None = None,
    dz: dict | None = None,
    min_interval_sec: int = 540,
    force: bool = False,
) -> bool:
    """Записывает срез метрик по всем готовым платформам в stats_history.db."""
    now_ts = int(time.time())
    rows_to_write: list[tuple] = []

    if yt and yt.get("ok"):
        rows_to_write.append((now_ts, "yt", *_agg_platform(yt.get("videos") or [], yt.get("followers"))))
    if vk_clips is not None and (vk_clips or vk_members is not None):
        rows_to_write.append((now_ts, "vk", *_agg_platform(vk_clips, vk_members)))
    if ig and ig.get("ok"):
        rows_to_write.append((now_ts, "ig", *_agg_platform(ig.get("videos") or [], ig.get("followers"))))
    if dz and dz.get("ok"):
        rows_to_write.append((now_ts, "dz", *_agg_platform(dz.get("videos") or [], dz.get("subscribers"))))

    if not rows_to_write:
        return False

    conn = sqlite3.connect(_history_db(data_dir), timeout=10)
    try:
        _init_history_db(conn)
        if not force:
            row = conn.execute("SELECT MAX(ts) FROM platform_snapshots").fetchone()
            last_ts = int(row[0] or 0) if row else 0
            if last_ts and (now_ts - last_ts) < min_interval_sec:
                return False
        else:
            # Даже при force не плодим чаще 1 раза в 60 секунд
            row = conn.execute("SELECT MAX(ts) FROM platform_snapshots").fetchone()
            last_ts = int(row[0] or 0) if row else 0
            if last_ts and (now_ts - last_ts) < 60:
                return False

        conn.executemany(
            """INSERT OR REPLACE INTO platform_snapshots
               (ts, platform, subscribers, videos, views, likes, comments, reposts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows_to_write,
        )
        conn.commit()
        return True
    except sqlite3.Error as exc:
        logger.warning("stats_history write error: %s", exc)
        return False
    finally:
        conn.close()


def load_history(data_dir: Path, max_days: int = 365) -> list[dict[str, Any]]:
    """Возвращает агрегированную по времени историю снимков для графика."""
    db_path = _history_db(data_dir)
    if not db_path.is_file():
        return []

    cutoff = int(time.time()) - max_days * 86400
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        _init_history_db(conn)
        rows = conn.execute(
            """SELECT ts, platform, subscribers, videos, views, likes, comments, reposts
               FROM platform_snapshots
               WHERE ts >= ?
               ORDER BY ts ASC""",
            (cutoff,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    by_ts: dict[int, dict[str, Any]] = {}
    for ts, plat, subs, vids, views, likes, comms, reps in rows:
        bucket = by_ts.setdefault(int(ts), {"ts": int(ts), "platforms": {}})
        bucket["platforms"][plat] = {
            "subscribers": subs,
            "videos": vids,
            "views": views,
            "likes": likes,
            "comments": comms,
            "reposts": reps,
        }

    # Если снимок одной платформы был записан на несколько секунд позже, объединяем окна в пределах 90 сек
    merged: list[dict[str, Any]] = []
    for ts in sorted(by_ts):
        cur = by_ts[ts]
        if merged and (ts - merged[-1]["ts"]) <= 90:
            merged[-1]["platforms"].update(cur["platforms"])
        else:
            merged.append(cur)
    return merged
