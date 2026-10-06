"""Source-grounded publication. No invented release dates or LLM dependency."""
import asyncio
import logging
import re
from datetime import date, datetime, timezone, timedelta

import aiohttp
from bot.services.season_dates import season_premieres
from website.trailers import official_trailers, select_trailers, trailer_season
from website.title_names import canonical_title, source_aliases, source_seo_aliases
from website.artwork import artwork
from website.audience import audience_metadata, exclusion_reason

logger = logging.getLogger(__name__)


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


def error_text(exc):
    # Network exceptions may carry a request URL and its API key.
    return str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__


def valid_date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


def date_ru(value):
    value = valid_date(value)
    return date.fromisoformat(value).strftime("%d.%m.%Y") if value else "Дата пока не объявлена"


class Editor:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.lock = asyncio.Lock()
        self.session = None

    async def fetch(self, endpoint, **params):
        key = self.config["api_key"]
        headers = {"Authorization": "Bearer " + key} if len(key) > 50 or key.startswith("eyJ") else {}
        params = {"language": "ru-RU", **params}
        if not headers:
            params["api_key"] = key
        # Exceptions intentionally never log request URLs containing credentials.
        for attempt in range(3):
            async with self.session.get(self.config["api_base"] + endpoint, params=params, headers=headers) as response:
                if response.status in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(1 + attempt * 2)
                    continue
                if response.status != 200:
                    raise RuntimeError(f"TMDB вернул HTTP {response.status}")
                return await response.json()

    async def fetch_details(self, media, tmdb_id):
        append = "videos,alternative_titles,translations" + (",release_dates" if media == 'movie' else '')
        detail = await self.fetch(f"/{media}/{tmdb_id}", append_to_response=append, include_video_language="ru,en,null")
        if detail.get("id") != tmdb_id:
            raise RuntimeError("TMDB вернул другой идентификатор проекта")
        if media == "tv":
            detail["season_videos"] = {}
            seasons = sorted({s["season_number"] for s in detail.get("seasons") or []
                              if isinstance(s.get("season_number"), int) and s["season_number"] > 0}, reverse=True)
            for number in seasons:
                videos = await self.fetch(f"/tv/{tmdb_id}/season/{number}/videos", include_video_language="ru,en,null")
                results = videos.get("results") or []
                detail["season_videos"][number] = results
                if official_trailers(results):
                    break
        return detail

    def eligible(self, media, detail, require_recent=True):
        if exclusion_reason({**detail, **audience_metadata(media, detail), 'media_type': media, 'key': f"{media}:{detail.get('id')}"}, self.config):
            return False
        if detail.get("adult") or not detail.get("poster_path") or not detail.get("overview"):
            return False
        if media == "tv" and (detail.get("type") in ("Reality", "Talk Show", "News", "Video") or any(g.get("id") in (10763, 10764, 10767, 10766) for g in detail.get("genres", []))):
            return False
        popularity = float(detail.get("popularity") or 0)
        votes = int(detail.get("vote_count") or 0)
        rating = float(detail.get("vote_average") or 0)
        if votes >= self.config.get("min_votes", 50) and rating < self.config.get("min_rating", 6):
            return False
        if popularity < self.config.get("min_popularity", 5):
            return False
        if not require_recent:
            return True
        first = valid_date(detail.get("release_date") if media == "movie" else detail.get("first_air_date"))
        next_air = valid_date((detail.get("next_episode_to_air") or {}).get("air_date"))
        lower = (today() - timedelta(days=180)).isoformat()
        upper = (today() + timedelta(days=365)).isoformat()
        return bool((first and lower <= first <= upper) or
                    (media == "tv" and next_air and today().isoformat() <= next_air <= upper))

    def process(self, media, detail, *, emit_news=True, publish_card=False):
        if detail.get("adult") or not detail.get("id"):
            return
        title = detail.get("title") or detail.get("name")
        if not title:
            return
        title = canonical_title(title, detail.get("original_title") or detail.get("original_name"))
        key = f"{media}:{detail['id']}"
        existing = self.store.catalog_item(key, False) or {}
        bot_linked = publish_card or existing.get("bot_linked", False)
        news_related = self.store.has_news_title(media, detail["id"])
        metadata = audience_metadata(media, detail)
        blocked = exclusion_reason({**detail, **metadata, 'media_type': media, 'key': key}, self.config)
        if not blocked and not news_related and not bot_linked and "popularity" in detail and not self.eligible(media, detail, require_recent=False):
            self.store.db.execute("DELETE FROM catalog WHERE key=?", (key,))
            self.store.delete_title(key)
            return
        previous = self.store.snapshot(key)
        episode = detail.get("next_episode_to_air") or {}
        release = valid_date(detail.get("release_date") if media == "movie" else episode.get("air_date"))
        if media == "tv" and not release:
            # First-air date is not the date of a new season/episode.
            first = valid_date(detail.get("first_air_date"))
            if first and first >= today().isoformat():
                release = first
        trailers = select_trailers(media, detail)
        trailer = trailers[-1].get("key") if trailers else None
        if trailer and not re.fullmatch(r"[\w-]{6,32}", trailer):
            trailer = None
        poster_path, backdrop_path = artwork(media, detail)
        poster = backdrop_path or poster_path
        item = {"key": key, "id": detail["id"], "media_type": media, "title": title,
                "original_title": detail.get("original_title") or detail.get("original_name"),
                "aliases": source_aliases(detail),
                "seo_aliases": source_seo_aliases(detail),
                "overview": detail.get("overview", ""), "release_date": release,
                "image": "https://image.tmdb.org/t/p/w1280" + poster if poster else None,
                "poster": "https://image.tmdb.org/t/p/w500" + poster_path if poster_path else None,
                "season": episode.get("season_number"), "episode": episode.get("episode_number"),
                "status": detail.get("status"), "trailer": trailer,
                "trailer_keys": [v["key"] for v in trailers if re.fullmatch(r"[A-Za-z0-9_-]{6,32}", v.get("key", ""))],
                "trailer_languages": {v["key"]: v.get("iso_639_1") for v in trailers},
                "trailer_language": trailers[-1].get("iso_639_1", "en") if trailer else None,
                "trailer_season": (trailer_season(trailers[-1]) or None) if trailer and media == "tv" else None,
                "season_trailers_loaded": media == "tv" and "season_videos" in detail,
                "rating": detail.get("vote_average"), "votes": detail.get("vote_count", 0),
                "popularity": detail.get("popularity", 0),
                "first_release": valid_date(detail.get("release_date") if media == "movie" else detail.get("first_air_date")),
                "genres": [g["name"] for g in detail.get("genres", [])],
                "source_url": f"https://www.themoviedb.org/{media}/{detail['id']}"}
        item.update(metadata)
        if media == "tv":
            premieres = season_premieres(detail)
            if premieres:
                number, premiered = premieres[-1]
                item["season_premiere"] = premiered.isoformat()
                item["premiere_season"] = number
        if bot_linked:
            item["bot_linked"] = True
        if news_related or publish_card:
            self.store.ensure_news_card(media, detail["id"], title, item["source_url"], item=item)
        self.store.update_catalog(item)
        if blocked:
            # Keep old URLs, snapshots and explicitly opened cards; suppress automatic news.
            self.store.save_title(key, item)
            return
        if not emit_news:
            self.store.save_title(key, item)
            return
        if self.config.get("catalog_size") and not self.store.catalog_item(key):
            self.store.save_title(key, item)
            return
        category = "movies" if media == "movie" else "series"
        kind = "фильма" if media == "movie" else "сериала"
        context = ""
        if media == "tv" and item["season"] and item["episode"]:
            context = f" Речь о {item['episode']}-м эпизоде {item['season']}-го сезона."

        def post(event, heading, summary, paragraphs):
            self.store.publish(f"tmdb:{key}:{event}", heading, category, summary,
                               paragraphs, item["source_url"], item["image"], media, detail["id"], release, item=item)

        if release and release >= today().isoformat() and (previous or release != today().isoformat()) and (not previous or previous.get("release_date") != release):
            same_episode = (media != "tv" or not previous or
                            (previous.get("season"), previous.get("episode")) == (item["season"], item["episode"]))
            old = previous.get("release_date") if previous and same_episode else None
            heading = f"«{title}»: дата выхода — {date_ru(release)}" if not old else f"«{title}»: дата выхода изменилась"
            if media == "tv" and item["season"] and item["episode"]:
                subject = f"{item['season']}-й сезон, {item['episode']}-я серия"
                heading = f"«{title}»: {subject} — {date_ru(release)}" if not old else f"«{title}»: дата выхода {subject} изменилась"
            summary = f"В каталоге TMDB указана дата {date_ru(release)}.{context}"
            body = [summary]
            if old:
                body.append(f"Ранее в каталоге была указана дата {date_ru(old)}. При очередной проверке она изменилась на {date_ru(release)}.")
            if item["overview"]:
                body.append("О проекте: " + item["overview"])
            body.append("Дата относится к данным TMDB и может отличаться в зависимости от страны и способа релиза. Это запись каталога, а не гарантия доступности на конкретной платформе.")
            post("date:" + release, heading, summary, body)
        if previous and previous.get("release_date") and previous['release_date'] > today().isoformat() and not release:
            old = previous["release_date"]
            post("date-removed:" + old, f"«{title}»: дата следующего выхода уточняется", "В текущей записи TMDB больше нет прежней даты следующего выхода.",
                 [f"Ранее была указана дата {date_ru(old)}. Сейчас каталог не содержит даты следующего выхода; это само по себе не подтверждает отмену проекта."])
        if previous and previous.get("release_date") == today().isoformat() and release != today().isoformat():
            self.store.publish(f"tmdb:{key}:release:{previous['release_date']}", f"«{title}»: выход по календарю сегодня", category,
                               "Сегодняшняя дата выхода была указана в предыдущем снимке TMDB.",
                               [f"В предыдущем снимке каталога выход был указан на {date_ru(previous['release_date'])}.",
                                "Текущая запись уже изменилась. Проверяйте фактическую доступность у распространителя."],
                               item['source_url'], item['image'], media, detail['id'], previous['release_date'], item=item)
        if release == today().isoformat():
            post("release:" + release, f"«{title}»: выход по календарю сегодня", f"По данным TMDB, выход {'эпизода' if media == 'tv' and item['episode'] else kind} указан на {date_ru(release)}.{context}",
                 [f"В каталоге TMDB указана сегодняшняя дата выхода.{context}", "Доступность в кинотеатрах и онлайн-сервисах зависит от региона. Проверяйте сведения у распространителя."])
        if previous and item["status"] != previous.get("status") and item["status"]:
            labels = {"Canceled": "закрыт", "Ended": "завершён", "In Production": "в производстве", "Post Production": "на постпродакшне", "Released": "вышел", "Returning Series": "продолжается", "Planned": "запланирован"}
            status = labels.get(item["status"], item["status"])
            post("status:" + item["status"], f"«{title}»: изменился статус проекта", f"Текущий статус в TMDB: {status}.",
                 [f"При автоматической проверке обнаружено изменение статуса: {status}.", "Изменение статуса в каталоге не означает анонс нового сезона. Для подтверждения деталей проверяйте страницу проекта и сообщения создателей."])
        old_keys = (previous.get("trailer_keys", [previous.get("trailer")]) if previous else [])
        if previous and item["season_trailers_loaded"] and not previous.get("season_trailers_loaded"):
            # Initial season metadata backfill is not a newly published trailer.
            old_keys = item["trailer_keys"]
        for new_key in item["trailer_keys"]:
            if not previous or new_key in old_keys:
                continue
            post("trailer:" + new_key, f"«{title}»: новый трейлер в каталоге TMDB", "В записи проекта появился трейлер с отметкой official.",
                 ["В каталоге TMDB появился новый ролик типа Trailer с отметкой official.", f"Смотреть: https://www.youtube.com/watch?v={new_key}"])
        self.store.save_title(key, item)

    async def open_title(self, media, tmdb_id):
        """Resolve a bot link without requiring selection in the discovery catalogue."""
        key = f"{media}:{tmdb_id}"
        visible = self.store.catalog_item(key)
        if visible:
            return visible
        saved = self.store.snapshot(key) or self.store.catalog_item(key, False)
        if saved and saved.get("source_url"):
            saved = {**saved, "bot_linked": True}
            if "first_release" not in saved:
                saved["needs_details"] = True
            self.store.ensure_news_card(media, tmdb_id, saved["title"], saved.get("source_url") or
                                       f"https://www.themoviedb.org/{media}/{tmdb_id}", item=saved)
            self.store.db.commit()
            return self.store.catalog_item(key)
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=20)) as session:
            self.session = session
            try:
                detail = await self.fetch_details(media, tmdb_id)
            finally:
                self.session = None
        self.process(media, detail, emit_news=False, publish_card=True)
        return self.store.catalog_item(key)

    async def sync(self):
        if self.lock.locked():
            return
        async with self.lock:
            self.store.import_channel(self.config["bot_database"], self.config["channel_url"])
            self.store.restore_news_cards()
            if not self.config["api_key"]:
                self.store.state("sync_error", "Не задан TMDB_API_KEY. Новости канала доступны; обновление каталога ожидает ключ.")
                return
            errors = []
            try:
                connector = aiohttp.TCPConnector()
                async with aiohttp.ClientSession(connector=connector, trust_env=True, timeout=aiohttp.ClientTimeout(total=20)) as session:
                    self.session = session
                    details = {}
                    replenish = bool(self.store.state("initial_catalog_visible"))
                    discovery_due = not self.store.state("catalog_selected") or (replenish and self.store.state("catalog_discovery_day") != today().isoformat())
                    # Date-bounded discovery prevents old evergreen hits dominating the queue.
                    for media in (("movie", "tv") if discovery_due else ()):
                        date_field = "primary_release_date" if media == "movie" else "first_air_date"
                        for page in range(1, 5):
                            try:
                                data = await self.fetch(f"/discover/{media}", **{
                                    date_field + ".gte": (today()-timedelta(days=180)).isoformat(),
                                    date_field + ".lte": (today()+timedelta(days=365)).isoformat(),
                                    "include_adult": "false", "sort_by": "popularity.desc", "page": page,
                                    **({"without_genres": "10763,10764,10767,10766"} if media == 'tv' else {})})
                                for row in data.get("results", []):
                                    if not row.get("adult") and float(row.get("popularity") or 0) >= self.config.get("min_popularity", 5) and (int(row.get("vote_count") or 0) < self.config.get("min_votes", 50) or float(row.get("vote_average") or 0) >= self.config.get("min_rating", 6)):
                                        details.setdefault((media, row["id"]), None)
                            except Exception as exc:
                                errors.append(error_text(exc))
                    # Continuing series are selected by their next episode, not first season.
                    try:
                        data = await self.fetch("/tv/on_the_air") if discovery_due else {}
                        for row in data.get("results", []):
                            details.setdefault(("tv", row["id"]), None)
                    except Exception as exc:
                        errors.append(error_text(exc))
                    news_titles = set(self.store.news_titles())
                    for media, tmdb_id in news_titles:
                        details.setdefault((media, tmdb_id), None)
                    for item in self.store.catalog(False):
                        details.setdefault((item["media_type"], item["id"]), None)
                    for media, tmdb_id in details:
                        try:
                            detail = await self.fetch_details(media, tmdb_id)
                            details[(media, tmdb_id)] = detail
                        except Exception as exc:
                            errors.append(error_text(exc))
                    # Complete cards imported from news before selecting the discovery queue.
                    # Backfilling metadata must not generate historical date/trailer news.
                    for (media, tmdb_id), detail in details.items():
                        card = self.store.catalog_item(f"{media}:{tmdb_id}")
                        if detail and (media, tmdb_id) in news_titles and (not card or card.get("needs_details")):
                            self.process(media, detail, emit_news=False)
                    size = self.config.get("catalog_size", 50)
                    if not self.store.state("catalog_selected"):
                        selected = []
                        for media in ("movie", "tv"):
                            pool = [d for (m, _), d in details.items() if m == media and d and self.eligible(m, d)]
                            pool.sort(key=lambda d: float(d.get("popularity") or 0), reverse=True)
                            selected.append([(media, d) for d in pool[:size//2]])
                        # Alternate movies and series in the daily publication queue.
                        ordered = [entry for pair in zip(*selected) for entry in pair]
                        ordered += selected[0][len(selected[1]):] + selected[1][len(selected[0]):]
                        for media, detail in ordered:
                            self.store.queue_title({"key": f"{media}:{detail['id']}", "id": detail["id"], "media_type": media, "title": detail.get("title") or detail.get("name")})
                        if len(ordered) >= size:
                            self.store.state("catalog_selected", datetime.now(timezone.utc).isoformat())
                    if replenish and discovery_due:
                        pending = len(self.store.catalog(False)) - len(self.store.catalog())
                        pool = [(m, d) for (m, ident), d in details.items() if d and self.eligible(m, d) and not self.store.catalog_item(f"{m}:{ident}", False)]
                        pool.sort(key=lambda entry: float(entry[1].get("popularity") or 0), reverse=True)
                        for media, detail in pool[:min(6, max(0, 12-pending))]:
                            self.store.queue_title({"key": f"{media}:{detail['id']}", "id": detail["id"], "media_type": media, "title": detail.get("title") or detail.get("name")})
                        if not errors:
                            self.store.state("catalog_discovery_day", today().isoformat())
                    # Refresh hidden cards too; they must stay current until publication.
                    for (media, tmdb_id), detail in details.items():
                        if detail and self.store.catalog_item(f"{media}:{tmdb_id}", False) and not self.store.catalog_item(f"{media}:{tmdb_id}"):
                            self.process(media, detail)
                    self.store.release_catalog(self.config.get("daily_cards", 3))
                    # Published entries now receive normal date/trailer event monitoring.
                    for (media, tmdb_id), detail in details.items():
                        if detail and self.store.catalog_item(f"{media}:{tmdb_id}"):
                            self.process(media, detail)
                    if not errors:
                        self.store.state("last_sync", datetime.now(timezone.utc).isoformat())
                    self.store.state("sync_error", "; ".join(sorted(set(errors))) if errors else "")
            except Exception as exc:
                self.store.state("sync_error", error_text(exc))
            finally:
                self.session = None
            logger.info("Website sync finished: %s titles; %s errors", len(self.store.titles()), len(errors))

    async def run(self):
        while True:
            await self.sync()
            await asyncio.sleep(self.config["sync_seconds"])
