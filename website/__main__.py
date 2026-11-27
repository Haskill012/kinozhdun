import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

from website.content import Store, today
from website.editor import Editor
from website.search import ProjectSearch, result
from website import views
from website.audience import audience_articles

ROOT = Path(__file__).resolve().parent.parent


def configuration():
    load_dotenv(ROOT / ".env")
    port = int(os.getenv("SITE_PORT", "8099"))
    base = os.getenv("SITE_BASE_URL", f"http://127.0.0.1:{port}").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("SITE_BASE_URL должен быть абсолютным http(s) адресом без query/fragment")
    channel = os.getenv("TELEGRAM_CHANNEL_ID", "").lstrip("@")
    channel_url = os.getenv("SITE_CHANNEL_URL", "") or ("https://t.me/" + channel if channel and not channel.startswith("-100") else "https://t.me/kinojdun_channel")
    database = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/kinozhdun.db")
    return {"port": port, "host": os.getenv("SITE_HOST", "127.0.0.1"), "base_url": base,
            "public": os.getenv("SITE_PUBLIC", "false").lower() == "true",
            "bot_url": "https://t.me/" + os.getenv("BOT_USERNAME", "kinojdun_bot").lstrip("@"),
            "max_bot_url": os.getenv("MAX_BOT_URL", "").strip() or ("https://max.ru/" + os.getenv("MAX_BOT_USERNAME", "id5001170357_1_bot").lstrip("@")),
            "vk_bot_url": os.getenv("VK_BOT_URL", "https://vk.me/club242087163").strip(),
            "channel_url": channel_url,
            "database": os.getenv("SITE_DATABASE_PATH", str(ROOT / "data" / "website.db")),
            "bot_database": str(ROOT / database.removeprefix("sqlite+aiosqlite:///")) if database.startswith("sqlite+aiosqlite:///") else None,
            "api_key": os.getenv("TMDB_API_KEY", ""),
            "api_base": os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3").rstrip("/"),
            "sync_seconds": max(60, int(os.getenv("SITE_SYNC_INTERVAL_MINUTES", "60")) * 60),
            "catalog_size": 50,
            "daily_cards": max(1, min(100, int(os.getenv("SITE_DAILY_CARDS", "30")))),
            "min_rating": float(os.getenv("SITE_MIN_RATING", "6.0")),
            "min_votes": int(os.getenv("SITE_MIN_VOTES", "50")),
            "min_popularity": float(os.getenv("SITE_MIN_POPULARITY", "5")),
            "asian_min_votes": max(50, int(os.getenv("SITE_ASIAN_MIN_VOTES", "1000"))),
            "asian_min_popularity": max(0, float(os.getenv("SITE_ASIAN_MIN_POPULARITY", "20"))),
            "audience_allow_keys": tuple(k.strip() for k in os.getenv("SITE_AUDIENCE_ALLOW_KEYS", "").split(',') if k.strip()),
            "batch_size": min(20, max(1, int(os.getenv("SITE_BATCH_SIZE", "12")))),
            "yandex_verification": os.getenv("SITE_YANDEX_VERIFICATION", ""),
            "google_verification": os.getenv("SITE_GOOGLE_VERIFICATION", ""),
            "yandex_metrika_id": os.getenv("SITE_YANDEX_METRIKA_ID", "")}


STORE = web.AppKey("store", Store)
CONFIG = web.AppKey("config", dict)


async def background(app):
    editor = Editor(app[STORE], app[CONFIG])
    task = asyncio.create_task(editor.run())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app[STORE].db.close()


