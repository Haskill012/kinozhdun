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


async def _fetch_socials(session: aiohttp.ClientSession) -> dict:
    res = {
        "vk_members": None,
        "vk_wall": [],
        "vk_clips": [],
        "vk_service_missing": False,
        "max_members": None,
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
            "access_token": vk_service, "v": "5.199", "owner_id": f"-{vk_gid}", "count": "10",
        })
        for item in (wall.get("response") or {}).get("items") or []:
            res["vk_wall"].append({
                "id": item.get("id"),
                "date": datetime.fromtimestamp(item.get("date", 0), tz=timezone.utc).strftime("%d.%m %H:%M"),
                "text": (item.get("text") or "").replace("\n", " ")[:70],
                "views": (item.get("views") or {}).get("count", 0),
                "likes": (item.get("likes") or {}).get("count", 0),
                "comments": (item.get("comments") or {}).get("count", 0),
                "reposts": (item.get("reposts") or {}).get("count", 0),
            })
        clips = await _fetch_json(session, "https://api.vk.com/method/video.get", params={
            "access_token": vk_service, "v": "5.199", "owner_id": f"-{vk_gid}", "count": "10",
        })
        for v in (clips.get("response") or {}).get("items") or []:
            res["vk_clips"].append({
                "title": (v.get("title") or "Клип")[:60],
                "views": v.get("views", 0),
                "likes": (v.get("likes") or {}).get("count", 0),
                "comments": v.get("comments", 0),
            })
    else:
        res["vk_service_missing"] = True

    max_tok = os.getenv("MAX_BOT_TOKEN", "").strip()
    max_cid = os.getenv("MAX_CHANNEL_ID", "").strip()
    if max_tok and max_cid:
        mc = await _fetch_json(session, f"https://platform-api.max.ru/chats/{max_cid}", headers={"Authorization": max_tok})
        if "participants_count" in mc:
            res["max_members"] = mc["participants_count"]

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
        local_stats, metrika, socials = await asyncio.gather(local_task, metrika_task, socials_task)

    payload = {
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "local": local_stats,
        "metrika": metrika,
        "socials": socials,
    }
    _CACHE["ts"] = now
    _CACHE["data"] = payload
    return payload


def _render_html(config: dict, data: dict) -> str:
    loc = data["local"]
    met = data["metrika"]
    soc = data["socials"]

    p7 = met["periods"].get("7d", {})
    p30 = met["periods"].get("30d", {})
    ptod = met["periods"].get("today", {})

    tg_ch = str(soc["tg_members"]) if soc["tg_members"] is not None else "—"
    vk_ch = str(soc["vk_members"]) if soc["vk_members"] is not None else "—"
    max_ch = str(soc["max_members"]) if soc["max_members"] is not None else "—"

    sources_rows = "".join(
        f"<tr><td>{escape(s)}</td><td>{escape(e)}</td><td>{v}</td><td>{u}</td></tr>"
        for s, e, v, u in met["sources"]
    ) or "<tr><td colspan='4'>Нет данных за 30 дней</td></tr>"

    land_rows = "".join(
        f"<tr><td style='word-break:break-all'>{escape(u)}</td><td>{v}</td><td>{usr}</td></tr>"
        for u, v, usr in met["landing_pages"]
    ) or "<tr><td colspan='3'>Нет данных</td></tr>"

    goals_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{gid}</td><td>{reaches}</td><td>{users}</td></tr>"
        for name, gid, reaches, users in met["goals"]
    ) or "<tr><td colspan='4'>Цели в Метрике не найдены или ещё нет достижений</td></tr>"

    ref_rows = "".join(
        f"<tr><td>{escape(str(src))}</td><td>{cnt}</td></tr>"
        for src, cnt in loc["tg_bot"]["referrals"]
    ) or "<tr><td colspan='2'>Нет данных</td></tr>"

    ev_rows = "".join(
        f"<tr><td><code>{escape(name)}</code></td><td>{cnt}</td></tr>"
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

    metrika_err = f"<p class='st-warn'>Ошибка Яндекс.Метрики: {escape(met['error'])}</p>" if not met["ok"] else ""

    content = f"""
    <style>
      .st-wrap{{max-width:1120px;margin:0 auto;padding:36px 20px 80px}}
      .st-head{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;margin-bottom:24px}}
      .st-head h1{{margin:0;font-size:clamp(26px,4vw,36px)}}
      .st-btn{{display:inline-block;padding:10px 16px;border-radius:10px;background:#a7ef46;color:#111;font-weight:700;text-decoration:none}}
      .st-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin-bottom:28px}}
      .st-card{{padding:18px;border:1px solid rgba(255,255,255,.12);border-radius:16px;background:rgba(255,255,255,.03)}}
      .st-card small{{display:block;color:var(--muted,#9aa39d);margin-bottom:6px;font-size:13px}}
      .st-card strong{{font-size:28px;color:#a7ef46;display:block;line-height:1.15}}
      .st-card span{{font-size:13px;color:var(--muted,#9aa39d)}}
      .st-sec{{margin-bottom:32px}}
      .st-sec h2{{font-size:20px;margin:0 0 12px;border-bottom:1px solid rgba(255,255,255,.1);padding-bottom:8px}}
      .st-sec h3{{font-size:16px;margin:18px 0 8px}}
      .st-cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}}
      .st-table{{width:100%;border-collapse:collapse;font-size:14px}}
      .st-table th,.st-table td{{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.08)}}
      .st-table th{{color:var(--muted,#9aa39d);font-weight:600}}
      .st-note{{color:var(--muted,#9aa39d);font-size:14px}}
      .st-warn{{padding:12px 14px;border-radius:10px;background:rgba(255,100,100,.14);border:1px solid rgba(255,100,100,.4)}}
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
          <small>Каналы (подписчики)</small>
          <strong>VK: {vk_ch} · MAX: {max_ch}</strong>
          <span>Telegram: {tg_ch} (через AWG)</span>
        </div>
        <div class="st-card">
          <small>Боты (пользователи)</small>
          <strong>{loc['tg_bot']['users'] + loc['vk_bot']['users'] + loc['max_bot']['users']} всего</strong>
          <span>TG: {loc['tg_bot']['users']} (+{loc['tg_bot']['users_7d']} за 7д) · VK: {loc['vk_bot']['users']} · MAX: {loc['max_bot']['users']}</span>
        </div>
        <div class="st-card">
          <small>Отслеживания и база</small>
          <strong>{loc['tg_bot']['tracked'] + loc['vk_bot']['tracked'] + loc['max_bot']['tracked']} подписок</strong>
          <span>Каталог: {loc['site']['titles']} · Новости: {loc['site']['articles']} · Увед: {loc['tg_bot']['notifications']}</span>
        </div>
      </div>

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
        <h3>Цели сайта (клики в ботов и канал)</h3>
        <table class="st-table">
          <thead><tr><th>Цель</th><th>ID</th><th>Достижений</th><th>Уникальных</th></tr></thead>
          <tbody>{goals_rows}</tbody>
        </table>
      </section>

      <section class="st-sec">
        <h2>Боты: рефералы, события и топ отслеживаний</h2>
        <div class="st-cols">
          <div>
            <h3>Источники в Telegram-боте</h3>
            <table class="st-table">
              <thead><tr><th>Источник</th><th>Пользователей</th></tr></thead>
              <tbody>{ref_rows}</tbody>
            </table>
          </div>
          <div>
            <h3>Воронка событий (analytics_events)</h3>
            <table class="st-table">
              <thead><tr><th>Событие</th><th>Кол-во</th></tr></thead>
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
