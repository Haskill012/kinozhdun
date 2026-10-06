"""Season premieres are dates of first episodes, never weekly episode dates."""
from datetime import date


def season_premieres(details):
    seasons = {}
    for season in details.get("seasons") or []:
        number = season.get("season_number") or 0
        try:
            air_date = date.fromisoformat(season.get("air_date"))
        except (ValueError, TypeError):
            continue
        if number > 0:
            seasons[number] = air_date
    for field in ("last_episode_to_air", "next_episode_to_air"):
        episode = details.get(field) or {}
        number = episode.get("season_number") or 0
        if number > 0 and episode.get("episode_number") == 1:
            try:
                seasons[number] = date.fromisoformat(episode.get("air_date"))
            except (ValueError, TypeError):
                pass
    if not seasons:
        try:
            seasons[1] = date.fromisoformat(details.get("first_air_date"))
        except (ValueError, TypeError):
            pass
    return sorted(seasons.items())


def upcoming_season(details, today=None):
    today = today or date.today()
    return next(((number, air_date) for number, air_date in season_premieres(details)
                 if air_date >= today), (None, None))
