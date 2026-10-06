"""Source names plus a small set of user-specified Russian aliases."""
import re
KNOWN_NAMES = {
    "pluribus": ("Одна из многих", "Плюрибус", "Pluribus"),
    "trainspotting": ("На игле", "Трейнспоттинг", "Транспоттинг", "Trainspotting"),
}


def normalized(value):
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def names(item):
    values = [item.get("title"), item.get("original_title"), *(item.get("aliases") or [])]
    original = normalized(item.get("original_title"))
    values.extend(KNOWN_NAMES.get(original, ()))
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and v.strip()))


def canonical_title(title, original):
    return KNOWN_NAMES.get(normalized(original), (title,))[0]


def source_aliases(detail):
    data = detail.get("alternative_titles") or {}
    values = [v.get("title") for v in data.get("results", data.get("titles", []))]
    for translation in (detail.get("translations") or {}).get("translations", []):
        data = translation.get("data") or {}
        values.append(data.get("name") or data.get("title"))
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and v.strip()))


def remote_query(query):
    query = normalized(query)
    if len(query) >= 3:
        for original, aliases in KNOWN_NAMES.items():
            if any(query == normalized(alias) or normalized(alias).startswith(query) for alias in aliases):
                return original
    return query


def source_seo_aliases(detail):
    """Keep Russian published names with provenance, rather than every translation."""
    data = detail.get('alternative_titles') or {}
    values = [row.get('title') for row in data.get('results', data.get('titles', []))
              if row.get('iso_3166_1') == 'RU' and not re.search(r'working|рабоч', row.get('type') or '', re.I)]
    values.extend((row.get('data') or {}).get('title') or (row.get('data') or {}).get('name')
                  for row in (detail.get('translations') or {}).get('translations', [])
                  if row.get('iso_639_1') == 'ru')
    return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))


def seo_names(item):
    """A compact set shared by visible text and structured data."""
    original = item.get('original_title')
    values = [original, *KNOWN_NAMES.get(normalized(original), ()), *(item.get('seo_aliases') or [])]
    seen = {normalized(item.get('title'))}
    selected = []
    for value in values:
        if not isinstance(value, str):
            continue
        value = ' '.join(value.split())
        key = normalized(value)
        if not key or key in seen or len(value) > 100:
            continue
        # Extra translated aliases must use Russian letters; the original is retained.
        if key != normalized(original) and not re.search(r'[А-Яа-яЁё]', value):
            continue
        seen.add(key)
        selected.append(value)
        if len(selected) == 3:
            break
    return selected
