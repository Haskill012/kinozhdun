"""Home-page projections of saved catalogue facts; no synthetic audience counts."""
import re
from datetime import date, datetime, timezone, timedelta

from website.editor import today

MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
          'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')


def parsed_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def days_text(days):
    word = 'день' if days % 10 == 1 and days % 100 != 11 else 'дня' if days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14) else 'дней'
    return f'{days} {word}'


def event_state(item, current=None):
    current = current or today()
    release = parsed_date(item.get('release_date'))
    season, episode = item.get('season'), item.get('episode')
    premiere = parsed_date(item.get('season_premiere'))
    kind = 'Премьера фильма' if item['media_type'] == 'movie' else 'Новая серия' if episode else 'Выход сериала'
    if item['media_type'] == 'tv':
        if premiere and premiere >= current and (not release or release < current or premiere <= release):
            release, season, episode = premiere, item.get('premiere_season'), 1
        if episode == 1:
            kind = 'Новый сезон' if season and season > 1 else 'Премьера сериала'
    if not release:
        return dict(date=None, label='СТОИТ ДОЖДАТЬСЯ', headline='Дата выхода пока не объявлена', detail='', kind=kind)
    days = (release - current).days
    label = 'СЕГОДНЯ' if days == 0 else 'УЖЕ ЗАВТРА' if days == 1 else 'СКОРО ВЕРНЁТСЯ' if 0 < days <= 120 and episode == 1 and season and season > 1 else 'СКОРО ПРЕМЬЕРА' if 0 < days <= 120 and (item['media_type'] == 'movie' or episode == 1) else 'СТОИТ ДОЖДАТЬСЯ'
    headline = f'{kind} сегодня' if days == 0 else f'{kind} уже завтра' if days == 1 else f'{kind} через {days_text(days)}' if days > 0 else f'{kind} уже вышла · по календарю' if kind in ('Новая серия', 'Премьера фильма', 'Премьера сериала') else f'{kind} уже вышел · по календарю'
    detail = f'{release.day} {MONTHS[release.month - 1]}'
    if release.year != current.year or not episode:
        detail += f' {release.year}'
    if season and episode:
        detail += f' · {season} сезон, {episode} серия'
    return dict(date=release, label=label, headline=headline, detail=detail, kind=kind)


def waiting(item, current=None):
    current = current or today()
    event = event_state(item, current)['date']
    if event:
        return event >= current
    return item.get('status') in ('Returning Series', 'Planned', 'In Production', 'Post Production')


def watch_label(item):
    """A future authenticated adapter may supply confirmed per-user subscription state."""
    return '✓ Жду' if item.get('is_waiting') is True else '+ Ждать'


def hero_projects(items, events=(), limit=6):
    changed = {tuple(a.get(k) for k in ('media_type', 'tmdb_id')) for a in events}
    def score(item):
        event = event_state(item)['date']
        days = (event - today()).days if event else None
        popularity = max(0, float(item.get('popularity') or 0))
        # Popularity leads; reliable ratings and imminent events add bounded bonuses.
        import math
        return (math.log1p(popularity) * 12 +
                (float(item.get('rating') or 0) * 2 if item.get('votes', 0) >= 50 else 0) +
                (20 * (1 - days / 120) if days is not None and 0 <= days <= 120 else 0) +
                (5 if (item['media_type'], item['id']) in changed else 0))
    candidates = [i for i in items if waiting(i) or (event_state(i)['date'] and 0 <= (today() - event_state(i)['date']).days <= 7)]
    return sorted(candidates or items, key=lambda i: (-score(i), i['media_type'], i['id']))[:limit]


def change_type(article):
    match = re.match(r'^tmdb:(movie|tv):\d+:(date|date-removed|status|trailer|release):(.+)$', article.get('fingerprint', ''))
    if not match:
        return None
    event, value = match[2], match[3]
    if event == 'status':
        return {'Canceled': ('🔴', 'ЗАКРЫЛИ В TMDB'), 'Ended': ('◷', 'ЗАВЕРШЁН В TMDB')}.get(value, ('🟢', 'ИЗМЕНИЛСЯ СТАТУС'))
    if event == 'date':
        return ('📅', 'ИЗМЕНИЛИ ДАТУ' if 'изменилась' in article.get('title', '') else 'НАЗНАЧИЛИ ДАТУ')
    return {'date-removed': ('🟡', 'ДАТА УТОЧНЯЕТСЯ'), 'trailer': ('🎬', 'НОВЫЙ ТРЕЙЛЕР'), 'release': ('🍿', 'ВЫХОД ПО КАЛЕНДАРЮ')}[event]


def relative_time(value, current=None):
    current = current or datetime.now(timezone.utc)
    try:
        published = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not published.tzinfo:
            published = published.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return ''
    hours = int((current - published).total_seconds() // 3600)
    moscow = timezone(timedelta(hours=3))
    days = (current.astimezone(moscow).date() - published.astimezone(moscow).date()).days
    if days < 0 or hours < 0:
        return ''
    if hours == 0:
        return 'Только что'
    if days == 0:
        word = 'час' if hours % 10 == 1 and hours != 11 else 'часа' if hours % 10 in (2, 3, 4) and hours not in (12, 13, 14) else 'часов'
        return f'{hours} {word} назад'
    return 'Вчера' if days == 1 else f'{days_text(days)} назад' if days <= 7 else f'{published.day} {MONTHS[published.month - 1]} {published.year}'
