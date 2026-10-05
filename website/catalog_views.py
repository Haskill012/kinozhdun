"""Streaming-style catalogue pages, with server-side search and filters."""
from datetime import date
from urllib.parse import urlencode

from website.editor import today, date_ru
from website.views import esc, image, layout, title_path, title_link, trailer_player, card


def rating_label(item):
    return f"{float(item.get('rating') or 0):.1f}" if item.get("votes", 0) >= 50 else None


def poster_card(item):
    rating = rating_label(item)
    year = (item.get("first_release") or "")[:4]
    kind = "Фильм" if item["media_type"] == "movie" else "Сериал"
    genres = item.get("genres", [])
    badge = f'<span class="poster-rating">★ {rating}</span>' if rating else ''
    return f'''<a class="poster-card" href="{title_path(item)}" aria-label="{esc(item['title'])}, {kind.lower()}, {esc(year)}"><div class="poster-art">{image(item.get('poster') or item.get('image'), item['title'])}{badge}<span class="poster-open">Подробнее ↗</span></div><div class="poster-copy"><h3>{esc(item['title'])}</h3><p>{esc(year)}<span> · </span>{kind}</p><small>{esc(genres[0].capitalize() if genres else '')}</small></div></a>'''


def collection(items, heading, url, eyebrow="ВЫБОР КИНОЖДУНА"):
    if not items:
        return ""
    return f'''<section class="collection"><div class="collection-heading"><div><span class="eyebrow muted">{eyebrow}</span><h2>{heading}</h2></div><a class="text-link" href="{url}">Смотреть все ↗</a></div><div class="poster-rail">{''.join(poster_card(t) for t in items[:10])}</div></section>'''


def project_page(store, config, item):
    movie = item["media_type"] == "movie"
    kind = "Фильм" if movie else "Сериал"
    catalog_url = "/movies" if movie else "/series"
    year = (item.get("first_release") or "")[:4]
    rating = rating_label(item)
    genres = ' · '.join(g.capitalize() for g in item.get("genres", []))
    release = item.get("release_date") if not movie else item.get("first_release")
    future = bool(release and release > today().isoformat())
    state = "Скоро премьера" if future else "Уже вышел" if movie and release else "Сериал"
    meta = f'<span class="score">★ {rating} <small>TMDB</small></span>' if rating else '<span class="unrated">Рейтинг формируется</span>'
    meta += f'<span>{esc(year)}</span><span>{kind}</span>'
    tracker = title_link(item, config)
    watch = '<a class="button" href="#trailer"><span aria-hidden="true">▶</span> Смотреть трейлер</a>' if item.get("trailer") else ''
    date_label = "Премьера" if future and movie else "Дата выхода" if movie else "Следующий эпизод"
    dates = f'<div><dt>{date_label}</dt><dd>{date_ru(release)}</dd></div>'
    if not movie and item.get("season") and item.get("episode"):
        dates += f'<div><dt>Ближайшая серия</dt><dd>{item["season"]} сезон · {item["episode"]} серия</dd></div>'
    if rating:
        dates += f'<div><dt>Оценки зрителей</dt><dd>{item.get("votes", 0):,} голосов</dd></div>'.replace(',', ' ')
    related_news = [a for a in store.articles(limit=500) if a.get("media_type") == item["media_type"] and a.get("tmdb_id") == item["id"]][:3]
    news = f'<section class="collection project-news"><div class="collection-heading"><h2>Новости проекта</h2><a href="/news">Все новости ↗</a></div><div class="news-grid">{"".join(card(a) for a in related_news)}</div></section>' if related_news else ''
    other = [t for t in store.catalog() if t["key"] != item["key"] and t["media_type"] == item["media_type"]]
    other.sort(key=lambda t: len(set(t.get('genres', [])) & set(item.get('genres', []))), reverse=True)
    trailer = f'<div id="trailer" class="theater">{trailer_player(item.get("trailer"), item.get("trailer_language"))}</div>' if item.get("trailer") else '<div class="trailer-unavailable"><span>Трейлер пока не опубликован</span><p>Добавим официальный ролик, когда он появится.</p></div>'
    content = f'''<div class="project-shell"><div class="page-shell"><div class="breadcrumbs"><a href="/catalog">Каталог</a><span> / </span><a href="{catalog_url}">{'Фильмы' if movie else 'Сериалы'}</a><span> / </span>{esc(item['title'])}</div></div><section class="project-hero">{image(item.get('image'), item['title'], 'project-backdrop', eager=True)}<div class="project-gradient"></div><div class="page-shell project-grid"><div class="project-poster">{image(item.get('poster'), item['title'], eager=True)}</div><div class="project-copy"><span class="eyebrow lime">{state}</span><h1>{esc(item['title'])}</h1><div class="project-meta">{meta}</div><p class="project-genres">{esc(genres)}</p><p class="project-overview">{esc(item.get('overview'))}</p><div class="project-actions">{watch}<a class="button outline" href="{esc(tracker)}" target="_blank" rel="noopener">＋ В список ожидания</a></div><p class="tracking-note">Ваш список и напоминания — в Telegram-боте КиноЖдун.</p></div></div></section><div class="page-shell"><dl class="project-facts">{dates}<div><dt>Источник</dt><dd><a href="{esc(item['source_url'])}" target="_blank" rel="noopener">TMDB ↗</a></dd></div></dl>{trailer}{news}{collection(other[:6], 'Вам может понравиться', catalog_url, 'ЕЩЁ НЕМНОГО КИНО')}</div></div>'''
    schema = {"@context": "https://schema.org", "@type": "Movie" if movie else "TVSeries", "name": item["title"], "description": item.get("overview"), "url": config["base_url"] + title_path(item)}
    return layout(config, item["title"], item.get("overview", "")[:180], content, title_path(item), "movies" if movie else "series", schema=schema, og_image=item.get("image"))


