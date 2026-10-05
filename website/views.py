"""HTML rendering: all indexable content is served without JavaScript."""
import html
import json
import re
from datetime import date, datetime
from urllib.parse import urlencode

from website.editor import date_ru, today

CATEGORIES = {"news": "Новости", "movies": "Фильмы", "series": "Сериалы", "guides": "Гид КиноЖдуна"}


def esc(value):
    return html.escape(str(value or ""), quote=True)


def image(url, title, cls="", eager=False):
    if url and (url.startswith("https://image.tmdb.org/") or url == "/static/mascot.jpg"):
        return f'<img class="{cls}" src="{esc(url)}" alt="{esc(title)}" loading="{"eager" if eager else "lazy"}" decoding="async">'
    return f'<div class="{cls} art-placeholder"><span>КЖ</span><small>КИНО — ЭТО ОЖИДАНИЕ</small></div>'


def stamp(value):
    return value[:10].split("-")[::-1] if value else []


def layout(config, title, description, content, path="/", active="", schema=None, noindex=False, og_image=None):
    base = config["base_url"]
    structured = schema or {"@context": "https://schema.org", "@type": "WebSite", "name": "КиноЖдун", "url": base, "inLanguage": "ru"}
    jsonld = json.dumps(structured, ensure_ascii=False).replace("<", "\\u003c")
    nav = "".join(f'<a class="{"active" if active == key else ""}" href="{url}">{label}</a>' for key, url, label in (
        ("home", "/", "Главная"), ("news", "/news", "Новости"), ("movies", "/movies", "Фильмы"), ("series", "/series", "Сериалы"), ("calendar", "/calendar", "Календарь премьер")))
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
    og_img = esc(og_image or (base + "/static/logo_mascot.jpg"))
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    {verification}<title>{esc(title)} — КиноЖдун</title><meta name="description" content="{esc(description)}"><meta name="robots" content="{robots}">
    <link rel="canonical" href="{esc(base + path)}"><link rel="icon" href="/static/logo_mascot.jpg" type="image/jpeg"><link rel="icon" href="/static/icon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/static/logo_mascot.jpg">
    <meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:site_name" content="КиноЖдун"><meta property="og:locale" content="ru_RU"><meta property="og:type" content="{"article" if is_article else 'website'}"><meta property="og:url" content="{esc(base + path)}">
    <meta property="og:image" content="{og_img}">
    <meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(title)}"><meta name="twitter:description" content="{esc(description)}"><meta name="twitter:image" content="{og_img}">
    <meta name="theme-color" content="#111312"><link rel="alternate" type="application/rss+xml" title="КиноЖдун — новости" href="/feed.xml">
    <link rel="stylesheet" href="/static/site.css"><script type="application/ld+json">{jsonld}</script><script src="/static/site.js" defer></script>{metrika}</head>
    <body><a class="skip" href="#content">Перейти к содержимому</a><header><div class="header-inner"><a class="brand" href="/" aria-label="КиноЖдун — главная"><img class="brand-logo" src="/static/logo_mascot.jpg" alt="КиноЖдун" width="48" height="48"><span>кино<span class="brand-light">ждун</span><small>ХОРОШЕЕ КИНО СТОИТ ЖДАТЬ</small></span></a>
    <nav aria-label="Основная навигация">{nav}</nav><a class="button small" href="{esc(config['bot_url'])}" target="_blank" rel="noopener">↗ Открыть бота</a></div></header>
    <main id="content">{content}</main>
    <footer><div class="footer-top"><a class="brand footer-brand" href="/"><img class="brand-logo footer-logo" src="/static/logo_mascot.jpg" alt="КиноЖдун" width="38" height="38"><span>кино<span class="brand-light">ждун</span><span class="lime">✳</span></span></a><p>Ваш следующий любимый фильм<br>ещё впереди.</p><div><a href="{esc(config['channel_url'])}" target="_blank" rel="noopener">Telegram-канал ↗</a><a href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Бот с напоминаниями ↗</a><a href="/about">О проекте и источниках</a></div></div>
    <div class="footer-bottom"><span>© {today().year} КиноЖдун</span><span>Сделано для тех, кто ждёт</span><a href="/feed.xml">RSS ↗</a></div></footer></body></html>'''


def card(article, featured=False):
    category = CATEGORIES.get(article["category"], "Новости")
    return f'''<a class="news-card {'featured-card' if featured else ''}" href="/news/{esc(article['slug'])}">
      <div class="card-image">{image(article.get('image'), article['title'])}<span class="card-tag">{category}</span><span class="card-arrow">↗</span></div>
      <div class="card-copy"><div class="meta"><time datetime="{esc(article['published'])}">{'.'.join(stamp(article['published']))}</time><span>•</span><span>2 мин чтения</span></div>
      <h3>{esc(article['title'])}</h3><p>{esc(article['summary'])}</p></div></a>'''


def title_path(item):
    return f"/title/{item['media_type']}/{item['id']}"


def title_card(item):
    rating = f"★ {float(item['rating']):.1f}" if item.get("votes", 0) >= 50 else "Рейтинг формируется"
    label = "Фильм" if item["media_type"] == "movie" else "Сериал"
    return f'''<a class="news-card title-card" href="{title_path(item)}"><div class="card-image">{image(item.get('poster') or item.get('image'), item['title'])}<span class="card-tag">{label}</span></div><div class="card-copy"><span class="meta">{rating} · {esc((item.get('first_release') or '')[:4])}</span><h3>{esc(item['title'])}</h3><p>{esc(item.get('overview', '')[:180])}</p></div></a>'''


def trailer_player(key, language=None):
    if not key or not re.fullmatch(r"[\w-]{6,32}", key, flags=re.ASCII):
        return ""
    label = "На русском языке" if language == "ru" else "На языке источника"
    return f'''<section class="trailer-section"><h2>Смотреть трейлер</h2><p>{label}</p><div class="trailer-frame"><iframe src="https://www.youtube-nocookie.com/embed/{esc(key)}" title="Трейлер" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div><p><a href="https://www.youtube.com/watch?v={esc(key)}" target="_blank" rel="noopener">Открыть трейлер на YouTube ↗</a></p></section>'''


def title_page(store, config, item):
    rating = f"{float(item.get('rating') or 0):.1f} / 10 · {item.get('votes', 0)} голосов" if item.get("votes", 0) >= 50 else "Рейтинг ещё формируется"
    related = [a for a in store.articles(limit=500) if a.get("media_type") == item["media_type"] and a.get("tmdb_id") == item["id"]][:6]
    content = f'''<div class="page-shell"><article class="article"><span class="eyebrow lime">{'Фильм' if item['media_type'] == 'movie' else 'Сериал'}</span><h1>{esc(item['title'])}</h1><div class="title-detail"><div>{image(item.get('poster'), item['title'], 'title-poster', eager=True)}</div><div class="article-body"><p class="article-lead">{esc(item.get('overview'))}</p><p><strong>Рейтинг TMDB:</strong> {rating}</p><p>{esc(', '.join(item.get('genres', [])))}</p><p><strong>Первая премьера:</strong> {date_ru(item.get('first_release'))}</p><p><strong>Ближайший выход:</strong> {date_ru(item.get('release_date'))}</p><a class="button" href="{esc(title_link(item, config))}" target="_blank" rel="noopener">Отслеживать в Telegram ↗</a><p class="source"><a href="{esc(item['source_url'])}" target="_blank" rel="noopener">Источник: TMDB ↗</a></p></div></div>{trailer_player(item.get('trailer'), item.get('trailer_language'))}</article><section class="news-section"><h2>Новости проекта</h2><div class="news-grid">{''.join(card(a) for a in related)}</div></section></div>'''
    schema = {"@context": "https://schema.org", "@type": "Movie" if item["media_type"] == "movie" else "TVSeries", "name": item["title"], "description": item.get("overview"), "url": config["base_url"] + title_path(item)}
    return layout(config, item["title"], item.get("overview", "")[:180], content, title_path(item), "movies" if item["media_type"] == "movie" else "series", schema=schema, og_image=item.get("image"))


def bot_banner(config):
    return f'''<section class="bot-banner"><div><span class="eyebrow">ВАШ ЛИЧНЫЙ ТРЕКЕР ПРЕМЬЕР</span><h2>Ждать — ваше дело.<br>Напомнить — наше<span class="lime">.</span></h2><p>Добавьте фильм или сериал в Telegram-бота.<br>КиноЖдун сообщит, когда появится дата выхода.</p><a class="button" href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Начать ждать в боте <span>↗</span></a><small>Бесплатно. Без установки. В вашем Telegram.</small></div><div class="chat-scene" aria-label="Пример работы бота"><div class="chat-top"><img class="chat-avatar" src="/static/logo_mascot.jpg" alt="КиноЖдун"><div>КиноЖдун<small>бот · ваш список ожидания</small></div><span>•••</span></div><div class="bubble own">Хочу следить за новым сезоном</div><div class="bubble"><strong>🍿 Уже ждём вместе!</strong><p>Добавьте любимый сериал в список. Я проверю дату и пришлю уведомление, когда она появится.</p><span class="chat-action">✓ В списке ожидания</span></div><div class="chat-input">Написать сообщение… <span>➤</span></div></div></section>'''


def title_link(item, config):
    return config["bot_url"] + "?start=c_" + item["media_type"] + "_" + str(item["id"])


def premiere_rows(items, config, limit=5):
    items = sorted([i for i in items if i.get("release_date") and i["release_date"] >= today().isoformat()], key=lambda i: i["release_date"])
    if not items:
        return '<div class="empty compact"><span>◷</span><h3>Новые даты — скоро здесь</h3><p>Показываем только даты из источника. Следите за любимыми проектами в боте.</p></div>'
    rows = []
    for item in items[:limit]:
        d = date.fromisoformat(item["release_date"])
        diff_days = (d - today()).days
        if diff_days == 0:
            badge = '<span class="date-badge date-today">Сегодня!</span>'
        elif diff_days == 1:
            badge = '<span class="date-badge date-tomorrow">Завтра</span>'
        else:
            badge = f'<span class="date-badge">через {diff_days} дн.</span>'
        month = ["ЯНВ", "ФЕВ", "МАР", "АПР", "МАЙ", "ИЮН", "ИЮЛ", "АВГ", "СЕН", "ОКТ", "НОЯ", "ДЕК"][d.month - 1]
        label = "Фильм" if item["media_type"] == "movie" else "Сериал"
        if item.get("episode"):
            label += f" · {item.get('season') or '?'} сезон, {item['episode']} серия"
        rows.append(f'''<div class="premiere-row"><div class="premiere-date"><b>{d.day:02}</b><span>{month} {d.year}</span>{badge}</div><div class="premiere-poster">{image(item.get('poster'), item['title'])}</div><div class="premiere-title"><strong>{esc(item['title'])}</strong><span>{esc(label)}</span></div><a class="reminder" href="{esc(title_link(item, config))}" target="_blank" rel="noopener" aria-label="Отслеживать {esc(item['title'])}">＋ <span>Ждать</span></a></div>''')
    return "".join(rows)


def home(store, config):
    articles, seen = [], set()
    for article in store.articles(limit=40):
        if article.get("release_date") and article["release_date"] < today().isoformat():
            continue
        key = (article['media_type'], article['tmdb_id']) if article.get('tmdb_id') else article['slug']
        if key not in seen:
            articles.append(article)
            seen.add(key)
        if len(articles) == 7:
            break
    titles = store.catalog() if config.get("catalog_size") else store.titles()
    main_article = next((a for a in articles if a.get("image")), articles[0] if articles else None)
    hero_media = image((main_article.get("image") if main_article else None) or "/static/mascot.jpg", main_article["title"] if main_article and main_article.get("image") else "Ждун в кинотеатре — талисман КиноЖдуна", "hero-image", eager=True)
    spotlight = f'''<a class="hero-story" href="/news/{esc(main_article['slug'])}"><span>В ФОКУСЕ</span><strong>{esc(main_article['title'])}</strong><i>↗</i></a>''' if main_article else ""
    content = f'''<div class="page-shell"><div class="edition"><span><i class="live-dot"></i> КИНО, СЕРИАЛЫ И ВСЁ, ЧТО МЫ ЖДЁМ</span><span>ВАШ ПРОВОДНИК В МИР ПРЕМЬЕР ↙</span></div>
    <section class="hero">{hero_media}<div class="hero-shade"></div><div class="hero-content"><span class="eyebrow"><span class="live-dot"></span> В ОЖИДАНИИ ХОРОШЕГО КИНО</span><h1>Следующее<br>«вау» —<br><em>уже близко.</em></h1><p>Новости кино и сериалов, даты премьер<br>и новые сезоны. Всё, ради чего стоит ждать.</p><div class="hero-actions"><a class="button" href="/calendar">Что скоро выйдет <span>↗</span></a><a class="text-link" href="{esc(config['channel_url'])}" target="_blank" rel="noopener">Наш Telegram ↗</a></div></div><span class="hero-mark">✳</span>{spotlight}</section>
    <div class="ticker"><span>НЕ ПРОПУСТИТЕ ГЛАВНОЕ</span><div>НОВЫЕ СЕЗОНЫ <i>✳</i> БОЛЬШИЕ ПРЕМЬЕРЫ <i>✳</i> ТРЕЙЛЕРЫ <i>✳</i> ДАТЫ ВЫХОДА <i>✳</i> ВАШ СПИСОК ОЖИДАНИЯ</div></div>
    <section class="news-section"><div class="section-heading"><div><span class="eyebrow muted">ЛЕНТА КИНОЖДУНА</span><h2>Пока вы ждёте<span class="lime">.</span></h2></div><a class="text-link" href="/news">Все материалы ↗</a></div>
    <div class="tabs"><a class="selected" href="/news">Всё интересное</a><a href="/movies">Фильмы</a><a href="/series">Сериалы</a><a href="/news?category=guides">Гид КиноЖдуна</a><span class="tabs-note">Ничего лишнего. Только кино.</span></div><div class="news-grid">{''.join(card(a) for a in articles[:6])}</div></section>
    <section class="calendar-teaser"><div><span class="eyebrow muted">СОХРАНИТЕ ДАТУ</span><h2>Скоро<br>на экранах<span class="lime">.</span></h2><p>Премьеры, которые уже<br>появились в календаре.</p><a class="text-link" href="/calendar">Весь календарь ↗</a></div><div class="premiere-list">{premiere_rows(titles, config)}</div></section>
    <section class="news-section"><div class="section-heading"><h2>Что посмотреть<span class="lime">.</span></h2><a href="/movies">Все фильмы и сериалы ↗</a></div><div class="news-grid">{''.join(title_card(t) for t in store.catalog()[-6:])}</div></section>
    {bot_banner(config)}
    <section class="channel-section"><span class="channel-symbol">↗</span><div><span class="eyebrow muted">КИНОЖДУН В TELEGRAM</span><h2>Хорошие новости.<br>В хорошей компании.</h2><p>Новости кино, трейлеры и главные премьеры — в нашем канале.</p></div><a class="button outline" href="{esc(config['channel_url'])}" target="_blank" rel="noopener">Перейти в канал ↗</a></section></div>'''
    return layout(config, "Новости кино и сериалов, даты выхода и новые сезоны", "КиноЖдун — новости фильмов и сериалов, календарь премьер и Telegram-бот для отслеживания дат выхода.", content, active="home")


def listing(store, config, category, query, page):
    size = 12
    articles = store.articles(category, query, size + 1, (page - 1) * size)
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
    body = "".join(f'<p>{esc(p)}</p>' for p in json.loads(article["body"]))
    trailer_key = article["fingerprint"].split(":trailer:")[-1] if ":trailer:" in article["fingerprint"] else None
    item = store.catalog_item(f"{article.get('media_type')}:{article.get('tmdb_id')}")
    if trailer_key:
        body += trailer_player(trailer_key, (item or {}).get("trailer_languages", {}).get(trailer_key))
    if item:
        body += f'<p><a href="{title_path(item)}">Карточка «{esc(item["title"])}» ↗</a></p>'
    bot_url = (config["bot_url"] + f"?start=c_{article['media_type']}_{article['tmdb_id']}" if article.get("media_type") in ("tv", "movie") and article.get("tmdb_id") else config["bot_url"])
    related = [a for a in store.articles(limit=7) if a["slug"] != article["slug"]][:3]

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
    if article.get("release_date"):
        try:
            rd = date.fromisoformat(article["release_date"])
            diff = (rd - today()).days
            if diff > 0:
                release_badge = f'<div class="article-countdown">📅 Премьера: <b>{date_ru(article["release_date"])}</b> (через {diff} дн.)</div>'
            elif diff == 0:
                release_badge = f'<div class="article-countdown">🎉 Премьера <b>сегодня</b> ({date_ru(article["release_date"])})!</div>'
        except (ValueError, TypeError):
            pass

    content = f'''<div class="page-shell"><div class="breadcrumbs"><a href="/">Главная</a> / <a href="/news">Материалы</a> / {category}</div><article class="article"><span class="eyebrow lime">{category}</span><h1>{esc(article['title'])}</h1><div class="meta"><span>Редакция КиноЖдуна</span><span>•</span><time datetime="{esc(article['published'])}">{'.'.join(stamp(article['published']))}</time></div>{release_badge}<p class="article-lead">{esc(article['summary'])}</p>{image(article.get('image'), article['title'], 'article-cover', eager=True)}<div class="article-body">{body}<div class="source"><strong>Источник материала</strong><a href="{esc(article['source_url'])}" target="_blank" rel="noopener noreferrer">Открыть источник ↗</a><small>Сведения могут обновляться. Подробнее — <a href="/about">о нашей редакции</a>.</small></div><div class="article-cta"><h2>Не пропустите премьеру</h2><p>Сохраните проект в трекер: КиноЖдун пришлёт уведомление в Telegram за 3 дня до даты выхода.</p><a class="button" href="{esc(bot_url)}" target="_blank" rel="noopener">🔔 Напомнить о премьере в Telegram ↗</a></div></div></article><section class="news-section"><div class="section-heading"><h2>Ещё немного кино<span class="lime">.</span></h2><a href="/news" class="text-link">Все материалы ↗</a></div><div class="news-grid">{''.join(card(a) for a in related)}</div></section></div>'''
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
    content = f'''<div class="page-shell"><section class="page-intro"><span class="eyebrow muted">ЕСТЬ ЧТО ЖДАТЬ</span><h1>Календарь премьер<span class="lime">.</span></h1><p>Даты фильмов и ближайших эпизодов сериалов по данным TMDB.<br>Дата в каталоге может отличаться от даты выхода в вашей стране.</p></section>{filters}<div class="calendar-full">{premiere_rows(items, config, 150)}</div>{bot_banner(config)}</div>'''
    return layout(config, "Календарь премьер фильмов и сериалов", "Ближайшие даты выхода фильмов и новых эпизодов сериалов. Добавьте проект в Telegram-бота КиноЖдун.", content, "/calendar", "calendar", noindex=bool(media or period == "week"))


def about(config):
    content = f'''<div class="page-shell"><section class="page-intro"><span class="eyebrow muted">ХОРОШЕЕ КИНО СТОИТ ЖДАТЬ</span><h1>Мы тоже ждём<span class="lime">.</span></h1></section><div class="about article-body"><h2>Что такое КиноЖдун</h2><p>КиноЖдун объединяет новости, календарь премьер, Telegram-канал и личный бот для отслеживания фильмов и сериалов.</p><h2>Откуда берутся материалы</h2><p>Редакция работает автоматически: проверяет каталог TMDB, сравнивает даты, статусы и трейлеры, а также переносит уже опубликованные подтверждённые сообщения из базы нашего Telegram-канала. Каждая публикация содержит ссылку на источник. Сайт не публикует слухи и не генерирует вымышленные факты.</p><p>TMDB — каталог, который наполняет сообщество. Его записи не равнозначны официальным заявлениям студии. Международная дата выхода может отличаться от российской или цифровой премьеры. Для сериалов календарь показывает дату ближайшего эпизода, если она известна.</p><h2>Как отбираются карточки</h2><p>Подбираем популярные новинки и ожидаемые проекты. При 50 и более голосах нужен рейтинг TMDB не ниже 6 из 10; также требуется популярность от 5. Популярность — показатель интереса в каталоге, а не отдельный рейтинг ожидаемости. Первые 50 карточек публикуются по 3 в день. Для трейлеров предпочитаем русскую версию, а при её отсутствии показываем доступный официальный ролик.</p><h2>Что делает бот</h2><p>Сохраняет список ожидания и проверяет обновления о выбранных проектах. Вы можете поделиться списком с другом и задать дату вручную.</p><h2>Источники и изображения</h2><p>Данные и изображения предоставлены <a href="https://www.themoviedb.org" target="_blank" rel="noopener">The Movie Database</a>.</p><img class="tmdb-logo" src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_short-8e7b30f73a4020692ccca9c88bafe5dcb6f8a62a4c6bc55cd9ba82bb2cd95f6c.svg" alt="TMDB"><p lang="en">This product uses the TMDB API but is not endorsed or certified by TMDB.</p><p>При недоступности источника сайт сохраняет ранее опубликованные материалы и повторяет проверку автоматически.</p></div>{bot_banner(config)}</div>'''
    return layout(config, "О проекте и источниках", "Как работает КиноЖдун: источники новостей, автоматическая редакция и Telegram-бот.", content, "/about")
