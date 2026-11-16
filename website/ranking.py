"""Current-interest ranking and daily hero rotation from saved, verifiable facts."""
import json
import math
from datetime import date, datetime, timedelta, timezone

MOSCOW = timezone(timedelta(hours=3))


def today():
    return datetime.now(MOSCOW).date()


def parsed(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def number(value):
    try:
        result = float(value or 0)
        return max(0, result) if math.isfinite(result) else 0
    except (TypeError, ValueError):
        return 0


def season_dates(item):
    values = [parsed(item.get('season_premiere'))]
    values.extend(parsed(s.get('air_date')) for s in item.get('seasons') or []
                  if number(s.get('season_number')) > 0)
    # An episode-one date can stand in for a missing season premiere.
    if item.get('episode') == 1:
        values.append(parsed(item.get('release_date')))
    return [value for value in values if value]


def relevant_date(item, current=None):
    """Use a season premiere, never each weekly episode as a fresh series launch."""
    current = current or today()
    first = parsed(item.get('first_release'))
    if item.get('media_type') == 'movie':
        return first or parsed(item.get('release_date'))
    dates = season_dates(item) + ([first] if first else [])
    past = [value for value in dates if value <= current]
    imminent = [value for value in dates if current < value <= current + timedelta(days=120)]
    # A just-announced season should not erase a recently released season.
    return min(imminent) if imminent else max(past, default=None) or min(dates, default=None)


def long_running(item):
    if item.get('media_type') != 'tv':
        return False
    seasons = [number(item.get('season')), number(item.get('premiere_season'))]
    seasons.extend(number(s.get('season_number')) for s in item.get('seasons') or [])
    return max(seasons, default=0) >= 12


def load_trends(store, current=None):
    current = current or today()
    try:
        data = json.loads(store.state('ranking_trends') or '{}')
        day = parsed(data.get('day'))
        age = (current - day).days if day else 99
        scores = data.get('scores') or {}
        if not 0 <= age <= 3 or not isinstance(scores, dict):
            return {}
        return {key: number(value) * .6 ** age for key, value in scores.items()}
    except (ValueError, TypeError, AttributeError):
        return {}


def quality_score(item):
    votes = number(item.get('votes'))
    if votes < 50:
        return 0
    # A 10/10 from 50 people must not beat a well-established 8/10.
    return (number(item.get('rating')) * votes + 6.5 * 250) / (votes + 250)


def interest_score(item, trends=None, current=None):
    current = current or today()
    popularity = 28 * math.log1p(min(number(item.get('popularity')), 1000)) / math.log1p(1000)
    when = relevant_date(item, current)
    freshness = 0
    if when:
        days = (current - when).days
        if days >= 0:
            freshness = 38 * math.exp(-days / (240 if item.get('media_type') == 'movie' else 180))
        elif days >= -180:
            freshness = 32 * math.exp(days / 180)
        elif days >= -365:
            freshness = 8 * math.exp((days + 180) / 180)
    votes = number(item.get('votes'))
    confidence = votes / (votes + 500)
    freshness *= .7 + .3 * confidence
    trend = min(60, number((trends or {}).get(item.get('key') or f"{item.get('media_type')}:{item.get('id')}"))) * .4
    trend *= .5 + .5 * confidence
    trust = max(0, quality_score(item) - 5) * 2
    evidence = 28 * math.log1p(min(votes, 10000)) / math.log1p(10000)
    # Very long series gain no premiere boost from simply returning every year.
    if long_running(item):
        freshness *= .25
        popularity *= .65
    return popularity + freshness + trend + trust + evidence


def ranked(items, trends=None, current=None):
    current = current or today()
    return sorted(items, key=lambda item: (-interest_score(item, trends, current),
                                           item.get('media_type', ''), item.get('id', 0)))


def topical(item, trends=None, current=None):
    current = current or today()
    if long_running(item):
        return False
    when = relevant_date(item, current)
    days = (current - when).days if when else None
    fresh = days is not None and -180 <= days <= (365 if item.get('media_type') == 'movie' else 270)
    return fresh or number((trends or {}).get(item.get('key'))) >= 15


def hero_selection(items, events=(), limit=6, trends=None, current=None):
    current = current or today()
    if limit <= 0:
        return []
    unique = {(item.get('media_type'), item.get('id')): item for item in items}
    items = list(unique.values())
    candidates = [item for item in items if topical(item, trends, current)]
    # Small/test catalogues still have a useful hero; a full library uses current titles only.
    candidates = candidates or [item for item in items if not long_running(item)] or items
    complete = [item for item in candidates if item.get('image') or item.get('poster')]
    if len(complete) >= limit:
        candidates = complete
    changed = set()
    for event in events:
        published = parsed((event.get('published') or '')[:10])
        if published and 0 <= (current - published).days <= 7:
            changed.add((event.get('media_type'), event.get('tmdb_id')))
    def score(item):
        return interest_score(item, trends, current) + (4 if (item.get('media_type'), item.get('id')) in changed else 0)
    ordered = sorted(candidates, key=lambda item: (-score(item), item.get('media_type', ''), item.get('id', 0)))
    if len(ordered) <= limit:
        return ordered
    established = [item for item in ordered if number(item.get('votes')) >= 1000]
    anchor_count = min(3, limit)
    movie_count = sum(item.get('media_type') == 'movie' for item in ordered)
    anchors = []
    for item in established if len(established) >= anchor_count else ordered:
        if item.get('media_type') == 'tv' and sum(i.get('media_type') == 'tv' for i in anchors) >= 2 and movie_count >= limit - 2:
            continue
        anchors.append(item)
        if len(anchors) == anchor_count:
            break
    floor = score(ordered[0]) * .55
    pool = [item for item in ordered[:18] if item not in anchors and score(item) >= floor]
    offset = (current.toordinal() * 3) % len(pool) if pool else 0
    rotating = pool[offset:] + pool[:offset]
    selected = list(anchors)
    for item in rotating + ordered:
        if len(selected) >= limit:
            break
        if item in selected:
            continue
        if item.get('media_type') == 'tv' and sum(i.get('media_type') == 'tv' for i in selected) >= 2 and movie_count >= limit - 2:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    # Rotate positions daily too, retaining leaders with substantial audience evidence.
    shift = current.toordinal() % len(selected) if selected else 0
    return selected[shift:] + selected[:shift]


async def refresh_trends(editor, *, force=False):
    """Refresh short-window signals before the slower full catalogue metadata sync."""
    now = datetime.now(timezone.utc)
    try:
        saved = json.loads(editor.store.state('ranking_trends') or '{}')
        updated = datetime.fromisoformat(saved.get('updated_at', ''))
        if not force and updated.tzinfo and timedelta(0) <= now - updated < timedelta(hours=3):
            return False
    except (ValueError, TypeError, AttributeError):
        pass
    scores, positions = {}, {}
    for window, weight in (('day', 35), ('week', 25)):
        data = await editor.fetch('/trending/all/' + window)
        rows = [row for row in data.get('results') or []
                if row.get('media_type') in ('movie', 'tv') and isinstance(row.get('id'), int) and not row.get('adult')]
        if not rows:
            raise RuntimeError('TMDB: пустой список трендов ' + window)
        for rank, row in enumerate(rows, 1):
            key = f"{row['media_type']}:{row['id']}"
            scores[key] = scores.get(key, 0) + weight * (1 - (rank - 1) / len(rows))
            positions.setdefault(key, {})[window] = rank
            # Trending lists carry a fresh popularity value without a full detail request.
            item = editor.store.catalog_item(key, False)
            if item and row.get('popularity') is not None:
                item.pop('published', None)
                item['popularity'] = row['popularity']
                editor.store.update_catalog(item)
    editor.store.state('ranking_trends', json.dumps({'day': now.astimezone(MOSCOW).date().isoformat(),
                                                    'updated_at': now.isoformat(), 'scores': scores,
                                                    'positions': positions}))
    editor.store.state('ranking_trends_error', '')
    return True