def catalog_page(store, config, path, params):
    all_items = store.catalog()
    media = 'movie' if path == '/movies' else 'tv' if path == '/series' else params.get('type', '')
    media = media if media in ('movie', 'tv') else ''
    query = params.get('q', '')[:100].strip()
    genre = params.get('genre', '')[:80]
    sort = params.get('sort', 'popular')
    sort = sort if sort in ('popular', 'rating', 'newest') else 'popular'
    minimum = params.get('rating', '')
    minimum = minimum if minimum in ('6', '7', '8') else ''
    scoped = [t for t in all_items if not media or t['media_type'] == media]
    genres = sorted({g for t in scoped for g in t.get('genres', [])})
    selected = [t for t in scoped if query.casefold() in t['title'].casefold() and (not genre or genre in t.get('genres', [])) and (not minimum or (t.get('votes', 0) >= 50 and float(t.get('rating') or 0) >= float(minimum)))]
    if sort == 'rating':
        selected.sort(key=lambda t: float(t.get('rating') or 0) if t.get('votes', 0) >= 50 else -1, reverse=True)
    elif sort == 'newest':
        selected.sort(key=lambda t: t.get('first_release') or '', reverse=True)
    else:
        selected.sort(key=lambda t: float(t.get('popularity') or 0), reverse=True)
    heading = 'Фильмы' if path == '/movies' else 'Сериалы' if path == '/series' else 'Выбирайте своё кино'
    def options(values, active):
        return ''.join(f'<option value="{esc(value)}" {"selected" if value == active else ""}>{esc(label)}</option>' for value, label in values)
    type_filter = f'<label>Что смотрим<select name="type">{options([("", "Фильмы и сериалы"), ("movie", "Фильмы"), ("tv", "Сериалы")], media)}</select></label>' if path == '/catalog' else ''
    count = f'{len(selected)} из {len(scoped)}' if len(selected) != len(scoped) else str(len(selected))
    filters = f'''<form class="catalog-filters" action="{path}" method="get"><label class="catalog-search">Найти проект<input name="q" value="{esc(query)}" placeholder="Название фильма или сериала" maxlength="100"></label><details class="catalog-filter-more" open><summary>Жанр, рейтинг и порядок <span>⌄</span></summary><div class="catalog-filter-fields">{type_filter}<label>Жанр<select name="genre">{options([("", "Все жанры")] + [(g, g.capitalize()) for g in genres], genre)}</select></label><label>Рейтинг<select name="rating">{options([("", "Любой"), ("6", "От 6.0"), ("7", "От 7.0"), ("8", "От 8.0")], minimum)}</select></label><label>Порядок<select name="sort">{options([("popular", "По популярности"), ("rating", "По рейтингу"), ("newest", "Сначала новые")], sort)}</select></label></div></details><button class="button" type="submit">Найти</button></form>'''
    tabs = ''.join(f'<a class="{"selected" if path == url else ""}" href="{url}">{label}<span>{amount}</span></a>' for url, label, amount in (('/catalog', 'Всё', len(all_items)), ('/movies', 'Фильмы', sum(t['media_type']=='movie' for t in all_items)), ('/series', 'Сериалы', sum(t['media_type']=='tv' for t in all_items))))
    grid = f'<div class="poster-grid">{"".join(poster_card(t) for t in selected)}</div>' if selected else f'<div class="empty"><span>⌕</span><h2>Ничего не нашлось</h2><p>Попробуйте изменить название, жанр или рейтинг.</p><a class="button outline" href="{path}">Сбросить фильтры</a></div>'
    reset = f'<a href="{path}">Сбросить фильтры ↗</a>' if query or genre or minimum or media and path == '/catalog' else '<span>Отобрано по интересу зрителей</span>'
    content = f'''<div class="page-shell catalog-shell"><section class="catalog-intro"><span class="eyebrow lime">ХОРОШЕЕ КИНО СТОИТ ЖДАТЬ</span><h1>{heading}<span class="lime">.</span></h1><p>Громкие новинки, любимые сериалы и премьеры, которые уже хочется увидеть.</p></section><div class="catalog-tabs">{tabs}</div>{filters}<div class="catalog-results"><p><b>{count}</b> проектов</p>{reset}</div>{grid}<section class="catalog-note"><span class="live-dot"></span><p>Находите кино здесь. Сохраняйте в боте — он напомнит о премьере.</p><a href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Открыть КиноЖдуна ↗</a></section></div>'''
    return layout(config, heading, 'Популярные фильмы и сериалы: описания, рейтинги, даты выхода и трейлеры.', content, path, 'movies' if path == '/movies' else 'series' if path == '/series' else 'catalog', noindex=bool(query or genre or minimum or sort != 'popular' or media and path == '/catalog'))


