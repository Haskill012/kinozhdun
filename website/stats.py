import asyncio
import base64
import hmac
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import aiohttp
from aiohttp import web

from website import views

logger = logging.getLogger(__name__)

_CACHE: dict = {"ts": 0.0, "data": None}
CACHE_TTL_SECONDS = 600


def _check_basic_auth(request: web.Request) -> bool:
    expected_user = os.getenv("SITE_STATS_USER", "").strip()
    expected_pass = os.getenv("SITE_STATS_PASSWORD", "").strip()
    if not expected_user or not expected_pass:
        return False
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth[6:].strip()).decode("utf-8")
        user, password = decoded.split(":", 1)
    except Exception:
        return False
    return hmac.compare_digest(user, expected_user) and hmac.compare_digest(password, expected_pass)


def _ro_connect(db_path: Path):
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _collect_local_dbs(data_dir: Path) -> dict:
    stats = {
        "tg_bot": {"users": 0, "users_7d": 0, "tracked": 0, "notifications": 0, "referrals": [], "events": [], "top_titles": [], "recent_posts": []},
        "vk_bot": {"users": 0, "tracked": 0, "notifications": 0, "vk_posts": 0},
        "max_bot": {"users": 0, "tracked": 0, "notifications": 0, "channel_deliveries": 0},
        "site": {"titles": 0, "articles": 0, "last_sync": "—"},
    }

    con = _ro_connect(data_dir / "kinozhdun.db")
    if con:
        try:
            stats["tg_bot"]["users"] = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            stats["tg_bot"]["users_7d"] = con.execute("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')").fetchone()[0]
            stats["tg_bot"]["tracked"] = con.execute("SELECT COUNT(*) FROM tracked_items").fetchone()[0]
            stats["tg_bot"]["notifications"] = con.execute("SELECT COUNT(*) FROM notification_logs").fetchone()[0]
            stats["tg_bot"]["referrals"] = con.execute(
                "SELECT COALESCE(NULLIF(referral_source, ''), 'Прямой вход') AS src, COUNT(*) AS cnt "
                "FROM users GROUP BY src ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            stats["tg_bot"]["events"] = con.execute(
                "SELECT event_name, COUNT(*) AS cnt FROM analytics_events GROUP BY event_name ORDER BY cnt DESC LIMIT 15"
            ).fetchall()
            stats["tg_bot"]["top_titles"] = con.execute(
                "SELECT title, media_type, COUNT(*) AS cnt FROM tracked_items GROUP BY media_type, tmdb_id ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
            stats["tg_bot"]["recent_posts"] = con.execute(
                "SELECT id, post_type, title, status, COALESCE(published_at, created_at) FROM channel_posts ORDER BY id DESC LIMIT 10"
            ).fetchall()
            stats["vk_bot"]["vk_posts"] = con.execute("SELECT COUNT(*) FROM vk_posts").fetchone()[0]
        except sqlite3.Error as exc:
            logger.warning("stats: kinozhdun.db read error: %s", exc)
        finally:
            con.close()

    for key, fname in (("vk_bot", "kinozhdun_vk.db"), ("max_bot", "kinozhdun_max.db")):
        c = _ro_connect(data_dir / fname)
        if c:
            try:
                stats[key]["users"] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                stats[key]["tracked"] = c.execute("SELECT COUNT(*) FROM tracked_items").fetchone()[0]
                stats[key]["notifications"] = c.execute("SELECT COUNT(*) FROM notification_logs").fetchone()[0]
            except sqlite3.Error as exc:
                logger.warning("stats: %s read error: %s", fname, exc)
            finally:
                c.close()

    mc = _ro_connect(data_dir / "kinozhdun_max_channel.db")
    if mc:
        try:
            stats["max_bot"]["channel_deliveries"] = mc.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
        except sqlite3.Error:
            pass
        finally:
            mc.close()

    wc = _ro_connect(data_dir / "website.db")
    if wc:
        try:
            stats["site"]["titles"] = wc.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
            stats["site"]["articles"] = wc.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            row = wc.execute("SELECT value FROM state WHERE key='last_sync'").fetchone()
            if row and row[0]:
                stats["site"]["last_sync"] = row[0][:19].replace("T", " ")
        except sqlite3.Error:
            pass
        finally:
            wc.close()

    for key, fname in (("instagram_cache", "instagram_stats.json"), ("dzen_cache", "dzen_video_stats.json")):
        fpath = data_dir / fname
        if fpath.is_file():
            try:
                stats[key] = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("stats: %s read error: %s", fname, exc)
                stats[key] = {}
        else:
            stats[key] = {}

    return stats


async def _fetch_json(session: aiohttp.ClientSession, url: str, headers: dict | None = None, params: dict | None = None, timeout_s: float = 6.0):
    try:
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
            if resp.status >= 400:
                return {"_http_error": resp.status, "_body": (await resp.text())[:200]}
            return await resp.json(content_type=None)
    except Exception as exc:
        return {"_exc": str(exc)}


async def _fetch_metrika(session: aiohttp.ClientSession, counter_id: str, token: str) -> dict:
    out = {"ok": False, "error": "", "periods": {}, "sources": [], "landing_pages": [], "goals": []}
    if not counter_id or not token:
        out["error"] = "Не задан SITE_YANDEX_METRIKA_ID или YANDEX_METRIKA_TOKEN"
        return out

    headers = {"Authorization": f"OAuth {token}"}
    api = "https://api-metrika.yandex.net/stat/v1/data"

    for label, d1 in (("today", "today"), ("7d", "7daysAgo"), ("30d", "30daysAgo")):
        res = await _fetch_json(session, api, headers=headers, params={
            "ids": counter_id,
            "metrics": "ym:s:visits,ym:s:users,ym:s:pageviews,ym:s:bounceRate,ym:s:avgVisitDurationSeconds",
            "date1": d1,
            "date2": "today",
        })
        if "_http_error" in res or "_exc" in res or "errors" in res:
            out["error"] = str(res.get("_http_error") or res.get("_exc") or res.get("errors"))
            return out
        totals = res.get("totals") or [0, 0, 0, 0, 0]
        out["periods"][label] = {
            "visits": int(totals[0] or 0),
            "users": int(totals[1] or 0),
            "pageviews": int(totals[2] or 0),
            "bounce": round(float(totals[3] or 0), 1),
            "avg_sec": int(totals[4] or 0),
        }

    # Источники переходов за 30 дней
    src_res = await _fetch_json(session, api, headers=headers, params={
        "ids": counter_id,
        "dimensions": "ym:s:lastsignTrafficSource,ym:s:lastsignSourceEngine",
        "metrics": "ym:s:visits,ym:s:users",
        "date1": "30daysAgo",
        "date2": "today",
        "sort": "-ym:s:visits",
        "limit": 12,
    })
    for row in src_res.get("data") or []:
        dims = row.get("dimensions") or []
        mets = row.get("metrics") or [0, 0]
        s_type = dims[0].get("name") if len(dims) > 0 else "—"
        s_eng = dims[1].get("name") if len(dims) > 1 and dims[1].get("name") else "—"
        out["sources"].append((s_type, s_eng, int(mets[0]), int(mets[1])))

    # Точки входа (включая ?from=dzen / ?from=vk-clips)
    land_res = await _fetch_json(session, api, headers=headers, params={
        "ids": counter_id,
        "dimensions": "ym:s:startURL",
        "metrics": "ym:s:visits,ym:s:users",
        "date1": "30daysAgo",
        "date2": "today",
        "sort": "-ym:s:visits",
        "limit": 12,
    })
    for row in land_res.get("data") or []:
        dims = row.get("dimensions") or []
        mets = row.get("metrics") or [0, 0]
        url = dims[0].get("name") if dims else "—"
        out["landing_pages"].append((url, int(mets[0]), int(mets[1])))

    # Цели сайта (bot_click, watchlist_click, channel_click)
    goals_list = await _fetch_json(
        session,
        f"https://api-metrika.yandex.net/management/v1/counter/{counter_id}/goals",
        headers=headers,
    )
    for g in (goals_list.get("goals") or []):
        gid = g.get("id")
        gname = g.get("name") or f"Goal #{gid}"
        gres = await _fetch_json(session, api, headers=headers, params={
            "ids": counter_id,
            "metrics": f"ym:s:goal{gid}reaches,ym:s:goal{gid}users",
            "date1": "30daysAgo",
            "date2": "today",
        })
        gtot = gres.get("totals") or [0, 0]
        out["goals"].append((gname, gid, int(gtot[0] or 0), int(gtot[1] or 0)))

    out["ok"] = True
    return out


async def _fetch_youtube(session: aiohttp.ClientSession) -> dict:
    out = {"ok": False, "enabled": False, "followers": None, "channel_views": None, "videos": [], "error": ""}
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
        ch = await _fetch_json(
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

        pl = await _fetch_json(
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
            vdata = await _fetch_json(
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
                pub_at = str(sn.get("publishedAt") or "")[:16].replace("T", " ")
                out["videos"].append({
                    "id": vid,
                    "title": str(sn.get("title") or "YouTube Short")[:90],
                    "url": f"https://youtube.com/shorts/{vid}" if vid else "",
                    "date": pub_at,
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


async def _fetch_socials(session: aiohttp.ClientSession) -> dict:
    res = {
        "vk_members": None,
        "vk_wall": [],
        "vk_clips": [],
        "vk_service_missing": False,
        "max_members": None,
        "max_posts": [],
        "tg_members": None,
    }

    vk_token = os.getenv("VK_BOT_TOKEN", "").strip()
    vk_service = os.getenv("VK_SERVICE_TOKEN", "").strip()
    vk_gid = os.getenv("VK_GROUP_ID", "242087163").strip()

    if vk_token and vk_gid:
        d = await _fetch_json(session, "https://api.vk.com/method/groups.getById", params={
            "access_token": vk_token, "v": "5.199", "group_id": vk_gid, "fields": "members_count",
        })
        groups = (d.get("response") or {}).get("groups") or []
        if groups:
            res["vk_members"] = groups[0].get("members_count")

    if vk_service and vk_gid:
        wall = await _fetch_json(session, "https://api.vk.com/method/wall.get", params={
            "access_token": vk_service, "v": "5.199", "owner_id": f"-{vk_gid}", "count": "40",
        })
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
            clips = await _fetch_json(session, "https://api.vk.com/method/video.get", params={
                "access_token": vk_service, "v": "5.199", "videos": ",".join(clip_ids[:25]), "extended": "1",
            })
            for v in (clips.get("response") or {}).get("items") or []:
                desc_line = ((v.get("description") or "").splitlines()[0] if v.get("description") else "").strip()
                raw_title = str(v.get("title") or "")
                clean_title = desc_line if (not raw_title or raw_title.startswith("Clip by")) and desc_line else raw_title
                oid, vid_id = v.get("owner_id"), v.get("id")
                res["vk_clips"].append({
                    "id": str(vid_id or ""),
                    "title": (clean_title or "VK Клип")[:90],
                    "url": f"https://vk.ru/clip{oid}_{vid_id}" if (oid is not None and vid_id is not None) else "",
                    "date": datetime.fromtimestamp(v.get("date", 0), tz=timezone.utc).strftime("%d.%m %H:%M") if v.get("date") else "—",
                    "status": f"{v.get('duration', 0)}с" if v.get("duration") else "Опубликован",
                    "views": int(v.get("views") or 0),
                    "likes": int((v.get("likes") or {}).get("count") or 0),
                    "comments": int(v.get("comments") or 0),
                    "reposts": int((v.get("reposts") or {}).get("count") or 0),
                })
    else:
        res["vk_service_missing"] = True

    max_tok = os.getenv("MAX_BOT_TOKEN", "").strip()
    max_cid = os.getenv("MAX_CHANNEL_ID", "").strip()
    if max_tok and max_cid:
        mc = await _fetch_json(session, f"https://platform-api.max.ru/chats/{max_cid}", headers={"Authorization": max_tok})
        if "participants_count" in mc:
            res["max_members"] = mc["participants_count"]
        mm = await _fetch_json(
            session,
            "https://platform-api.max.ru/messages",
            headers={"Authorization": max_tok},
            params={"chat_id": max_cid, "count": "15"},
        )
        for msg in (mm.get("messages") or []):
            body = msg.get("body") or {}
            txt = (body.get("text") or "").replace("\n", " ").strip()
            ts_ms = int(msg.get("timestamp") or 0)
            dt_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%d.%m %H:%M") if ts_ms else "—"
            res["max_posts"].append({
                "date": dt_str,
                "text": txt[:75] or "Пост с медиа",
                "views": int((msg.get("stat") or {}).get("views") or 0),
            })

    tg_tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_cid = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if tg_tok and tg_cid:
        tg = await _fetch_json(
            session,
            f"https://api.telegram.org/bot{tg_tok}/getChatMemberCount",
            params={"chat_id": tg_cid},
            timeout_s=2.5,
        )
        if tg.get("ok"):
            res["tg_members"] = tg.get("result")

    return res


async def collect_stats(config: dict, force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] is not None and (now - _CACHE["ts"]) < CACHE_TTL_SECONDS:
        return _CACHE["data"]

    data_dir = Path(config["database"]).parent
    local_task = asyncio.to_thread(_collect_local_dbs, data_dir)

    async with aiohttp.ClientSession() as session:
        metrika_task = _fetch_metrika(session, config.get("yandex_metrika_id", ""), os.getenv("YANDEX_METRIKA_TOKEN", "").strip())
        socials_task = _fetch_socials(session)
        youtube_task = _fetch_youtube(session)
        local_stats, metrika, socials, youtube = await asyncio.gather(local_task, metrika_task, socials_task, youtube_task)

    payload = {
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "local": local_stats,
        "metrika": metrika,
        "socials": socials,
        "youtube": youtube,
    }
    _CACHE["ts"] = now
    _CACHE["data"] = payload
    return payload


def _render_html(config: dict, data: dict) -> str:
    loc = data["local"]
    met = data["metrika"]
    soc = data["socials"]
    yt = data.get("youtube") or {}
    ig = loc.get("instagram_cache") or {}
    dz = loc.get("dzen_cache") or {}

    p7 = met["periods"].get("7d", {})
    p30 = met["periods"].get("30d", {})
    ptod = met["periods"].get("today", {})

    tg_ch = str(soc["tg_members"]) if soc["tg_members"] is not None else "—"
    vk_ch = str(soc["vk_members"]) if soc["vk_members"] is not None else "—"
    max_ch = str(soc["max_members"]) if soc["max_members"] is not None else "—"
    yt_ch = str(yt["followers"]) if yt.get("followers") is not None else "—"
    ig_ch = str(ig["followers"]) if ig.get("followers") is not None else "—"
    dz_ch = str(dz["subscribers"]) if dz.get("subscribers") is not None else "—"

    def _fmt_num(val) -> str:
        return "—" if val is None else f"{int(val):,}".replace(",", " ")

    def _sum_opt(items: list[dict], field: str) -> int | None:
        vals = [it.get(field) for it in items if it.get(field) is not None]
        return sum(vals) if vals else (0 if items else None)

    yt_videos = yt.get("videos") or []
    vk_clips = soc.get("vk_clips") or []
    ig_videos = ig.get("videos") or []
    dz_videos = dz.get("videos") or []

    platform_specs = [
        ("yt", "YouTube Shorts", yt_ch, yt_videos, "Data API v3 (без репостов)"),
        ("vk", "VK Клипы", vk_ch, vk_clips, "VK API video.get"),
        (
            "ig",
            "Instagram Reels",
            ig_ch,
            ig_videos,
            "Лайки/комменты" if ig.get("insights_available") is False else ("Graph API + Insights" if ig.get("ok") else "Синк каждые 10 мин через VPN"),
        ),
        (
            "dz",
            "Дзен (Ролики)",
            dz_ch,
            dz_videos,
            "Дзен Студия (показы + просмотры)" if dz.get("ok") else "Обновляется раз в 30 мин",
        ),
    ]

    plat_rows = []
    tot_vids = 0
    tot_views = 0
    tot_likes = 0
    tot_comments = 0
    tot_reposts = 0
    all_video_rows: list[dict] = []

    for pkey, pname, psubs, plist, pnote in platform_specs:
        v_views = _sum_opt(plist, "views")
        v_likes = _sum_opt(plist, "likes")
        v_comm = _sum_opt(plist, "comments")
        v_rep = _sum_opt(plist, "reposts")

        tot_vids += len(plist)
        tot_views += v_views or 0
        tot_likes += v_likes or 0
        tot_comments += v_comm or 0
        tot_reposts += v_rep or 0

        plat_rows.append(
            f"<tr><td><strong>{escape(pname)}</strong></td>"
            f"<td>{escape(psubs)}</td>"
            f"<td>{len(plist)}</td>"
            f"<td><strong>{_fmt_num(v_views)}</strong></td>"
            f"<td>{_fmt_num(v_likes)}</td>"
            f"<td>{_fmt_num(v_comm)}</td>"
            f"<td>{_fmt_num(v_rep)}</td>"
            f"<td class='st-note'>{escape(pnote)}</td></tr>"
        )
        for item in plist:
            all_video_rows.append({"pkey": pkey, "pname": pname, **item})

    plat_rows.append(
        f"<tr class='st-total'><td><strong>Итого по видео</strong></td><td>—</td><td><strong>{tot_vids}</strong></td>"
        f"<td><strong>{_fmt_num(tot_views)}</strong></td><td><strong>{_fmt_num(tot_likes)}</strong></td>"
        f"<td><strong>{_fmt_num(tot_comments)}</strong></td><td><strong>{_fmt_num(tot_reposts)}</strong></td><td></td></tr>"
    )
    platform_summary_rows = "".join(plat_rows)

    def _video_link(item: dict) -> str:
        t = escape(str(item.get("title") or "Ролик"))
        url = str(item.get("url") or "").strip()
        if url.startswith("https://"):
            return f"<a href='{escape(url)}' target='_blank' rel='noopener' class='st-link'>{t}</a>"
        return t

    video_detail_rows = []
    for it in all_video_rows:
        extra = ""
        if it["pkey"] == "dz" and it.get("impressions") is not None:
            extra = f" <span class='st-note'>(показов: {_fmt_num(it.get('impressions'))})</span>"
        elif it["pkey"] == "ig" and it.get("saved") is not None:
            extra = f" <span class='st-note'>(сохр: {_fmt_num(it.get('saved'))})</span>"
        video_detail_rows.append(
            f"<tr data-plat='{escape(it['pkey'])}'>"
            f"<td><span class='st-badge st-b-{escape(it['pkey'])}'>{escape(it['pname'])}</span></td>"
            f"<td>{_video_link(it)}</td>"
            f"<td>{escape(str(it.get('date') or '—'))}<br><span class='st-note'>{escape(str(it.get('status') or ''))}</span></td>"
            f"<td><strong>{_fmt_num(it.get('views'))}</strong>{extra}</td>"
            f"<td>{_fmt_num(it.get('likes'))}</td>"
            f"<td>{_fmt_num(it.get('comments'))}</td>"
            f"<td>{_fmt_num(it.get('reposts'))}</td>"
            f"</tr>"
        )
    video_table_html = "".join(video_detail_rows) or "<tr><td colspan='7'>Видео пока не найдены</td></tr>"
    ig_insights_note = (
        "<p class='st-note'>Подсказка по Instagram Reels: сейчас отображаются лайки и комментарии; чтобы подтягивались и просмотры/репосты/сохранения Reels, добавьте право <code>instagram_manage_insights</code> системному пользователю в Meta Business Suite и обновите токен.</p>"
        if ig.get("ok") and ig.get("insights_available") is False
        else ""
    )

    traffic_type_ru = {
        "Direct traffic": "Прямые заходы",
        "Search engine traffic": "Поиск",
        "Recommendation system traffic": "Рекомендации",
        "Link traffic": "По ссылкам с сайтов",
        "Social network traffic": "Соцсети",
        "Messenger traffic": "Мессенджеры",
        "Internal traffic": "Внутренние переходы",
        "Advertising traffic": "Реклама",
        "Cached page traffic": "Сохранённые страницы",
    }
    engine_ru = {
        "Yandex Zen": "Дзен",
    }

    sources_rows = "".join(
        f"<tr><td>{escape(traffic_type_ru.get(s, s))}</td><td>{escape(engine_ru.get(e, e))}</td><td>{v}</td><td>{u}</td></tr>"
        for s, e, v, u in met["sources"]
    ) or "<tr><td colspan='4'>Нет данных за 30 дней</td></tr>"

    land_rows = "".join(
        f"<tr><td style='word-break:break-all'>{escape(u)}</td><td>{v}</td><td>{usr}</td></tr>"
        for u, v, usr in met["landing_pages"]
    ) or "<tr><td colspan='3'>Нет данных</td></tr>"

    goals_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{reaches}</td><td>{users}</td></tr>"
        for name, _gid, reaches, users in met["goals"]
    ) or "<tr><td colspan='3'>Цели в Метрике не найдены или ещё нет достижений</td></tr>"

    def _human_ref(src: str) -> str:
        s = (src or "").strip()
        if not s or s == "organic":
            return "Прямой запуск / поиск в Telegram"
        if s.startswith("unknown:ref_") or s.startswith("ref_"):
            return "По приглашению друга"
        if "channel" in s:
            return "Из Telegram-канала"
        if "site" in s or "kinojdun" in s:
            return "С сайта kinojdun.ru"
        return s

    event_ru = {
        "channel_link_opened": "Открыли ссылку из Telegram-канала",
        "content_followed_from_channel": "Подписались на релиз из канала",
        "share_link_opened": "Открыли ссылку «Поделиться»",
        "content_followed_from_share": "Подписались на релиз по ссылке друга",
        "content_shared": "Поделились фильмом/сериалом",
        "watchlist_shared": "Поделились списком ожидания",
        "watchlist_link_opened": "Открыли чужой список ожидания",
        "watchlist_item_followed": "Подписались на релиз из списка",
        "watchlist_follow_all": "Подписались на весь список",
    }

    ref_rows = "".join(
        f"<tr><td>{escape(_human_ref(str(src)))}</td><td>{cnt}</td></tr>"
        for src, cnt in loc["tg_bot"]["referrals"]
    ) or "<tr><td colspan='2'>Нет данных</td></tr>"

    ev_rows = "".join(
        f"<tr><td>{escape(event_ru.get(name, name))}</td><td>{cnt}</td></tr>"
        for name, cnt in loc["tg_bot"]["events"]
    ) or "<tr><td colspan='2'>Событий пока нет</td></tr>"

    top_rows = "".join(
        f"<tr><td>{escape(title)}</td><td>{escape(mtype)}</td><td>{cnt}</td></tr>"
        for title, mtype, cnt in loc["tg_bot"]["top_titles"]
    ) or "<tr><td colspan='3'>Отслеживаний пока нет</td></tr>"

    posts_rows = "".join(
        f"<tr><td>#{pid}</td><td>{escape(str(ptype))}</td><td>{escape(str(title))}</td><td>{escape(str(st))}</td><td>{escape(str(dt)[:16])}</td></tr>"
        for pid, ptype, title, st, dt in loc["tg_bot"]["recent_posts"]
    ) or "<tr><td colspan='5'>Постов нет</td></tr>"

    vk_wall_html = ""
    if soc["vk_wall"]:
        wrows = "".join(
            f"<tr><td>{escape(w['date'])}</td><td>{escape(w['text'])}</td><td>{w['views']}</td><td>{w['likes']}</td><td>{w['comments']}</td><td>{w['reposts']}</td></tr>"
            for w in soc["vk_wall"]
        )
        vk_wall_html = f"<h3>Последние посты на стене ВК</h3><table class='st-table'><thead><tr><th>Дата</th><th>Текст</th><th>Просмотры</th><th>Лайки</th><th>Комменты</th><th>Репосты</th></tr></thead><tbody>{wrows}</tbody></table>"
    elif soc["vk_service_missing"]:
        vk_wall_html = "<p class='st-note'>Для просмотров, лайков и комментариев постов/клипов ВК добавьте <code>VK_SERVICE_TOKEN</code> в <code>.env</code>.</p>"

    max_posts_html = ""
    if soc.get("max_posts"):
        mrows = "".join(
            f"<tr><td>{escape(m['date'])}</td><td>{escape(m['text'])}</td><td>{m['views']}</td></tr>"
            for m in soc["max_posts"]
        )
        max_posts_html = f"<h3>Последние публикации в канале MAX</h3><table class='st-table'><thead><tr><th>Дата</th><th>Текст</th><th>Просмотры</th></tr></thead><tbody>{mrows}</tbody></table>"

    metrika_err = f"<p class='st-warn'>Ошибка Яндекс.Метрики: {escape(met['error'])}</p>" if not met["ok"] else ""

    content = f"""
    <style>
      .st-wrap{{max-width:1160px;margin:0 auto;padding:36px 20px 80px}}
      .st-head{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;margin-bottom:24px}}
      .st-head h1{{margin:0;font-size:clamp(26px,4vw,36px)}}
      .st-btn{{display:inline-block;padding:10px 16px;border-radius:10px;background:#a7ef46;color:#111;font-weight:700;text-decoration:none}}
      .st-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:28px}}
      .st-card{{padding:18px;border:1px solid rgba(255,255,255,.12);border-radius:16px;background:rgba(255,255,255,.03)}}
      .st-card small{{display:block;color:var(--muted,#9aa39d);margin-bottom:6px;font-size:13px}}
      .st-card strong{{font-size:26px;color:#a7ef46;display:block;line-height:1.2}}
      .st-card span{{font-size:13px;color:var(--muted,#9aa39d)}}
      .st-sec{{margin-bottom:32px}}
      .st-sec h2{{font-size:20px;margin:0 0 12px;border-bottom:1px solid rgba(255,255,255,.1);padding-bottom:8px}}
      .st-sec h3{{font-size:16px;margin:18px 0 8px}}
      .st-cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}}
      .st-table-wrap{{overflow-x:auto}}
      .st-table{{width:100%;border-collapse:collapse;font-size:14px}}
      .st-table th,.st-table td{{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.08);vertical-align:top}}
      .st-table th{{color:var(--muted,#9aa39d);font-weight:600;white-space:nowrap}}
      .st-total td{{border-top:2px solid rgba(167,239,70,.35);background:rgba(167,239,70,.05)}}
      .st-note{{color:var(--muted,#9aa39d);font-size:13px}}
      .st-warn{{padding:12px 14px;border-radius:10px;background:rgba(255,100,100,.14);border:1px solid rgba(255,100,100,.4)}}
      .st-link{{color:#e7f6d5;text-decoration:underline;text-underline-offset:3px}}
      .st-link:hover{{color:#a7ef46}}
      .st-filters{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
      .st-pill{{border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.04);color:#e9eee9;padding:6px 12px;border-radius:999px;cursor:pointer;font-size:13px}}
      .st-pill.active{{background:#a7ef46;color:#111;border-color:#a7ef46;font-weight:700}}
      .st-badge{{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}}
      .st-b-yt{{background:rgba(255,68,68,.18);color:#ff8a8a}}
      .st-b-vk{{background:rgba(68,138,255,.18);color:#8ab4ff}}
      .st-b-ig{{background:rgba(225,48,108,.18);color:#ff85b3}}
      .st-b-dz{{background:rgba(167,239,70,.16);color:#b7f468}}
    </style>
    <main class="st-wrap">
      <div class="st-head">
        <div>
          <h1>Статистика КиноЖдуна</h1>
          <span class="st-note">Обновлено: {escape(data['generated_at'])} (кэш 10 мин)</span>
        </div>
        <a class="st-btn" href="/stats?refresh=1">Обновить сейчас</a>
      </div>

      {metrika_err}

      <div class="st-grid">
        <div class="st-card">
          <small>Сайт (Яндекс.Метрика)</small>
          <strong>{p30.get('visits', 0)} визитов</strong>
          <span>Сегодня: {ptod.get('visits', 0)} · 7 дн: {p7.get('visits', 0)} · Просмотров (30д): {p30.get('pageviews', 0)}</span>
        </div>
        <div class="st-card">
          <small>Каналы и видеопрофили</small>
          <strong>VK: {vk_ch} · YT: {yt_ch} · IG: {ig_ch}</strong>
          <span>TG: {tg_ch} · MAX: {max_ch} · Дзен: {dz_ch}</span>
        </div>
        <div class="st-card">
          <small>Видео (просмотры / лайки)</small>
          <strong>{_fmt_num(tot_views)} просм.</strong>
          <span>Роликов: {tot_vids} · Лайков: {_fmt_num(tot_likes)} · Комментов: {_fmt_num(tot_comments)} · Репостов: {_fmt_num(tot_reposts)}</span>
        </div>
        <div class="st-card">
          <small>Боты и база</small>
          <strong>{loc['tg_bot']['users'] + loc['vk_bot']['users'] + loc['max_bot']['users']} юзеров</strong>
          <span>TG: {loc['tg_bot']['users']} (+{loc['tg_bot']['users_7d']} за 7д) · Подписок: {loc['tg_bot']['tracked'] + loc['vk_bot']['tracked'] + loc['max_bot']['tracked']} · TMDB: {loc['site']['titles']}</span>
        </div>
      </div>

      <section class="st-sec">
        <h2>Видео по платформам (YouTube Shorts · VK Клипы · Instagram Reels · Дзен)</h2>
        <div class="st-table-wrap">
          <table class="st-table">
            <thead><tr><th>Платформа</th><th>Подписчики</th><th>Роликов</th><th>Просмотры</th><th>Лайки</th><th>Комменты</th><th>Репосты</th><th>Примечание</th></tr></thead>
            <tbody>{platform_summary_rows}</tbody>
          </table>
        </div>
        {ig_insights_note}
        <h3>Статистика по каждому ролику</h3>
        <div class="st-filters">
          <button type="button" class="st-pill active" onclick="filterVideos('all', this)">Все ({len(all_video_rows)})</button>
          <button type="button" class="st-pill" onclick="filterVideos('yt', this)">YouTube Shorts ({len(yt_videos)})</button>
          <button type="button" class="st-pill" onclick="filterVideos('vk', this)">VK Клипы ({len(vk_clips)})</button>
          <button type="button" class="st-pill" onclick="filterVideos('ig', this)">Instagram Reels ({len(ig_videos)})</button>
          <button type="button" class="st-pill" onclick="filterVideos('dz', this)">Дзен ({len(dz_videos)})</button>
        </div>
        <div class="st-table-wrap">
          <table class="st-table" id="st-videos-table">
            <thead><tr><th>Платформа</th><th>Ролик</th><th>Дата / статус</th><th>Просмотры</th><th>Лайки</th><th>Комменты</th><th>Репосты</th></tr></thead>
            <tbody>{video_table_html}</tbody>
          </table>
        </div>
      </section>
      <script>
        function filterVideos(plat, btn) {{
          document.querySelectorAll('.st-pill').forEach(b => b.classList.remove('active'));
          if (btn) btn.classList.add('active');
          document.querySelectorAll('#st-videos-table tbody tr[data-plat]').forEach(tr => {{
            tr.style.display = (plat === 'all' || tr.dataset.plat === plat) ? '' : 'none';
          }});
        }}
      </script>

      <section class="st-sec">
        <h2>Яндекс.Метрика: откуда приходят и куда переходят (30 дней)</h2>
        <div class="st-cols">
          <div>
            <h3>Источники трафика</h3>
            <table class="st-table">
              <thead><tr><th>Тип</th><th>Источник</th><th>Визиты</th><th>Люди</th></tr></thead>
              <tbody>{sources_rows}</tbody>
            </table>
          </div>
          <div>
            <h3>Точки входа (включая ?from=...)</h3>
            <table class="st-table">
              <thead><tr><th>Страница входа</th><th>Визиты</th><th>Люди</th></tr></thead>
              <tbody>{land_rows}</tbody>
            </table>
          </div>
        </div>
        <h3>Действия на сайте (куда кликают посетители за 30 дней)</h3>
        <table class="st-table">
          <thead><tr><th>Действие</th><th>Кликов (всего)</th><th>Уникальных людей</th></tr></thead>
          <tbody>{goals_rows}</tbody>
        </table>
      </section>

      <section class="st-sec">
        <h2>Боты: откуда приходят люди и что делают</h2>
        <div class="st-cols">
          <div>
            <h3>Откуда пришли в Telegram-бот</h3>
            <table class="st-table">
              <thead><tr><th>Источник</th><th>Пользователей</th></tr></thead>
              <tbody>{ref_rows}</tbody>
            </table>
          </div>
          <div>
            <h3>Активность внутри Telegram-бота</h3>
            <table class="st-table">
              <thead><tr><th>Действие</th><th>Кол-во</th></tr></thead>
              <tbody>{ev_rows}</tbody>
            </table>
          </div>
          <div>
            <h3>Топ отслеживаемых проектов</h3>
            <table class="st-table">
              <thead><tr><th>Название</th><th>Тип</th><th>Подписок</th></tr></thead>
              <tbody>{top_rows}</tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="st-sec">
        <h2>Публикации и соцсети</h2>
        <p class="st-note">Постов VK в БД: {loc['vk_bot']['vk_posts']} · Отправок в канал MAX: {loc['max_bot']['channel_deliveries']} · Последний синк TMDB: {escape(loc['site']['last_sync'])}</p>
        {vk_wall_html}
        {max_posts_html}
        <h3>Последние посты в Telegram-канале / шортсы</h3>
        <table class="st-table">
          <thead><tr><th>ID</th><th>Тип</th><th>Заголовок</th><th>Статус</th><th>Дата</th></tr></thead>
          <tbody>{posts_rows}</tbody>
        </table>
      </section>
    </main>
    """
    return views.layout(config, "Статистика КиноЖдуна", "Закрытая статистика проекта.", content, noindex=True)


async def stats_handler(request: web.Request, config: dict) -> web.Response:
    if not _check_basic_auth(request):
        return web.Response(
            status=401,
            text="Требуется авторизация",
            headers={
                "WWW-Authenticate": 'Basic realm="Kinojdun Stats"',
                "X-Robots-Tag": "noindex, nofollow",
                "Cache-Control": "no-store",
            },
        )
    force = request.query.get("refresh") == "1"
    data = await collect_stats(config, force=force)
    return web.Response(
        text=_render_html(config, data),
        content_type="text/html",
        headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"},
    )
