"""HTML rendering: all indexable content is served without JavaScript."""
import html
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import json
import re
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlencode

from website.editor import date_ru, today
from website.artwork import allowed_asset
from website.audience import audience_items, audience_articles

ASSET_VERSION = hashlib.sha256((Path(__file__).parent / "static/site.css").read_bytes() + (Path(__file__).parent / "static/site.js").read_bytes()).hexdigest()[:12]

CATEGORIES = {"news": "Новости", "movies": "Фильмы", "series": "Сериалы", "guides": "Гид КиноЖдуна"}


def esc(value):
    return html.escape(str(value or ""), quote=True)


ALLOWED_HTML_TAGS = {"a", "b", "strong", "i", "em", "code", "br"}


class SafeHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.output = []
        self.open_tags = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ALLOWED_HTML_TAGS:
            if t == "a":
                href = ""
                for k, v in attrs:
                    if k.lower() == "href":
                        href = v.strip()
                        break
                if href.startswith(("/", "https://", "http://", "tg://")):
                    safe_href = html.escape(href, quote=True)
                    rel = ' rel="noopener"' if href.startswith("http") else ""
                    self.output.append(f'<a href="{safe_href}"{rel}>')
                    self.open_tags.append("a")
            elif t == "br":
                self.output.append("<br>")
            else:
                self.output.append(f"<{t}>")
                self.open_tags.append(t)

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self.open_tags:
            self.output.append(f"</{t}>")
            self.open_tags.remove(t)

    def handle_data(self, data):
        self.output.append(html.escape(data))

    def get_html(self):
        return "".join(self.output)


def sanitize_paragraph_html(p: str) -> str:
    if not p:
        return ""
    p_clean = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', str(p), flags=re.IGNORECASE | re.DOTALL)
    parser = SafeHTMLParser()
    try:
        parser.feed(p_clean)
        cleaned = parser.get_html()
    except Exception:
        cleaned = esc(p)
    return cleaned.replace("\n", "<br>")


def image(url, title, cls="", eager=False):
    if allowed_asset(url) and (url.startswith("https://image.tmdb.org/") or url == "/static/mascot.jpg"):
        return f'<img class="{cls}" src="{esc(url)}" alt="{esc(title)}" loading="{"eager" if eager else "lazy"}" decoding="async">'
    return f'<div class="{cls} art-placeholder"><span>КЖ</span><small>КИНО — ЭТО ОЖИДАНИЕ</small></div>'


def stamp(value):
    if not value:
        return []
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone(timedelta(hours=3))).strftime('%d-%m-%Y').split('-')



def search_form(prefix="site"):
    return '<form class="site-search" action="/catalog" method="get" role="search" aria-label="Поиск фильмов и сериалов"><div class="site-search-field"><span aria-hidden="true">⌕</span><input id="{prefix}-search-input" name="q" type="search" placeholder="Найти фильм или сериал" aria-label="Название фильма или сериала" autocomplete="off" maxlength="100" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="{prefix}-search-results"><button class="site-search-clear" type="button" aria-label="Очистить поиск" hidden>×</button></div><div class="site-search-dropdown" hidden><p class="site-search-status" role="status" aria-live="polite"></p><div id="{prefix}-search-results" role="listbox" aria-label="Найденные фильмы и сериалы"></div><a class="site-search-all" href="/catalog">Все результаты →</a></div><noscript><button type="submit">Найти</button></noscript></form>'.replace("{prefix}", prefix)


