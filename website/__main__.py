import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

from aiohttp import web
from dotenv import load_dotenv

from website.content import Store
from website.editor import Editor
from website import views

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
            "channel_url": channel_url,
            "database": os.getenv("SITE_DATABASE_PATH", str(ROOT / "data" / "website.db")),
            "bot_database": str(ROOT / database.removeprefix("sqlite+aiosqlite:///")) if database.startswith("sqlite+aiosqlite:///") else None,
            "api_key": os.getenv("TMDB_API_KEY", ""),
            "api_base": os.getenv("TMDB_BASE_URL", "https://api.themoviedb.org/3").rstrip("/"),
            "sync_seconds": max(60, int(os.getenv("SITE_SYNC_INTERVAL_MINUTES", "60")) * 60),
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
    store.import_channel(config["bot_database"], config["channel_url"])
    app[STORE], app[CONFIG] = store, config
    app.cleanup_ctx.append(background)

    async def home(request):
        return web.Response(text=views.home(store, config), content_type="text/html")

    async def listing(request):
        category = {"/movies": "movies", "/series": "series"}.get(request.path, request.query.get("category"))
        if category not in views.CATEGORIES:
            category = None
        try:
            page = max(1, min(10000, int(request.query.get("page", "1"))))
        except ValueError:
            page = 1
        return web.Response(text=views.listing(store, config, category, request.query.get("q", "")[:100], page), content_type="text/html")

    async def article(request):
        row = store.article(request.match_info["slug"])
        if not row:
            raise web.HTTPNotFound()
        return web.Response(text=views.article_page(store, config, row), content_type="text/html")

    async def calendar(request):
        media = request.query.get("type")
        media = media if media in ("tv", "movie") else None
        return web.Response(text=views.calendar(store, config, media, request.query.get("period", "all")), content_type="text/html")

    async def about(request):
        return web.Response(text=views.about(config), content_type="text/html")

    async def robots(request):
        text = "User-agent: *\n" + ("Allow: /\nDisallow: /health\n" if config["public"] else "Disallow: /\n")
        if config["public"]:
            text += "Clean-param: q /news&/movies&/series\n"
            text += "Sitemap: " + config["base_url"] + "/sitemap.xml\n"
        return web.Response(text=text, content_type="text/plain")

    async def sitemap(request):
        pages = [(p, None, "1.0" if p == "/" else "0.9" if p == "/calendar" else "0.8", "daily")
                 for p in ("/", "/news", "/movies", "/series", "/calendar", "/about")]
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
        for a in store.articles(limit=30):
            url = xml_escape(config["base_url"] + "/news/" + a["slug"])
            items.append(f'<item><title>{xml_escape(a["title"])}</title><link>{url}</link><guid isPermaLink="true">{url}</guid><description>{xml_escape(a["summary"])}</description><pubDate>{format_datetime(datetime.fromisoformat(a["published"]))}</pubDate></item>')
        return web.Response(text='<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>КиноЖдун</title><link>' + xml_escape(config["base_url"]) + '</link><description>Новости кино и сериалов</description><language>ru</language>' + ''.join(items) + '</channel></rss>', content_type="application/rss+xml")

    async def health(request):
        return web.json_response({"status": "ok", "last_sync": store.state("last_sync"), "sync_error": store.state("sync_error"), "titles": len(store.titles()), "articles": store.db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]}, headers={"X-Robots-Tag": "noindex"})

    for path, handler in (("/", home), ("/news", listing), ("/movies", listing), ("/series", listing), ("/news/{slug}", article), ("/calendar", calendar), ("/about", about), ("/robots.txt", robots), ("/sitemap.xml", sitemap), ("/feed.xml", feed), ("/health", health)):
        app.router.add_get(path, handler)
    app.router.add_static("/static/", ROOT / "website" / "static", show_index=False)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = configuration()
    web.run_app(create_app(cfg), host=cfg["host"], port=cfg["port"], access_log=None)
