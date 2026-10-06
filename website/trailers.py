"""Prefer the newest season with an official trailer before language preference."""
import re


def official_trailers(videos):
    return [v for v in videos if v.get("official") and v.get("site") == "YouTube"
            and v.get("type") == "Trailer"
            and re.fullmatch(r"[A-Za-z0-9_-]{6,32}", v.get("key") or "")]


def trailer_season(video):
    if video.get("season_number"):
        return video["season_number"]
    name = video.get("name") or ""
    match = re.search(r"(?:season|сезон)\s*(\d+)|(\d+)\s*(?:-?[а-я]+\s+)?сезон", name, re.I)
    return int(next(g for g in match.groups() if g)) if match else 0


def select_trailers(media, detail):
    videos = list(detail.get("videos", {}).get("results") or [])
    for season, results in (detail.get("season_videos") or {}).items():
        videos.extend({**v, "season_number": int(season)} for v in results)
    trailers = official_trailers(videos)
    # Keep one entry per video key, preserving explicit season endpoint metadata.
    by_key = {}
    for video in trailers:
        previous = by_key.get(video["key"])
        if not previous or trailer_season(video) >= trailer_season(previous):
            by_key[video["key"]] = video
    return sorted(by_key.values(), key=lambda v: (
        trailer_season(v) if media == "tv" else 0,
        v.get("iso_639_1") == "ru", v.get("published_at") or ""))
