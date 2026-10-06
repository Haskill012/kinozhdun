"""Search source names and aliases, with a cached TMDB fallback."""
import asyncio
import time
from difflib import SequenceMatcher
import aiohttp
from website.title_names import normalized as normalize, names, canonical_title, remote_query
from website.artwork import artwork, allowed_asset


def matches(item, query):
    query = normalize(query)
    for name in names(item):
        name = normalize(name)
        if query in name:
            return True
        if len(query) >= 5 and abs(len(query) - len(name)) <= 3 and SequenceMatcher(None, query, name).ratio() >= .84:
            return True
    return False


def rank(item, query):
    labels = [normalize(name) for name in names(item)]
    return (not any(name == query for name in labels),
            not any(name.startswith(query) for name in labels),
            not any(query in name for name in labels),
            -float(item.get("popularity") or 0), item["title"])


def result(item):
    return {"title": item["title"], "url": f"/title/{item['media_type']}/{item['id']}",
            "media_type": item["media_type"], "year": (item.get("first_release") or "")[:4],
            "rating": item.get("rating") if item.get("votes", 0) >= 50 else None,
            "poster": item.get("poster") if allowed_asset(item.get("poster")) else None,
            "alternate_title": item.get("original_title")}


def suggestions(store, query, limit=8):
    query = normalize(query[:100])
    if len(query) < 2:
        return []
    found = [item for item in store.catalog() if matches(item, query)]
    found.sort(key=lambda item: rank(item, query))
    return [result(item) for item in found[:limit]]


class ProjectSearch:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.cache = {}
        self.lock = asyncio.Lock()

    async def projects(self, query):
        query = normalize(query[:100])
        if len(query) < 2:
            return []
        published = self.store.catalog()
        local = [item for item in published if matches(item, query)]
        if not self.config.get("api_key") or any(query == normalize(name) for item in local for name in names(item)):
            return sorted(local, key=lambda item: rank(item, query))[:8]
        # One external search at a time; identical overlapping requests share cache.
        async with self.lock:
            key = remote_query(query)
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                remote = cached[1]
            else:
                remote = await self.fetch_remote(key)
                if len(self.cache) >= 128:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[key] = (time.monotonic() + 600, remote)
        merged = {(item["media_type"], item["id"]): item for item in remote}
        for item in published:
            identity = (item["media_type"], item["id"])
            if identity in merged:
                merged[identity] = {**item, "remote_match": True}
        merged.update({(item["media_type"], item["id"]): item for item in local})
        return sorted(merged.values(), key=lambda item: rank(item, query))[:8]

    async def fetch_remote(self, query):
        from website.editor import Editor
        editor = Editor(self.store, self.config)
        try:
            async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=5)) as session:
                editor.session = session
                response = await editor.fetch("/search/multi", query=query, include_adult="false")
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
            return []
        found = []
        for row in response.get("results", []):
            media = row.get("media_type")
            if media not in ("movie", "tv") or row.get("adult") or not row.get("id"):
                continue
            title = row.get("title") or row.get("name")
            original = row.get("original_title") or row.get("original_name")
            if not title:
                continue
            poster, _ = artwork(media, row)
            found.append({"key": f"{media}:{row['id']}", "id": row["id"], "media_type": media,
                          "title": canonical_title(title, original), "original_title": original,
                          "first_release": row.get("release_date") or row.get("first_air_date"),
                          "rating": row.get("vote_average"), "votes": row.get("vote_count", 0),
                          "popularity": row.get("popularity", 0), "genres": [], "remote_match": True,
                          "poster": "https://image.tmdb.org/t/p/w500" + poster if poster else None})
        return found
