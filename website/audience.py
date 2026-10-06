"""Editorial selection for a Russian audience, separate from explicit user searches."""
import re

ASIAN_COUNTRIES = {'CN', 'JP', 'KR', 'KP', 'TW', 'HK', 'MO', 'IN', 'BD', 'PK', 'LK', 'NP', 'BT',
                   'TH', 'VN', 'ID', 'MY', 'PH', 'SG', 'KH', 'LA', 'MM', 'MN'}
ASIAN_LANGUAGES = {'zh', 'cn', 'ja', 'ko', 'hi', 'ta', 'te', 'ml', 'kn', 'bn', 'mr', 'pa', 'ur',
                   'si', 'ne', 'th', 'vi', 'id', 'ms', 'tl', 'km', 'lo', 'my', 'mn'}
EXCLUDED_GENRES = {10763, 10764, 10767, 10766}
EXCLUDED_NAMES = {'ток-шоу', 'ток шоу', 'реалити-шоу', 'реалити', 'новости', 'мыльная опера',
                  'talk', 'talk show', 'reality', 'news', 'soap'}


def audience_metadata(media, detail):
    countries = list(detail.get('origin_country') or [])
    if not countries:
        countries = [c['iso_3166_1'] for c in detail.get('production_countries') or [] if c.get('iso_3166_1')]
    releases = (detail.get('release_dates') or {}).get('results') or []
    ru_release = any(row.get('iso_3166_1') == 'RU' and
                     any(r.get('release_date') and r.get('type') in (2, 3, 4, 5, 6) for r in row.get('release_dates') or [])
                     for row in releases) if media == 'movie' else False
    videos = list((detail.get('videos') or {}).get('results') or [])
    for season in (detail.get('season_videos') or {}).values():
        videos.extend(season)
    ru_trailer = any(v.get('official') is True and v.get('type') == 'Trailer' and
                     v.get('iso_639_1') == 'ru' for v in videos)
    return dict(origin_country=countries, original_language=detail.get('original_language'),
                genre_ids=[g['id'] for g in detail.get('genres') or [] if isinstance(g, dict) and g.get('id')],
                series_type=detail.get('type'), ru_release=ru_release, ru_official_trailer=ru_trailer)


def exclusion_reason(item, config=None):
    config = config or {}
    genres = item.get('genres') or []
    ids = set(item.get('genre_ids') or []) | {g.get('id') for g in genres if isinstance(g, dict)}
    labels = {str(g.get('name', '') if isinstance(g, dict) else g).casefold() for g in genres}
    if item.get('media_type') == 'tv' and (item.get('series_type', item.get('type')) in
            ('Reality', 'Talk Show', 'News', 'Video', 'Soap') or ids & EXCLUDED_GENRES or labels & EXCLUDED_NAMES):
        return 'nonfiction-format'
    countries = set(item.get('origin_country') or [])
    if 'RU' in countries or item.get('original_language') == 'ru':
        return None
    if not (countries & ASIAN_COUNTRIES or item.get('original_language') in ASIAN_LANGUAGES):
        return None
    # Explicit editorial exceptions can preserve anticipated releases before they have votes.
    if item.get('key') in config.get('audience_allow_keys', ()) or item.get('ru_release'):
        return None
    popularity = float(item.get('popularity') or 0)
    threshold = config.get('asian_min_popularity', 20)
    if item.get('ru_official_trailer') and popularity >= threshold:
        return None
    localized = bool(re.search('[А-Яа-яЁё]', item.get('title') or item.get('name') or '')) and bool(re.search('[А-Яа-яЁё]', item.get('overview') or ''))
    votes = int(item.get('votes', item.get('vote_count')) or 0)
    rating = float(item.get('rating', item.get('vote_average')) or 0)
    if localized and popularity >= threshold and votes >= config.get('asian_min_votes', 1000) and rating >= 7:
        return None
    return 'asian-local'


def audience_items(items, config=None):
    return [item for item in items if not exclusion_reason(item, config)]


def audience_articles(store, config, *, category=None, query='', limit=24, offset=0):
    """Filter before pagination, while preserving individual article URLs and history."""
    selected, position = [], 0
    while len(selected) < offset + limit:
        batch = store.articles(category=category, query=query, limit=100, offset=position)
        for article in batch:
            item = store.catalog_item(f"{article.get('media_type')}:{article.get('tmdb_id')}", False) or {}
            if not exclusion_reason(item, config):
                selected.append(article)
        position += len(batch)
        if len(batch) < 100:
            break
    return selected[offset:offset + limit]