def layout(config, title, description, content, path="/", active="", schema=None, noindex=False, og_image=None):
    base = config["base_url"]
    structured = schema or {"@context": "https://schema.org", "@type": "WebSite", "name": "КиноЖдун", "url": base, "inLanguage": "ru"}
    jsonld = json.dumps(structured, ensure_ascii=False).replace("<", "\\u003c")
    nav = "".join(f'<a class="{"active" if active == key else ""}" href="{url}">{label}</a>' for key, url, label in (
        ("home", "/", "Главная"), ("catalog", "/catalog", "Каталог"), ("news", "/news", "Новости"), ("movies", "/movies", "Фильмы"), ("series", "/series", "Сериалы"), ("calendar", "/calendar", "Премьеры"), ("help", "/help", "Помощь")))
    robots = "noindex, follow" if noindex or not config["public"] else "index, follow, max-image-preview:large"
    verification = ""
    if config.get("yandex_verification"):
        verification += f'<meta name="yandex-verification" content="{esc(config["yandex_verification"])}">\n    '
    if config.get("google_verification"):
        verification += f'<meta name="google-site-verification" content="{esc(config["google_verification"])}">\n    '
    metrika = ""
    if config.get("yandex_metrika_id"):
        mid = esc(config["yandex_metrika_id"])
        metrika = f'''<script type="text/javascript">(function(m,e,t,r,i,k,a){{m[i]=m[i]||function(){{(m[i].a=m[i].a||[]).push(arguments)}};m[i].l=1*new Date();for(var j=0;j<document.scripts.length;j++){{if(document.scripts[j].src===r){{return;}}}}k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)}})(window,document,"script","https://mc.yandex.ru/metrika/tag.js?id={mid}","ym");ym({mid},"init",{{ssr:true,webvisor:true,clickmap:true,accurateTrackBounce:true,trackLinks:true}});</script><noscript><div><img src="https://mc.yandex.ru/watch/{mid}" style="position:absolute;left:-9999px;" alt="" /></div></noscript>'''
    is_article = False
    if schema:
        if schema.get("@type") in ("NewsArticle", "Article"):
            is_article = True
        elif "@graph" in schema:
            is_article = any(item.get("@type") in ("NewsArticle", "Article") for item in schema.get("@graph", []))
    og_img = esc(og_image if allowed_asset(og_image) else (base + "/static/logo_mascot.jpg"))
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    {verification}<title>{esc(title)} — КиноЖдун</title><meta name="description" content="{esc(description)}"><meta name="robots" content="{robots}">
    <link rel="canonical" href="{esc(base + path)}"><link rel="icon" href="/static/logo_mascot.jpg" type="image/jpeg"><link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/static/logo_mascot.jpg">
    <meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:site_name" content="КиноЖдун"><meta property="og:locale" content="ru_RU"><meta property="og:type" content="{"article" if is_article else 'website'}"><meta property="og:url" content="{esc(base + path)}">
    <meta property="og:image" content="{og_img}">
    <meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(title)}"><meta name="twitter:description" content="{esc(description)}"><meta name="twitter:image" content="{og_img}">
    <meta name="theme-color" content="#111312"><link rel="alternate" type="application/rss+xml" title="КиноЖдун — новости" href="/feed.xml">
    <link rel="stylesheet" href="/static/site.css?v={ASSET_VERSION}"><script type="application/ld+json">{jsonld}</script><script src="/static/site.js?v={ASSET_VERSION}" defer></script>{metrika}</head>
    <body data-metrika-id="{esc(config.get('yandex_metrika_id'))}" data-bot-url="{esc(config['bot_url'])}" data-channel-url="{esc(config['channel_url'])}"><a class="skip" href="#content">Перейти к содержимому</a><header><div class="header-inner"><a class="brand" href="/" aria-label="КиноЖдун — главная"><img class="brand-logo" src="/static/logo_mascot.jpg" alt="КиноЖдун" width="48" height="48"><span>кино<span class="brand-light">ждун</span><small>ХОРОШЕЕ КИНО СТОИТ ЖДАТЬ</small></span></a>
    {search_form()}
    <nav aria-label="Основная навигация">{nav}</nav><a class="button small" href="{esc(config['bot_url'])}" target="_blank" rel="noopener">↗ Открыть бота</a></div></header>
    <main id="content">{content}</main>
    <footer><div class="footer-top"><a class="brand footer-brand" href="/"><img class="brand-logo footer-logo" src="/static/logo_mascot.jpg" alt="КиноЖдун" width="38" height="38"><span>кино<span class="brand-light">ждун</span><span class="lime">✳</span></span></a><p>Ваш следующий любимый фильм<br>ещё впереди.</p><div><a href="{esc(config['channel_url'])}" target="_blank" rel="noopener">Telegram-канал ↗</a><a href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Бот с напоминаниями ↗</a><a href="/about">О проекте</a></div></div>
    <div class="footer-bottom"><span>© {today().year} КиноЖдун</span><span class="footer-service-links"><a href="/help">Помощь</a><a href="/privacy">Конфиденциальность</a></span></div></footer></body></html>'''


def card(article, featured=False):
    category = CATEGORIES.get(article["category"], "Новости")
    return f'''<a class="news-card {'featured-card' if featured else ''}" href="/news/{esc(article['slug'])}">
      <div class="card-image">{image(article.get('image'), article['title'])}<span class="card-tag">{category}</span><span class="card-arrow">↗</span></div>
      <div class="card-copy"><div class="meta"><time datetime="{esc(article['published'])}">{'.'.join(stamp(article['published']))}</time><span>•</span><span>2 мин чтения</span></div>
      <h3>{esc(article['title'])}</h3><p>{esc(article['summary'])}</p></div></a>'''


def title_path(item):
    return f"/title/{item['media_type']}/{item['id']}"


def title_card(item):
    from website.catalog_views import poster_card
    return poster_card(item)


def trailer_player(key, language=None, season=None):
    if not key or not re.fullmatch(r"[\w-]{6,32}", key, flags=re.ASCII):
        return ""
    label = "На русском языке" if language == "ru" else "На английском языке" if language == "en" else "Оригинальный трейлер"
    if isinstance(season, int) and season > 0:
        label = f"Трейлер {season}-го сезона · " + label
    return f'''<section class="trailer-section"><h2>Смотреть трейлер</h2><p>{label}</p><div class="trailer-frame"><iframe src="https://www.youtube-nocookie.com/embed/{esc(key)}" title="Трейлер" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div><p><a href="https://www.youtube.com/watch?v={esc(key)}" target="_blank" rel="noopener">Открыть трейлер на YouTube ↗</a></p></section>'''


def title_page(store, config, item, news_page=1):
    from website.catalog_views import project_page
    return project_page(store, config, item, news_page)


def bot_banner(config):
    return f'''<section class="bot-banner"><div><span class="eyebrow">ВАШ ЛИЧНЫЙ ТРЕКЕР ПРЕМЬЕР</span><h2>Ждать — ваше дело.<br>Напомнить — наше<span class="lime">.</span></h2><p>Добавьте фильм или сериал в Telegram-бота.<br>КиноЖдун сообщит, когда появится дата выхода.</p><a class="button" href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Начать ждать в боте <span>↗</span></a><small>Бесплатно. Без установки. В вашем Telegram.</small></div><div class="chat-scene" aria-label="Пример работы бота"><div class="chat-top"><img class="chat-avatar" src="/static/logo_mascot.jpg" alt="КиноЖдун"><div>КиноЖдун<small>бот · ваш список ожидания</small></div><span>•••</span></div><div class="bubble own">Хочу следить за новым сезоном</div><div class="bubble"><strong>🍿 Уже ждём вместе!</strong><p>Добавьте любимый сериал в список. Я проверю дату и пришлю уведомление, когда она появится.</p><span class="chat-action">✓ В списке ожидания</span></div><div class="chat-input">Написать сообщение… <span>➤</span></div></div></section>'''


def title_link(item, config):
    return config["bot_url"] + "?start=c_" + item["media_type"] + "_" + str(item["id"])


def premiere_rows(items, config, limit=5):
    from website.home_state import event_state, days_text, watch_label
    states = [(i, event_state(i)) for i in audience_items(items, config)]
    states = sorted([(i, state) for i, state in states if state['date'] and state['date'] >= today()], key=lambda pair: pair[1]['date'])
    if not states:
        return '<div class="empty compact"><span>◷</span><h3>Новые даты — скоро здесь</h3><p>Показываем только даты из источника. Следите за любимыми проектами в боте.</p></div>'
    rows = []
    for item, state in states[:limit]:
        d = state['date']
        diff_days = (d - today()).days
        if diff_days == 0:
            badge = '<span class="date-badge date-today">Сегодня!</span>'
        elif diff_days == 1:
            badge = '<span class="date-badge date-tomorrow">Завтра</span>'
        else:
            badge = f'<span class="date-badge">Через {days_text(diff_days)}</span>'
        month = ["ЯНВ", "ФЕВ", "МАР", "АПР", "МАЙ", "ИЮН", "ИЮЛ", "АВГ", "СЕН", "ОКТ", "НОЯ", "ДЕК"][d.month - 1]
        label = state['kind']
        if ' · ' in state['detail']:
            label += ' · ' + state['detail'].split(' · ', 1)[1]
        rows.append(f'''<div class="premiere-row"><div class="premiere-date"><b>{d.day:02}</b><span>{month} {d.year}</span>{badge}</div><a class="premiere-poster" href="{title_path(item)}" aria-label="Открыть карточку: {esc(item['title'])}">{image(item.get('poster'), item['title'])}</a><a class="premiere-title" href="{title_path(item)}"><strong>{esc(item['title'])}</strong><span>{esc(label)}</span></a><a class="reminder" href="{esc(title_link(item, config))}" target="_blank" rel="noopener" aria-label="{watch_label(item)}: {esc(item['title'])}">{watch_label(item)}</a></div>''')
    return "".join(rows)


def home(store, config):
    from website.catalog_views import streaming_home
    return streaming_home(store, config)


def listing(store, config, category, query, page):
    size = 12
    articles = audience_articles(store, config, category=category, query=query, limit=size + 1, offset=(page - 1) * size)
    catalog = [t for t in store.catalog() if t["media_type"] == ("movie" if category == "movies" else "tv") and query.casefold() in t["title"].casefold()] if category in ("movies", "series") else []
    if catalog or (config.get("catalog_size") and category in ("movies", "series")):
        entries = catalog[(page-1)*size:page*size+1]
        cards = "".join(title_card(t) for t in entries[:size])
    else:
        entries = articles
        cards = "".join(card(a) for a in articles[:size])
    heading = {"movies": "Кино, которое ждём", "series": "Ещё одна серия", "guides": "Гид КиноЖдуна"}.get(category, "Всё самое интересное")
    path = "/movies" if category == "movies" else "/series" if category == "series" else "/news"
    form = f'''<form class="search" action="{path}" method="get"><label for="search">Поиск по материалам</label><div><input id="search" name="q" placeholder="Фильм, сериал или новость…" value="{esc(query)}" maxlength="100">{f'<input type="hidden" name="category" value="{esc(category)}">' if category == 'guides' else ''}<button type="submit" aria-label="Найти">⌕ Найти</button></div></form>'''
    empty = '<div class="empty"><span>⌕</span><h2>Пока ничего не нашлось</h2><p>Попробуйте другое название или вернитесь ко всем материалам.</p><a class="button outline" href="/news">Все материалы ↗</a></div>'
    def page_url(number):
        return path + "?" + urlencode({k: v for k, v in {"page": number, "q": query, "category": category if category == "guides" else ""}.items() if v})
    pager = '<div class="pagination">' + (f'<a href="{esc(page_url(page-1))}">← Назад</a>' if page > 1 else '') + f'<span>Страница {page}</span>' + (f'<a href="{esc(page_url(page+1))}">Дальше →</a>' if len(entries) > size else '') + '</div>'
    tabs = ''.join(f'<a class="{"selected" if category == k else ""}" href="{u}">{label}</a>' for k,u,label in ((None,"/news","Все материалы"),("movies","/movies","Фильмы"),("series","/series","Сериалы"),("guides","/news?category=guides","Гид")))
    content = f'<div class="page-shell"><section class="page-intro"><span class="eyebrow muted">ЛЕНТА КИНОЖДУНА</span><h1>{heading}<span class="lime">.</span></h1><p>Даты выхода, изменения в проектах и полезные материалы для тех, кто любит кино.</p>{form}</section><div class="tabs">{tabs}</div><div class="news-grid">{cards}</div>{empty if not entries else pager}{bot_banner(config)}</div>'
    canonical = path + ("?category=guides" if category == "guides" else "")
    if page > 1:
        canonical += ("&" if "?" in canonical else "?") + "page=" + str(page)
    return layout(config, heading, "Новости, даты выхода фильмов и сериалов, новые сезоны и трейлеры с источниками.", content, canonical, category or "news", noindex=bool(query))


def article_page(store, config, article):
    path = "/news/" + article["slug"]
    category = CATEGORIES.get(article["category"], "Новости")
    trailer_key = article["fingerprint"].split(":trailer:")[-1] if ":trailer:" in article["fingerprint"] else None
    body_paragraphs = json.loads(article["body"])
    rendered = []
    for i, p in enumerate(body_paragraphs):
        p_clean = re.sub(r"<[^>]*>", "", p).strip()
        if i == 0 and (p_clean == article["summary"].strip() or (len(p_clean) < 60 and any(h in p_clean for h in ("Что выходит сегодня", "Сегодня на экране", "Что посмотреть", "Главные премьеры")))):
            continue
        rendered.append(f'<p>{sanitize_paragraph_html(p)}</p>')
    body = "".join(rendered)
    item = store.catalog_item(f"{article.get('media_type')}:{article.get('tmdb_id')}")
    if trailer_key:
        body += trailer_player(trailer_key, (item or {}).get("trailer_languages", {}).get(trailer_key))
    if item:
        body += f'<p><a href="{title_path(item)}">Карточка «{esc(item["title"])}» ↗</a></p>'
    bot_url = (config["bot_url"] + f"?start=c_{article['media_type']}_{article['tmdb_id']}" if article.get("media_type") in ("tv", "movie") and article.get("tmdb_id") else config["bot_url"])
    related = [a for a in audience_articles(store, config, limit=7) if a["slug"] != article["slug"]][:3]

    cat_url = config["base_url"] + ("/movies" if article["category"] == "movies" else "/series" if article["category"] == "series" else "/news")
    article_obj = {
        "@type": "NewsArticle" if article["category"] != "guides" else "Article",
        "headline": article["title"],
        "description": article["summary"],
        "datePublished": article["published"],
        "dateModified": article["updated"],
        "mainEntityOfPage": config["base_url"] + path,
        "inLanguage": "ru",
        "author": {"@type": "Organization", "name": "КиноЖдун", "url": config["base_url"] + "/about"},
        "publisher": {"@type": "Organization", "name": "КиноЖдун", "url": config["base_url"]}
    }
    if article.get("image"):
        article_obj["image"] = [article["image"]]

    breadcrumbs = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Главная", "item": config["base_url"] + "/"},
            {"@type": "ListItem", "position": 2, "name": category, "item": cat_url},
            {"@type": "ListItem", "position": 3, "name": article["title"], "item": config["base_url"] + path}
        ]
    }
    schema = {"@context": "https://schema.org", "@graph": [article_obj, breadcrumbs]}

    release_badge = ""
    release_label = "Выход серии" if article.get("media_type") == "tv" and re.search(r"Речь о \d+-м эпизоде|\d+-я серия", article.get("summary", "") + article.get("title", "")) else "Премьера"
    if article.get("release_date"):
        try:
            rd = date.fromisoformat(article["release_date"])
            diff = (rd - today()).days
            if diff > 0:
                release_badge = f'<div class="article-countdown">📅 {release_label}: <b>{date_ru(article["release_date"])}</b> (через {diff} дн.)</div>'
            elif diff == 0:
                release_badge = f'<div class="article-countdown">🎉 {release_label} <b>сегодня</b> ({date_ru(article["release_date"])})!</div>'
        except (ValueError, TypeError):
            pass

    from shared.viewing import viewing_state
    project = store.catalog_item(f"{article.get('media_type')}:{article.get('tmdb_id')}", False)
    action = viewing_state(project, today()) if project else None
    cta_heading = action['status'] if action else 'Сохраните кино на потом'
    cta_text = action['note'] if action else 'Выбирайте фильмы и сериалы и сохраняйте свой список в Telegram.'
    cta_button = action['label'] if action else 'Открыть бота'
    content = f'''<div class="page-shell"><div class="breadcrumbs"><a href="/">Главная</a> / <a href="/news">Материалы</a> / {category}</div><article class="article"><span class="eyebrow lime">{category}</span><h1>{esc(article['title'])}</h1><div class="meta"><span>Редакция КиноЖдуна</span><span>•</span><time datetime="{esc(article['published'])}">{'.'.join(stamp(article['published']))}</time></div>{release_badge}<p class="article-lead">{esc(article['summary'])}</p>{image(article.get('image'), article['title'], 'article-cover', eager=True)}<div class="article-body">{body}<div class="source"><strong>Подробнее о проекте</strong><a href="{esc(article['source_url'])}" target="_blank" rel="noopener noreferrer">Открыть источник ↗</a><small>Сведения могут обновляться. Подробнее — <a href="/about">о нашей редакции</a>.</small></div><div class="article-cta"><h2>{cta_heading}</h2><p>{cta_text}</p><a class="button" href="{esc(bot_url)}" target="_blank" rel="noopener">{cta_button}</a></div></div></article><section class="news-section"><div class="section-heading"><h2>Ещё немного кино<span class="lime">.</span></h2><a href="/news" class="text-link">Все материалы ↗</a></div><div class="news-grid">{''.join(card(a) for a in related)}</div></section></div>'''
    return layout(config, article["title"], article["summary"][:180], content, path, "news", schema=schema, og_image=article.get("image"))


def calendar(store, config, media=None, period="all"):
    items = [t for t in (store.catalog() if config.get("catalog_size") else store.titles()) if t.get("release_date") and t["release_date"] >= today().isoformat()]
    if media:
        items = [t for t in items if t.get("media_type") == media]
    if period == "week":
        from datetime import timedelta
        end = (today() + timedelta(days=7)).isoformat()
        items = [t for t in items if t["release_date"] <= end]
    filters = '<div class="tabs">' + ''.join(f'<a class="{"selected" if media == m else ""}" href="/calendar{("?" + urlencode({"type":m})) if m else ""}">{label}</a>' for m,label in ((None,"Все премьеры"),("movie","Фильмы"),("tv","Сериалы"))) + '<a href="/calendar?period=week">Ближайшие 7 дней</a></div>'
    content = f'''<div class="page-shell"><section class="page-intro"><span class="eyebrow muted">ЕСТЬ ЧТО ЖДАТЬ</span><h1>Календарь премьер<span class="lime">.</span></h1><p>Выбирайте, что посмотреть следующим: премьеры фильмов, старты сезонов и новые серии.<br>Доступность может отличаться в зависимости от страны и платформы.</p></section>{filters}<div class="calendar-full">{premiere_rows(items, config, 150)}</div>{bot_banner(config)}</div>'''
    return layout(config, "Календарь премьер фильмов и сериалов", "Ближайшие даты выхода фильмов и новых эпизодов сериалов. Добавьте проект в Telegram-бота КиноЖдун.", content, "/calendar", "calendar", noindex=bool(media or period == "week"))


def about(config):
    from website.service_pages import about as render_about
    return render_about(config)


def help_page(config):
    from website.service_pages import help_page as render_help
    return render_help(config)


def privacy(config):
    from website.service_pages import privacy as render_privacy
    return render_privacy(config)