@web.middleware
async def errors(request, handler):
    config = request.app[CONFIG]
    canonical_host = urlparse(config["base_url"]).hostname
    alias_host = "www." + canonical_host if canonical_host else None
    # Also enforce the canonical host behind a proxy that has not reloaded yet.
    if config["public"] and alias_host and request.url.host.lower() == alias_host.lower():
        raise web.HTTPMovedPermanently(location=config["base_url"] + request.raw_path)
    try:
        response = await handler(request)
    except web.HTTPNotFound:
        config = request.app[CONFIG]
        content = '<div class="page-shell"><div class="empty"><span>404</span><h1>Эта сцена не найдена.</h1><p>Похоже, у этой страницы другой сценарий.</p><a class="button" href="/">На главную ↗</a></div></div>'
        response = web.Response(text=views.layout(config, "Страница не найдена", "Вернитесь к новостям кино и сериалов.", content, noindex=True), content_type="text/html", status=404)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def create_app(config=None):
    config = config or configuration()
    app = web.Application(middlewares=[errors])
    store = Store(config["database"])
    store.seed_guides(config["bot_url"])
    store.seed_catalog(config["bot_url"])
    if config.get("catalog_size"):
        store.seed_live_catalog()
        store.open_initial_catalog()
        store.release_catalog(config.get("daily_cards", 3))
    store.import_channel(config["bot_database"], config["channel_url"])
    store.restore_news_cards()
    app[STORE], app[CONFIG] = store, config
    project_search = ProjectSearch(store, config)
    app.cleanup_ctx.append(background)

    async def home(request):
        return web.Response(text=views.home(store, config), content_type="text/html")

    async def subscription_guide(request):
        from website.catalog_views import subscription_demo_available, subscription_help_page
        if not subscription_demo_available():
            raise web.HTTPNotFound()
        key = request.query.get('project', '')
        item = store.catalog_item(key) if key else None
        if key and not item:
            raise web.HTTPNotFound()
        return web.Response(text=subscription_help_page(config, item), content_type='text/html')

    app.router.add_get('/how-to-subscribe', subscription_guide)

    async def listing(request):
        category = {"/movies": "movies", "/series": "series"}.get(request.path, request.query.get("category"))
        if category not in views.CATEGORIES:
            category = None
        try:
            page = max(1, min(10000, int(request.query.get("page", "1"))))
        except ValueError:
            page = 1
        if request.path == "/catalog" or (config.get("catalog_size") and category in ("movies", "series")):
            from website.catalog_views import catalog_page
            extra = await project_search.projects(request.query.get("q", "")) if request.query.get("q") else []
            return web.Response(text=catalog_page(store, config, request.path, request.query, extra), content_type="text/html")
        return web.Response(text=views.listing(store, config, category, request.query.get("q", "")[:100], page), content_type="text/html")

    async def article(request):
        row = store.article(request.match_info["slug"])
        if not row:
            raise web.HTTPNotFound()
        return web.Response(text=views.article_page(store, config, row), content_type="text/html")

    async def title_page(request):
        item = store.catalog_item(request.match_info["media"] + ":" + request.match_info["id"])
        if not item and config["api_key"]:
            try:
                item = await Editor(store, config).open_title(request.match_info["media"], int(request.match_info["id"]))
            except RuntimeError as exc:
                if str(exc) == "TMDB вернул HTTP 404":
                    raise web.HTTPNotFound()
                raise web.HTTPServiceUnavailable(text="Не удалось загрузить карточку. Попробуйте открыть её немного позже.")
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise web.HTTPServiceUnavailable(text="Не удалось загрузить карточку. Попробуйте открыть её немного позже.")
        if not item:
            raise web.HTTPNotFound()
        try:
            news_page = int(request.query.get("news_page", "1"))
        except ValueError:
            news_page = 1
        return web.Response(text=views.title_page(store, config, item, news_page), content_type="text/html")

    async def calendar(request):
        media = request.query.get("type")
        media = media if media in ("tv", "movie") else None
        return web.Response(text=views.calendar(store, config, media, request.query.get("period", "all")), content_type="text/html")

    async def about(request):
        return web.Response(text=views.about(config), content_type="text/html")

    async def bots(request):
        from website.bots_page import bots_page

        return web.Response(
            text=bots_page(config, request.query.get("from", "")),
            content_type="text/html",
        )

    async def stats_page(request):
        from website.stats import stats_handler
        return await stats_handler(request, config)

    indexnow_key = os.getenv("SITE_INDEXNOW_KEY", "kinojdun2026indexnow8842").strip()

    async def indexnow_txt(request):
        return web.Response(text=indexnow_key, content_type="text/plain")

    if indexnow_key:
        app.router.add_get(f"/{indexnow_key}.txt", indexnow_txt)

    async def help_page(request):
        return web.Response(text=views.help_page(config), content_type="text/html")

    async def privacy(request):
        return web.Response(text=views.privacy(config), content_type="text/html")

    async def robots(request):
        text = "User-agent: *\n" + ("Allow: /\nDisallow: /health\n" if config["public"] else "Disallow: /\n")
        if config["public"]:
            text += "Sitemap: " + config["base_url"] + "/sitemap.xml\n"
        return web.Response(text=text, content_type="text/plain")

    async def sitemap(request):
        pages = [(p, None, "1.0" if p == "/" else "0.9" if p == "/calendar" else "0.8", "daily")
                 for p in ("/", "/catalog", "/news", "/movies", "/series", "/calendar", "/bots", "/about", "/help", "/privacy")]
        pages.extend((views.title_path(t), None, "0.8", "daily") for t in store.catalog())
        pages.extend(("/news/" + a["slug"], a["updated"], "0.7", "weekly") for a in store.articles(limit=50000))
        body = ''.join(
            '<url><loc>' + xml_escape(config["base_url"] + path) + '</loc>'
            + ('<lastmod>' + xml_escape(updated) + '</lastmod>' if updated else '')
            + f'<changefreq>{freq}</changefreq><priority>{pri}</priority></url>'
            for path, updated, pri, freq in pages
        )
        return web.Response(text='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + '</urlset>', content_type="application/xml")

    async def feed(request):
        from email.utils import format_datetime
        from datetime import datetime
        items = []
        for a in audience_articles(store, config, limit=30):
            url = xml_escape(config["base_url"] + "/news/" + a["slug"])
            items.append(f'<item><title>{xml_escape(a["title"])}</title><link>{url}</link><guid isPermaLink="true">{url}</guid><description>{xml_escape(a["summary"])}</description><pubDate>{format_datetime(datetime.fromisoformat(a["published"]))}</pubDate></item>')
        return web.Response(text='<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>КиноЖдун</title><link>' + xml_escape(config["base_url"]) + '</link><description>Новости кино и сериалов</description><language>ru</language>' + ''.join(items) + '</channel></rss>', content_type="application/rss+xml")

    async def dzen_feed(request):
        from email.utils import format_datetime
        from datetime import datetime
        items = []
        bot_user = config.get("bot_username", "kinojdun_bot")
        for a in audience_articles(store, config, limit=50):
            url = xml_escape(config["base_url"] + "/news/" + a["slug"])
            try:
                pub_date = format_datetime(datetime.fromisoformat(a["published"]))
            except Exception:
                pub_date = format_datetime(datetime.utcnow())
            title = xml_escape(a["title"])
            summary = xml_escape(a.get("summary") or "")
            body = a.get("body") or a.get("summary") or ""
            poster = a.get("image") or a.get("poster")
            image_tag = ""
            if poster:
                img_url = poster if poster.startswith("http") else (config["base_url"].rstrip("/") + "/" + poster.lstrip("/"))
                image_tag = f'<enclosure url="{xml_escape(img_url)}" type="image/jpeg"/>'
            encoded_html = (
                f'<p>{body}</p>'
                f'<p>👉 <a href="{url}">Карточка проекта на КиноЖдуне</a></p>'
                f'<p>🍿 <a href="https://t.me/{bot_user}">Добавить в отслеживание в Telegram-боте</a></p>'
            )
            items.append(
                f'<item><title>{title}</title><link>{url}</link><guid isPermaLink="true">{url}</guid>'
                f'<pubDate>{pub_date}</pubDate><author>КиноЖдун</author><category>Кино</category>'
                f'{image_tag}<description>{summary}</description>'
                f'<content:encoded><![CDATA[{encoded_html}]]></content:encoded></item>'
            )
        rss_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:media="http://search.yahoo.com/mrss/" '
            'xmlns:atom="http://www.w3.org/2005/Atom">\n'
            '<channel><title>КиноЖдун</title>'
            f'<link>{xml_escape(config["base_url"])}</link>'
            '<description>Официальный канал КиноЖдуна в Дзене: график премьер, трейлеры, даты выхода фильмов и новых сезонов сериалов.</description>'
            '<language>ru</language>'
            + ''.join(items)
            + '</channel></rss>'
        )
        return web.Response(text=rss_xml, content_type="application/rss+xml", charset="utf-8")

    async def health(request):
        return web.json_response({
            "status": "ok",
            "version": "1.4.0",
            "cards_published": len(store.catalog()),
            "cards_queued": len(store.catalog(False)) - len(store.catalog()),
            "daily_cards_limit": config.get("daily_cards", 30),
            "cards_added_today": int(store.state("cards_published:" + today().isoformat()) or 0),
            "catalog_selected": store.state("catalog_selected"),
            "last_sync": store.state("last_sync"),
            "sync_error": store.state("sync_error"),
            "titles": len(store.titles()),
            "articles": store.db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        }, headers={"X-Robots-Tag": "noindex"})

    async def search(request):
        found = await project_search.projects(request.query.get("q", ""))
        return web.json_response({"results": [result(item) for item in found]},
                                 headers={"X-Robots-Tag": "noindex", "Cache-Control": "no-store"})

    app.router.add_get("/api/search", search)
    from website.vk_upload_check import upload_check_handler
    app.router.add_post('/api/vk/poster-check', upload_check_handler(ROOT / 'website' / 'catalog_seed.json'))

    for path, handler in (("/", home), ("/news", listing), ("/catalog", listing), ("/movies", listing), ("/series", listing), ("/news/{slug}", article), (r"/title/{media:movie|tv}/{id:\d+}", title_page), ("/calendar", calendar), ("/bots", bots), ("/stats", stats_page), ("/about", about), ("/help", help_page), ("/privacy", privacy), ("/robots.txt", robots), ("/sitemap.xml", sitemap), ("/feed.xml", feed), ("/dzen/rss.xml", dzen_feed), ("/dzen.xml", dzen_feed), ("/health", health)):

        app.router.add_get(path, handler)
    app.router.add_static("/static/", ROOT / "website" / "static", show_index=False)
    from website.social_images import image_handler
    app.router.add_get('/social-image/{name}', image_handler(Path(config['database']).parent / 'social_images'))

    reels_dir = Path(config['database']).parent / 'reels_tmp'

    async def reels_media(request):
        import re as _re
        name = request.match_info.get("name", "")
        if not _re.fullmatch(r"[a-f0-9]{16,32}_\d+\.mp4", name):
            raise web.HTTPNotFound()
        target = reels_dir / name
        if not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

    app.router.add_get('/media/reels/{name}', reels_media)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = configuration()
    web.run_app(create_app(cfg), host=cfg["host"], port=cfg["port"], access_log=None)
