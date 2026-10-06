"""Find tomorrow's episodes without changing season premiere tracking."""
from datetime import date


def episode_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def episodes_on_date(tmdb, tmdb_id, details, target):
    episodes = {}

    def add(episode):
        season = episode.get("season_number")
        number = episode.get("episode_number")
        if (isinstance(season, int) and season > 0
                and isinstance(number, int) and number > 0
                and episode_date(episode.get("air_date")) == target):
            episodes[(season, number)] = episode

    next_episode = details.get("next_episode_to_air") or {}
    add(next_episode)
    # The next episode can still be today's episode. Read its season schedule
    # too, so daily series and simultaneous episode releases are covered.
    seasons = {ep["season_number"] for ep in
               (next_episode, details.get("last_episode_to_air") or {})
               if isinstance(ep.get("season_number"), int) and ep["season_number"] > 0}
    dated_seasons = [(s.get("season_number"), episode_date(s.get("air_date")))
                     for s in details.get("seasons") or []]
    active = [n for n, d in dated_seasons if isinstance(n, int) and n > 0 and d and d <= target]
    if active:
        seasons.add(max(active))
    for season in sorted(seasons):
        schedule = await tmdb.get_tv_season(tmdb_id, season)
        for episode in schedule.get("episodes") or []:
            add({**episode, "season_number": season})
    return [episodes[key] for key in sorted(episodes)]
