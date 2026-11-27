"""
Периодическая синхронизация статистики Instagram Reels через AWG VPN
в общий файл /app/data/instagram_stats.json для отображения на /stats.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from bot.config import Settings
from bot.services.instagram_publisher import InstagramPublisher, _data_dir, _load_effective_token

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
    """Забирает профиль и список Reels (@kinojdun) и сохраняет в /app/data/instagram_stats.json."""
    ig = InstagramPublisher(settings)
    if not ig.is_configured():
        return {"ok": False, "enabled": False}

    token = _load_effective_token(ig.env_token)
    base = f"{ig._api_host(token)}/{ig.api_version}"
    uid = ig.ig_user_id

    result: dict[str, Any] = {
        "ok": False,
        "enabled": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "username": None,
        "followers": None,
        "media_count": None,
        "insights_available": None,
        "videos": [],
        "error": "",
    }

    try:
        async with aiohttp.ClientSession(connector=ig._connector()) as session:
            async with session.get(
                f"{base}/{uid}",
                params={"fields": "id,username,followers_count,media_count", "access_token": token},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                prof = await resp.json(content_type=None)
                if resp.status >= 400 or prof.get("error"):
                    result["error"] = str(prof.get("error") or resp.status)
                    _write_json_atomic(_stats_path(), result)
                    return result
                result["username"] = prof.get("username")
                result["followers"] = prof.get("followers_count")
                result["media_count"] = prof.get("media_count")

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
                    result["error"] = str(media_data.get("error") or resp.status)
                    _write_json_atomic(_stats_path(), result)
                    return result

            insights_supported = True
            for item in (media_data.get("data") or []):
                mid = str(item.get("id") or "")
                entry: dict[str, Any] = {
                    "id": mid,
                    "title": _extract_caption_title(item.get("caption") or ""),
                    "url": item.get("permalink") or "",
                    "date": str(item.get("timestamp") or "")[:16].replace("T", " "),
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
                                result["insights_available"] = True
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
                                result["insights_available"] = False
                    except Exception:
                        pass
                result["videos"].append(entry)

            if result["insights_available"] is None:
                result["insights_available"] = insights_supported
            result["ok"] = True
            _write_json_atomic(_stats_path(), result)
            return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.debug("Instagram stats sync error: %s", exc)
        try:
            if not _stats_path().exists():
                _write_json_atomic(_stats_path(), result)
        except Exception:
            pass
        return result
