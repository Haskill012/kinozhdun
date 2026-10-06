"""Source names plus a small set of user-specified Russian aliases."""
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
