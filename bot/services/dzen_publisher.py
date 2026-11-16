"""Human-readable Dzen copy and truthful delivery tracking."""
import datetime
from typing import Optional
from bot.services.social_editorial import clean_text, event_copy
from bot.services.dzen_delivery import DzenPublisher

GENRE_TAG_MAP = {"боевик":"боевики", "комедия":"комедии", "триллер":"триллеры", "детектив":"детективы"}

def build_dzen_hashtags(media_type=None, genres=None, extra_tags=None):
    tags = ["кино", "сериалы" if media_type == "tv" else "фильмы", "кинождун"]
    for value in list(genres or [])[:1] + list(extra_tags or []):
        value = value.strip().lower().lstrip("#")
        value = GENRE_TAG_MAP.get(value, value.replace(" ", "").replace("-", ""))
        if value and value not in tags:
            tags.append(value)
    return " ".join("#" + tag for tag in tags[:4])


def format_dzen_post_text(title, media_type="movie", event_type="announced",
                          season_number=None, air_date=None, network=None, overview=None,
                          genres=None, old_air_date=None, trailer_url=None,
                          site_url="https://kinojdun.ru", bot_username="kinojdun_bot", tmdb_id=None,
                          episode_number=None, source_url=None):
    paragraphs, past = event_copy(title, media_type, event_type, season_number,
                                  episode_number, air_date, network, overview, old_air_date,
                                  trailer_url, genres, tmdb_id, source_url)
    link = (f"{site_url.rstrip('/')}/title/{media_type}/{tmdb_id}" if tmdb_id
            else site_url.rstrip('/') + "/calendar")
    action = "Карточка и список просмотра" if past or event_type == "catalog_feature" else "Дата выхода и напоминания"
    paragraphs.append(f"{action}: {link}")
    # One useful destination; no repeated external promotion or generic tag carpet.
    return "\n\n".join(paragraphs)


def _format_digest(items, label, weekly, site_url):
    lines = [f"{'Главные премьеры недели' if weekly else 'Фильмы и новые серии сегодня'} — {label}"]
    for index, item in enumerate(items[:5], 1):
        title = clean_text(item.get("title"), 160)
        detail = [item.get("date_str") if weekly else None, item.get("tag"), item.get("network")]
        body = f"{index}. «{title}»\n" + " · ".join(clean_text(v, 80) for v in detail if v)
        if item.get("overview"):
            body += "\n" + clean_text(item["overview"], 240)
        if item.get("tmdb_id"):
            body += f"\nИсточник: https://www.themoviedb.org/{item.get('media_type', 'movie')}/{item['tmdb_id']}"
        lines.append(body)
    lines.append(f"Расписание и карточки проектов: {site_url.rstrip('/')}/calendar")
    return "\n\n".join(lines)


def format_dzen_daily_digest(items, date_label, site_url="https://kinojdun.ru", bot_username="kinojdun_bot"):
    return _format_digest(items, date_label, False, site_url)


def format_dzen_weekly_digest(items, range_label, site_url="https://kinojdun.ru", bot_username="kinojdun_bot"):
    return _format_digest(items, range_label, True, site_url)
