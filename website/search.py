"""Fast search over published project cards, including original titles."""
def normalize(value):
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def matches(item, query):
    query = normalize(query)
    return any(query in normalize(item.get(field)) for field in ("title", "original_title"))


def suggestions(store, query, limit=8):
    query = normalize(query[:100])
    if len(query) < 2:
        return []
    found = [item for item in store.catalog() if matches(item, query)]
    def rank(item):
        names = [normalize(item.get(field)) for field in ("title", "original_title")]
        return (not any(name == query for name in names),
                not any(name.startswith(query) for name in names),
                -float(item.get("popularity") or 0), item["title"])
    found.sort(key=rank)
    return [{"title": item["title"], "url": f"/title/{item['media_type']}/{item['id']}",
             "media_type": item["media_type"], "year": (item.get("first_release") or "")[:4],
             "rating": item.get("rating") if item.get("votes", 0) > 0 else None,
             "poster": item.get("poster")} for item in found[:limit]]
