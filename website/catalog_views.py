"""Streaming-style catalogue pages, with server-side search and filters."""
import re
from datetime import date
from urllib.parse import urlencode

from website.editor import today, date_ru
from website.views import esc, image, layout, title_path, title_link, trailer_player, card, premiere_rows
from website.title_names import seo_names, normalized
from website.home_state import event_state, hero_projects, waiting, change_type, relative_time, watch_label


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


def project_page(store, config, item, news_page=1):
    alternatives = seo_names(item)
    other_names = '<p class="project-alternate-names">' + esc(' · '.join(alternatives)) + '</p>' if alternatives else ''
    movie = item["media_type"] == "movie"
    kind = "Фильм" if movie else "Сериал"
    catalog_url = "/movies" if movie else "/series"
    year = (item.get("first_release") or "")[:4]
    rating = rating_label(item)
    genres = ' · '.join(g.capitalize() for g in item.get("genres", []))
    release = item.get("release_date") if not movie else item.get("first_release")
    future = bool(release and release > today().isoformat())
    state = "Скоро премьера" if future else "Уже вышел" if movie and release else "Сериал"
    if not movie and future and item.get("season"):
        state = "Новый сезон скоро" if item.get("episode") == 1 else "Новая серия скоро"
    meta = f'<span class="score">★ {rating} <small>TMDB</small></span>' if rating else '<span class="unrated">Рейтинг формируется</span>'
    meta += f'<span>{esc(year)}</span><span>{kind}</span>'
    if not movie and item.get("season"):
        meta += f'<span>{item["season"]} сезон</span>'
    tracker = title_link(item, config)
    watch = '<a class="button outline" href="#trailer"><span aria-hidden="true">▶</span> Смотреть трейлер</a>' if item.get("trailer") else ''
    date_label = "Премьера" if future and movie else "Дата выхода" if movie else "Следующий эпизод"
    dates = f'<div><dt>{date_label}</dt><dd>{date_ru(release)}</dd></div>'
    if not movie and item.get("season") and item.get("episode"):
        dates += f'<div><dt>Ближайшая серия</dt><dd>{item["season"]} сезон · {item["episode"]} серия</dd></div>'
    if not movie and item.get("season_premiere"):
        label = f"Премьера {item['premiere_season']}-го сезона"
        dates += f'<div><dt>{label}</dt><dd>{date_ru(item["season_premiere"])}</dd></div>'
    if rating:
        dates += f'<div><dt>Оценки зрителей</dt><dd>{item.get("votes", 0):,} голосов</dd></div>'.replace(',', ' ')
    news_count = store.title_articles_count(item["media_type"], item["id"])
    news_page = min(max(1, news_page), max(1, (news_count + 19) // 20))
    related_news = store.title_articles(item["media_type"], item["id"], offset=(news_page-1)*20)
    pager = []
    if news_page > 1:
        pager.append(f'<a href="{title_path(item)}?news_page={news_page-1}#news-history">← Более новые</a>')
    if news_page * 20 < news_count:
        pager.append(f'<a href="{title_path(item)}?news_page={news_page+1}#news-history">Более ранние →</a>')
    pagination = '<nav class="pagination" aria-label="История новостей">' + ''.join(pager) + '</nav>' if pager else ''
    entries = '<div class="news-grid">' + ''.join(card(a) for a in related_news) + '</div>' if related_news else '<p class="muted">Новостей об этом проекте пока нет. Они появятся здесь после публикации.</p>'
    news = f'<section id="news-history" class="collection project-news"><div class="collection-heading"><div><span class="eyebrow muted">ОТ НОВЫХ К РАННИМ · {news_count}</span><h2>История новостей</h2></div></div>{entries}{pagination}</section>'
    other = [t for t in store.catalog() if t["key"] != item["key"] and t["media_type"] == item["media_type"]]
    other.sort(key=lambda t: len(set(t.get('genres', [])) & set(item.get('genres', []))), reverse=True)
    trailer = f'<div id="trailer" class="theater">{trailer_player(item.get("trailer"), item.get("trailer_language"), item.get("trailer_season"))}</div>' if item.get("trailer") else '<div class="trailer-unavailable"><span>Трейлер пока не опубликован</span><p>Добавим официальный ролик, когда он появится.</p></div>'
    content = f'''<div class="project-shell"><div class="page-shell"><div class="breadcrumbs"><a href="/catalog">Каталог</a><span> / </span><a href="{catalog_url}">{'Фильмы' if movie else 'Сериалы'}</a><span> / </span>{esc(item['title'])}</div></div><section class="project-hero">{image(item.get('image'), item['title'], 'project-backdrop', eager=True)}<div class="project-gradient"></div><div class="page-shell project-grid"><div class="project-poster">{image(item.get('poster'), item['title'], eager=True)}</div><div class="project-copy"><span class="eyebrow lime">{state}</span><h1>{esc(item['title'])}</h1>{other_names}<div class="project-meta">{meta}</div><p class="project-genres">{esc(genres)}</p><p class="project-overview">{esc(item.get('overview'))}</p><div class="project-actions"><a class="button" href="{esc(tracker)}" target="_blank" rel="noopener">{watch_label(item)}</a>{watch}<a class="button outline" href="#news-history">История новостей</a></div><p class="tracking-note">В список ожидания можно добавить проект в Telegram. Бот сообщит об изменениях и напомнит о выходе.</p></div></div></section><div class="page-shell"><dl class="project-facts">{dates}<div><dt>Источник</dt><dd><a href="{esc(item['source_url'])}" target="_blank" rel="noopener">TMDB ↗</a></dd></div></dl>{trailer}{news}{collection(other[:6], 'Вам может понравиться', catalog_url, 'ЕЩЁ НЕМНОГО КИНО')}</div></div>'''
    schema = {"@context": "https://schema.org", "@type": "Movie" if movie else "TVSeries", "name": item["title"], "description": item.get("overview"), "url": config["base_url"] + title_path(item)}
    if alternatives:
        schema['alternateName'] = alternatives
    original = item.get('original_title') or ''
    qualifier = []
    if normalized(original) != normalized(item['title']) and len(item['title']) + len(original) <= 90:
        qualifier.append(original)
    if year:
        qualifier.append(year)
    seo_title = item['title'] + (' (' + ', '.join(qualifier) + ')' if qualifier else '')
    seo_title += ' — дата выхода' if movie else ' — дата выхода серий'
    release_info = f"{date_label}: {date_ru(release)}." if release else f"{date_label}: дата пока не указана в источнике."
    display_names = item['title'] + (' (' + ', '.join(alternatives) + ')' if alternatives else '')
    description = f"{display_names}. {release_info} Описание, трейлер и новости {'фильма' if movie else 'сериала'} на КиноЖдуне."
    return layout(config, seo_title, description, content, title_path(item), "movies" if movie else "series", schema=schema, og_image=item.get("image"))


def catalog_page(store, config, path, params, extra_items=None):
    from website.search import matches
    all_items = store.catalog()
    if params.get('q') and extra_items:
        merged = {item['key']: item for item in all_items}
        merged.update({item['key']: item for item in extra_items})
        all_items = list(merged.values())
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
    selected = [t for t in scoped if (t.get('remote_match') or matches(t, query)) and (not genre or genre in t.get('genres', [])) and (not minimum or (t.get('votes', 0) >= 50 and float(t.get('rating') or 0) >= float(minimum)))]
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


def tracking_events(store, limit=4):
    return [article for article in store.articles(limit=500)
            if change_type(article)][:limit]


def tracking_collection(items, heading, url, config):
    content = collection(items, heading, url, 'ДОБАВЬТЕ В СВОЙ СПИСОК')
    for item in items[:10]:
        poster = poster_card(item)
        state = event_state(item)
        context = f'<p class="waiting-context">{esc(state["detail"] or state["headline"])}</p>'
        content = content.replace(poster, '<div class="tracked-project">' + poster + context + f'<a class="track-project" href="{esc(title_link(item, config))}" target="_blank" rel="noopener" aria-label="{watch_label(item)}: {esc(item["title"])}">{watch_label(item)}</a></div>', 1)
    return content


def spotlight_slide(item, config, index):
    state = event_state(item)
    rating = rating_label(item)
    meta = ' · '.join(filter(None, ['★ ' + rating + ' TMDB' if rating else '',
                                  (item.get('first_release') or '')[:4],
                                  ' · '.join(item.get('genres', [])[:2])]))
    art = image(item.get('image') or item.get('poster'), item['title'], 'spotlight-image', eager=index == 0)
    if index == 0:
        art = art.replace('decoding="async"', 'decoding="async" fetchpriority="high"')
    else:
        # Only the next slide is hydrated by JS; avoid fetching all backdrops at once.
        art = art.replace(' src="', ' data-src="')
    heading = 'h1' if index == 0 else 'h2'
    title_class = 'spotlight-title long-title' if len(item['title']) > 32 else 'spotlight-title'
    hidden = ' hidden inert aria-hidden="true"' if index else ' aria-hidden="false"'
    return f'''<article class="spotlight-slide" data-slide="{index}" role="group" aria-label="{esc(item['title'])}"{hidden}>{art}<div class="spotlight-shade"></div><div class="spotlight-copy"><span class="eyebrow lime">{esc(state['label'])}</span><{heading} class="{title_class}">{esc(item['title'])}</{heading}><div class="spotlight-meta">{esc(meta)}</div><div class="featured-event"><strong>{esc(state['headline'])}</strong><span>{esc(state['detail'])}</span></div><div class="spotlight-actions"><a class="button" href="{esc(title_link(item, config))}" target="_blank" rel="noopener">{watch_label(item)}</a><a class="button outline" href="{title_path(item)}">Подробнее ↗</a></div></div></article>'''


def streaming_home(store, config):
    titles = store.catalog()
    events = tracking_events(store, 6)
    featured = hero_projects(titles, events)
    slides = ''.join(spotlight_slide(item, config, i) for i, item in enumerate(featured))
    controls = ''
    if len(featured) > 1:
        dots = ''.join(f'<button type="button" data-go="{i}" aria-label="Показать: {esc(item["title"])}" aria-pressed="{str(i == 0).lower()}"><span></span></button>' for i, item in enumerate(featured))
        controls = f'''<div class="spotlight-controls" hidden><div class="spotlight-dots">{dots}</div><span class="spotlight-counter" aria-live="off">1 / {len(featured)}</span><button type="button" data-direction="-1" aria-label="Предыдущий проект">←</button><button type="button" data-direction="1" aria-label="Следующий проект">→</button><button type="button" class="spotlight-pause" aria-label="Остановить автопереключение" aria-pressed="false">Ⅱ</button></div><span class="sr-only spotlight-announcement" role="status" aria-live="polite"></span>'''
    hero = f'<section class="spotlight dynamic-spotlight" aria-label="Стоит дождаться" aria-roledescription="карусель">{slides}{controls}</section>' if featured else '<section class="home-empty"><span class="eyebrow lime">СТОИТ ДОЖДАТЬСЯ</span><h1>Хорошее кино ещё впереди.</h1><p>Новые проекты появятся после обновления каталога. Выберите любимый фильм или сериал в Telegram — бот сообщит об изменениях.</p></section>'
    updates = []
    for article in events:
        icon, label = change_type(article)
        updates.append(f'''<a class="compact-change event-change" href="/news/{esc(article['slug'])}"><span class="change-icon" aria-hidden="true">{icon}</span><div><span class="change-label">{label}</span><strong>{esc(article['title'])}</strong><small><time datetime="{esc(article['published'])}">{esc(relative_time(article['published']))}</time> · TMDB</small></div><i aria-hidden="true">↗</i></a>''')
    changes = '<section class="collection"><div class="collection-heading"><h2>Что изменилось</h2><a class="text-link" href="/news">Все события ↗</a></div><div class="compact-changes">' + ''.join(updates) + '</div></section>' if updates else ''
    popular = sorted([t for t in titles if waiting(t)], key=lambda t: (-float(t.get('popularity') or 0), t['media_type'], t['id']))
    anticipated = tracking_collection(popular, 'Больше всего ждут', '/catalog', config)
    if anticipated:
        anticipated = anticipated.replace('ДОБАВЬТЕ В СВОЙ СПИСОК', 'ПОПУЛЯРНЫЕ ОЖИДАЕМЫЕ ПРОЕКТЫ')
    telegram = f'''<section class="discovery-banner"><div><span class="eyebrow lime">КИНОЖДУН В TELEGRAM</span><h2>Не проверяйте даты сами.</h2><p>Выберите фильм или сериал — КиноЖдун сообщит в Telegram, когда что-нибудь изменится.</p></div><a class="button" href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Открыть бота ↗</a></section>'''
    content = f'''<div class="page-shell streaming-home"><div class="tracker-heading"><span>ТРЕКЕР ЛЮБИМЫХ ФИЛЬМОВ И СЕРИАЛОВ</span><a href="{esc(config['bot_url'])}" target="_blank" rel="noopener">Мой список в Telegram ↗</a></div>{hero}<section class="collection"><div class="collection-heading"><h2>Ближайшие события</h2><a class="text-link" href="/calendar">Весь календарь ↗</a></div>{premiere_rows(titles, config, 5)}<p class="event-source-note">Даты по данным TMDB. Доступность зависит от региона и платформы.</p></section>{anticipated}{changes}{telegram}</div>'''
    return layout(config, 'Трекер любимых фильмов и сериалов', 'Ждите любимые фильмы и сериалы: ближайшие премьеры, новые серии и изменения проектов с уведомлениями в Telegram.', content, '/', 'home', og_image=featured[0].get('image') if featured else None)
