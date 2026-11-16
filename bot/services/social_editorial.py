"""Shared factual copy for social channels; never invent availability or sources."""
import html
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo


def moscow_today():
    return datetime.now(ZoneInfo('Europe/Moscow')).date()


def clean_text(value, limit=360):
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', html.unescape(str(value or '')))).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0].rstrip(' ,.;:') + '…'


def source_link(media_type, tmdb_id):
    return f'https://www.themoviedb.org/{media_type}/{tmdb_id}' if tmdb_id and media_type in ('tv', 'movie') else None


def event_copy(title, media_type='movie', event_type='announced', season_number=None,
               episode_number=None, air_date=None, network=None, overview=None,
               old_air_date=None, trailer_url=None, genres=None, tmdb_id=None,
               source_url=None, today=None, date_formatter=None):
    """Return complete paragraphs. Generic series dates never imply a season premiere."""
    today = today or moscow_today()
    format_date = date_formatter or (lambda d: d.strftime('%d.%m.%Y'))
    title = clean_text(title, 180)
    tv = media_type == 'tv'
    season = f'{season_number}-го сезона' if season_number else 'нового сезона'
    target = (f'{season_number} сезон · {episode_number} серия' if episode_number and season_number
              else f'{episode_number} серия' if episode_number
              else f'{season_number} сезон' if tv and season_number else 'сериал' if tv else 'фильм')
    past = bool(air_date and air_date < today)
    if event_type == 'catalog_feature':
        heading = f'🍿 Что посмотреть: «{title}»'
    elif event_type in ('announced', 'date_announced', 'episode_date'):
        if tv and episode_number:
            heading = f'📺 «{title}»: {target}'
        elif tv and season_number:
            heading = f'📅 «{title}»: дата выхода {season}'
        elif tv:
            heading = f'📺 «{title}»: ближайший выход по каталогу'
        else:
            heading = f'{"🍿 Уже вышло" if past else "🎬 Премьера сегодня" if air_date == today else "📅 Дата выхода"}: «{title}»'
    elif event_type in ('renewed', 'season_renewed'):
        heading = f'🎬 «{title}»: анонс продолжения'
    elif event_type == 'date_postponed':
        heading = f'📅 «{title}»: изменилась дата выхода'
    elif event_type == 'trailer':
        heading = f'🎬 «{title}»: новый трейлер'
    elif event_type == 'released':
        heading = f'🍿 «{title}»: релиз по каталогу'
    elif event_type in ('canceled', 'ended'):
        heading = f'📺 «{title}»: {"сериал закрыт" if event_type == "canceled" else "сериал завершён"}'
    elif event_type in ('filming_started', 'filming_finished'):
        heading = f'🎬 «{title}»: {"начались" if event_type == "filming_started" else "завершились"} съёмки'
    else:
        heading = f'🎬 «{title}»'
    details = []
    if tv and (season_number or episode_number):
        details.append(f'📺 {target.capitalize()}')
    if air_date:
        label = ('Новая дата' if event_type == 'date_postponed' else
                 'Дата серии по TMDB' if tv and episode_number else
                 'Дата сезона по TMDB' if tv and season_number and event_type != 'catalog_feature' else
                 'Ближайшая дата в каталоге' if tv else 'Дата премьеры по TMDB')
        details.append(f'📅 {label}: {format_date(air_date)}')
        if old_air_date and event_type == 'date_postponed':
            details.append(f'Ранее: {format_date(old_air_date)}')
        if not tv:
            details.append('Дата в каталоге не означает доступность в России или на конкретном сервисе.')
    elif event_type in ('announced', 'date_announced', 'renewed', 'season_renewed'):
        details.append('Дата выхода пока не объявлена.')
    if network:
        details.append(f'{"Канал / сервис" if tv else "Студия"}: {clean_text(network, 80)}')
    if genres:
        details.append('Жанры: ' + ', '.join(clean_text(g, 40) for g in genres[:3]))
    paragraphs = [heading, '\n'.join(details), clean_text(overview)]
    if trailer_url:
        paragraphs.append('Трейлер: ' + trailer_url)
    source = source_url or source_link(media_type, tmdb_id)
    if source:
        paragraphs.append('Источник: ' + source)
    return [p for p in paragraphs if p], past


def catalog_candidates(titles, today=None):
    """Prefer the near release window, then well-rated recommendations, deterministically."""
    today = today or moscow_today()
    candidates = []
    for raw in titles:
        if raw.get('media_type') not in ('tv', 'movie') or not raw.get('id') or not raw.get('title'):
            continue
        try:
            released = date.fromisoformat(raw.get('release_date') or '')
        except ValueError:
            released = None
        delta = (released - today).days if released else None
        if delta is not None and delta > 45:
            continue
        if delta is not None and delta < -365:
            continue
        try:
            rating = float(raw.get('rating') or raw.get('vote_average') or 0)
        except (ValueError, TypeError):
            rating = 0
        priority = (0, delta, -rating) if delta is not None and 0 <= delta <= 45 else (1, -rating, abs(delta or 0))
        candidates.append((priority, raw))
    return [raw for _, raw in sorted(candidates, key=lambda row: (row[0], str(row[1]['id'])))]


async def resolve_catalog_item(raw, tmdb_client=None, today=None, settings=None):
    """Refresh facts before a scheduled post; a TV seed date is never a premiere."""
    today = today or moscow_today()
    item = dict(raw)
    media = item['media_type']
    details = {}
    if tmdb_client:
        details = await (tmdb_client.get_tv_details(item['id']) if media == 'tv'
                         else tmdb_client.get_movie_details(item['id']))
        if not details:
            return None
        from shared.audience import audience_metadata, exclusion_reason
        policy = {'asian_min_votes': settings.SITE_ASIAN_MIN_VOTES,
                  'asian_min_popularity': settings.SITE_ASIAN_MIN_POPULARITY,
                  'audience_allow_keys': settings.SITE_AUDIENCE_ALLOW_KEYS} if settings else None
        if exclusion_reason({**details, **audience_metadata(media, details),
                             'media_type': media, 'key': f'{media}:{item["id"]}'}, policy):
            return None
        if (details.get('vote_count') or 0) >= 50 and (details.get('vote_average') or 0) < 6:
            return None
        item.update(title=details.get('title') or details.get('name') or item['title'],
                    overview=details.get('overview'), poster=details.get('poster_path'),
                    network=details.get('network') or None,
                    genres=[g['name'] for g in details.get('genres', []) if g.get('name')])
    item['event_type'] = 'catalog_feature'
    item['air_date'] = None
    item['season'] = None
    item['episode_number'] = None
    if media == 'tv':
        episode = details.get('next_episode_to_air') or {}
        try:
            released = date.fromisoformat(episode.get('air_date') or '')
            season, number = int(episode['season_number']), int(episode['episode_number'])
            if 0 <= (released - today).days <= 45 and season > 0 and number > 0:
                item.update(event_type='episode_date', air_date=released, season=season,
                            episode_number=number)
        except (KeyError, TypeError, ValueError):
            pass
    else:
        try:
            released = date.fromisoformat(details.get('release_date') if details else item.get('release_date') or '')
            if (released - today).days > 45:
                return None
            item.update(air_date=released,
                        event_type='announced' if released >= today else 'catalog_feature')
        except (TypeError, ValueError):
            pass
    return item
