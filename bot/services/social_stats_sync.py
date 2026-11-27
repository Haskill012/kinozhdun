"""
Периодическая синхронизация статистики соцсетей и видеоплатформ (Instagram Reels через AWG VPN,
YouTube Shorts, VK Клипы, Дзен кэш) в /app/data/instagram_stats.json и /app/data/stats_history.db.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from bot.config import Settings
from bot.services.instagram_publisher import InstagramPublisher, _data_dir, _load_effective_token
from shared.video_stats import (
    fetch_vk_group_stats,
    fetch_youtube_stats,
    read_json_first,
    record_snapshots,
)

logger = logging.getLogger(__name__)


def _stats_path() -> Path:
    return _data_dir() / "instagram_stats.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _extract_caption_title(caption: str) -> str:
    first = (caption or "").splitlines()[0].strip() if caption else ""
    first = first.lstrip("🍿🎬🔥 ").strip()
    return first[:80] or "Reels"


async def sync_instagram_stats(settings: Settings) -> dict[str, Any]:
    """Забирает профиль и список Reels (@kinojdun) и сохраняет срез истории по всем платформам."""
    data_dir = _data_dir()
    ig = InstagramPublisher(settings)
    ig_result: dict[str, Any] = {
        "ok": False,
        "enabled": ig.is_configured(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "username": None,
        "followers": None,
        "media_count": None,
        "insights_available": None,
        "videos": [],
        "error": "",
    }

    if ig.is_configured():
        token = _load_effective_token(ig.env_token)
        base = f"{ig._api_host(token)}/{ig.api_version}"
        uid = ig.ig_user_id
        try:
            async with aiohttp.ClientSession(connector=ig._connector()) as session:
                async with session.get(
                    f"{base}/{uid}",
                    params={"fields": "id,username,followers_count,media_count", "access_token": token},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    prof = await resp.json(content_type=None)
                    if resp.status >= 400 or prof.get("error"):
                        ig_result["error"] = str(prof.get("error") or resp.status)
                    else:
                        ig_result["username"] = prof.get("username")
                        ig_result["followers"] = prof.get("followers_count")
                        ig_result["media_count"] = prof.get("media_count")

                if not ig_result["error"]:
                    async with session.get(
                        f"{base}/{uid}/media",
                        params={
                            "fields": "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count",
                            "limit": "25",
                            "access_token": token,
                        },
                        timeout=aiohttp.ClientTimeout(total=25),
                    ) as resp:
                        media_data = await resp.json(content_type=None)
                        if resp.status >= 400 or media_data.get("error"):
                            ig_result["error"] = str(media_data.get("error") or resp.status)
                        else:
                            insights_supported = True
                            for item in (media_data.get("data") or []):
                                mid = str(item.get("id") or "")
                                ts_raw = str(item.get("timestamp") or "")
                                ts_epoch = None
                                if ts_raw:
                                    try:
                                        norm_ts = ts_raw[:-5] + "+00:00" if ts_raw.endswith("+0000") else ts_raw
                                        ts_epoch = int(datetime.fromisoformat(norm_ts).timestamp())
                                    except Exception:
                                        ts_epoch = None
                                entry: dict[str, Any] = {
                                    "id": mid,
                                    "title": _extract_caption_title(item.get("caption") or ""),
                                    "url": item.get("permalink") or "",
                                    "date": ts_raw[:16].replace("T", " "),
                                    "ts": ts_epoch,
                                    "status": str(item.get("media_product_type") or item.get("media_type") or "REELS"),
                                    "views": None,
                                    "reach": None,
                                    "likes": int(item.get("like_count") or 0),
                                    "comments": int(item.get("comments_count") or 0),
                                    "reposts": None,
                                    "saved": None,
                                }
                                if insights_supported and mid:
                                    try:
                                        async with session.get(
                                            f"{base}/{mid}/insights",
                                            params={"metric": "views,reach,shares,saved", "access_token": token},
                                            timeout=aiohttp.ClientTimeout(total=15),
                                        ) as ir:
                                            idata = await ir.json(content_type=None)
                                            err = idata.get("error") or {}
                                            if ir.status == 200 and isinstance(idata.get("data"), list):
                                                ig_result["insights_available"] = True
                                                for m in idata["data"]:
                                                    vals = m.get("values") or []
                                                    val = vals[0].get("value") if vals else None
                                                    if val is None:
                                                        continue
                                                    name = m.get("name")
                                                    if name == "views":
                                                        entry["views"] = int(val)
                                                    elif name == "reach":
                                                        entry["reach"] = int(val)
                                                    elif name == "shares":
                                                        entry["reposts"] = int(val)
                                                    elif name == "saved":
                                                        entry["saved"] = int(val)
                                            elif err.get("code") in (10, 190, 200):
                                                insights_supported = False
                                                ig_result["insights_available"] = False
                                    except Exception:
                                        pass
                                ig_result["videos"].append(entry)

                            if ig_result["insights_available"] is None:
                                ig_result["insights_available"] = insights_supported
                            ig_result["ok"] = True
        except Exception as exc:
            ig_result["error"] = f"{type(exc).__name__}: {exc}"
            logger.debug("Instagram stats sync error: %s", exc)

        if ig_result["ok"] or not _stats_path().exists():
            try:
                _write_json_atomic(_stats_path(), ig_result)
            except Exception:
                pass

    # Параллельно обновляем срез истории по всем доступным видеоплатформам (YT, VK, IG, Дзен)
    try:
        async with aiohttp.ClientSession() as plain_sess:
            yt_res = await fetch_youtube_stats(plain_sess)
            vk_res = await fetch_vk_group_stats(plain_sess)
        dz_res = read_json_first([Path("/app/dzen-data/dzen_video_stats.json"), data_dir / "dzen_video_stats.json"])
        ig_snap = ig_result if ig_result.get("ok") else read_json_first([_stats_path()])
        record_snapshots(
            data_dir,
            yt=yt_res,
            vk_members=vk_res.get("vk_members"),
            vk_clips=vk_res.get("vk_clips"),
            ig=ig_snap,
            dz=dz_res,
            min_interval_sec=540,
            force=False,
        )
    except Exception as exc:
        logger.debug("Video snapshots recording failed: %s", exc)

    return ig_result
