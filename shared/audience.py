"""Editorial selection for a Russian audience, separate from explicit user searches."""
import re

ASIAN_COUNTRIES = {'CN', 'JP', 'KR', 'KP', 'TW', 'HK', 'MO', 'IN', 'BD', 'PK', 'LK', 'NP', 'BT',
                   'TH', 'VN', 'ID', 'MY', 'PH', 'SG', 'KH', 'LA', 'MM', 'MN'}
ASIAN_LANGUAGES = {'zh', 'cn', 'ja', 'ko', 'hi', 'ta', 'te', 'ml', 'kn', 'bn', 'mr', 'pa', 'ur',
                   'si', 'ne', 'th', 'vi', 'id', 'ms', 'tl', 'km', 'lo', 'my', 'mn'}
EXCLUDED_GENRES = {10763, 10764, 10767}
EXCLUDED_NAMES = {'ток-шоу', 'ток шоу', 'реалити-шоу', 'реалити', 'новости',
                  'talk', 'talk show', 'reality', 'news'}
_NON_LATIN_CYRILLIC_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\u0600-\u06ff\u0e00-\u0e7f\u0900-\u097f]')


def is_readable_title(title: str | None) -> bool:
    """Проверяет, что заголовок читается кириллицей/латиницей без иероглифов и вязи."""
    text = (title or '').strip()
    if not text:
        return False
    if _NON_LATIN_CYRILLIC_RE.search(text):
        return False
    return bool(re.search(r'[А-Яа-яЁёA-Za-z]', text))


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
    title_val = item.get('title') or item.get('name') or ''
    if title_val and not is_readable_title(title_val):
        return 'unreadable-title'
    genres = item.get('genres') or []
    ids = set(item.get('genre_ids') or []) | {g.get('id') for g in genres if isinstance(g, dict)}
    labels = {str(g.get('name', '') if isinstance(g, dict) else g).casefold() for g in genres}
    if item.get('media_type') == 'tv' and (item.get('series_type', item.get('type')) in
            ('Reality', 'Talk Show', 'News', 'Video') or ids & EXCLUDED_GENRES or labels & EXCLUDED_NAMES):
        return 'nonfiction-format'
    countries = set(item.get('origin_country') or [])
    if 'RU' in countries or item.get('original_language') == 'ru':
        return None
    if item.get('key') in config.get('audience_allow_keys', ()) or item.get('ru_release'):
        return None
    popularity = float(item.get('popularity') or 0)
    votes = int(item.get('votes', item.get('vote_count')) or 0)
    rating = float(item.get('rating', item.get('vote_average')) or 0)
    localized = bool(re.search('[А-Яа-яЁё]', title_val)) and bool(re.search('[А-Яа-яЁё]', item.get('overview') or ''))

    if countries & ASIAN_COUNTRIES or item.get('original_language') in ASIAN_LANGUAGES:
        # International English-language co-productions are not local Asian releases.
        if item.get('original_language') == 'en' and countries & {'US', 'GB', 'CA', 'AU', 'NZ', 'IE'}:
            return None if (popularity >= 8 or votes >= 30) else 'low-interest'
        threshold = config.get('asian_min_popularity', 20)
        if item.get('ru_official_trailer') and popularity >= threshold:
            return None
        # Established anime can have fewer votes than live-action global hits.
        animation = 16 in ids or bool(labels & {'мультфильм', 'animation'})
        if localized and animation and popularity >= max(threshold, 50) and votes >= 250 and rating >= 8:
            return None
        if localized and popularity >= threshold and votes >= config.get('asian_min_votes', 1000) and rating >= 7:
            return None
        return 'asian-local'

    # Прочие региональные релизы (не RU и не англоязычные): пропускаем только при русской локализации и заметном интересе.
    is_english = item.get('original_language') == 'en' and (not countries or bool(countries & {'US', 'GB', 'CA', 'AU', 'NZ', 'IE'}) or popularity >= 15)
    if not is_english:
        if item.get('ru_official_trailer') and popularity >= 12:
            return None
        if not (localized and (popularity >= 15 or votes >= 200)):
            return 'regional-local'
    elif popularity < 8 and votes < 30 and not item.get('ru_official_trailer'):
        return 'low-interest'
    return None


def audience_items(items, config=None):
    return [item for item in items if not exclusion_reason(item, config)]