def streaming_home(store, config):
    titles = store.catalog()
    films = [t for t in titles if t['media_type']=='movie']
    series = [t for t in titles if t['media_type']=='tv']
    featured = next((t for t in films if t.get('image') and t.get('trailer')), titles[0])
    rating = rating_label(featured)
    recent = store.articles(limit=3)
    content = f'''<div class="page-shell streaming-home"><section class="spotlight"><picture class="spotlight-art"><source media="(max-width: 520px)" srcset="{esc(featured.get('poster') or featured.get('image'))}">{image(featured.get('image'), featured['title'], 'spotlight-image', eager=True)}</picture><div class="spotlight-shade"></div><div class="spotlight-copy"><span class="eyebrow lime">В ЦЕНТРЕ ВНИМАНИЯ</span><h1>{esc(featured['title'])}</h1><div class="spotlight-meta">{'★ ' + rating + ' · ' if rating else ''}{esc((featured.get('first_release') or '')[:4])} · {esc(' · '.join(featured.get('genres', [])[:2]))}</div><p>{esc(featured.get('overview', ''))}</p><div class="spotlight-actions"><a class="button" href="{title_path(featured)}#trailer">▶ Смотреть трейлер</a><a class="button outline" href="{title_path(featured)}">О фильме ↗</a></div></div><a class="spotlight-discover" href="/catalog">Найдите своё следующее кино <span>↗</span></a></section>{collection(films, 'Большое кино', '/movies', 'ПОПУЛЯРНОЕ СЕЙЧАС')}{collection(series, 'Ещё одну серию?', '/series', 'ИСТОРИИ, ОТ КОТОРЫХ НЕ ОТОРВАТЬСЯ')}<section class="discovery-banner"><div><span class="eyebrow lime">ВАШ ЛИЧНЫЙ СПИСОК ОЖИДАНИЯ</span><h2>Нашли кино.<br>Теперь не пропустите.</h2><p>Сохраните фильм или сериал в Telegram.<br>КиноЖдун проверит дату и напомнит о премьере.</p></div><a class="button" href="{esc(config['bot_url'])}" target="_blank" rel="noopener">＋ Собрать свой список</a></section><section class="collection"><div class="collection-heading"><div><span class="eyebrow muted">БУДЬТЕ В КУРСЕ</span><h2>Пока вы ждёте</h2></div><a class="text-link" href="/news">Все новости ↗</a></div><div class="news-grid">{''.join(card(a) for a in recent)}</div></section></div>'''
    return layout(config, 'Фильмы, сериалы и всё, что мы ждём', 'Найдите следующий любимый фильм: популярные новинки, сериалы, трейлеры и календарь премьер КиноЖдуна.', content, '/', 'home', og_image=featured.get('image'))
