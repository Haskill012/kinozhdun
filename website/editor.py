"""Source-grounded publication. No invented release dates or LLM dependency."""
import asyncio
import logging
import re
from datetime import date, datetime, timezone, timedelta

import aiohttp

logger = logging.getLogger(__name__)


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


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

    def process(self, media, detail):
        if detail.get("adult") or not detail.get("id"):
            return
        title = detail.get("title") or detail.get("name")
        if not title:
            return
        key = f"{media}:{detail['id']}"
        previous = self.store.snapshot(key)
        episode = detail.get("next_episode_to_air") or {}
        release = valid_date(detail.get("release_date") if media == "movie" else episode.get("air_date"))
        if media == "tv" and not release and not previous:
            # First-air date is not the date of a new season/episode.
            first = valid_date(detail.get("first_air_date"))
            if first and first >= today().isoformat():
                release = first
        videos = detail.get("videos", {}).get("results", [])
        trailers = sorted([v for v in videos if v.get("official") and v.get("site") == "YouTube" and v.get("type") == "Trailer"], key=lambda v: v.get("published_at", ""))
        trailer = trailers[-1].get("key") if trailers else None
        if trailer and not re.fullmatch(r"[\w-]{6,32}", trailer):
            trailer = None
        poster = detail.get("backdrop_path") or detail.get("poster_path")
        item = {"key": key, "id": detail["id"], "media_type": media, "title": title,
                "overview": detail.get("overview", ""), "release_date": release,
                "image": "https://image.tmdb.org/t/p/w1280" + poster if poster else None,
                "poster": "https://image.tmdb.org/t/p/w500" + detail["poster_path"] if detail.get("poster_path") else None,
                "season": episode.get("season_number"), "episode": episode.get("episode_number"),
                "status": detail.get("status"), "trailer": trailer,
                "source_url": f"https://www.themoviedb.org/{media}/{detail['id']}"}
        category = "movies" if media == "movie" else "series"
        kind = "фильма" if media == "movie" else "сериала"
        context = ""
        if media == "tv" and item["season"] and item["episode"]:
            context = f" Речь о {item['episode']}-м эпизоде {item['season']}-го сезона."

        def post(event, heading, summary, paragraphs):
            self.store.publish(f"tmdb:{key}:{event}", heading, category, summary,
                               paragraphs, item["source_url"], item["image"], media, detail["id"], release)

        if release and release >= today().isoformat() and (previous or release != today().isoformat()) and (not previous or previous.get("release_date") != release):
            old = previous.get("release_date") if previous else None
            heading = f"«{title}»: дата выхода — {date_ru(release)}" if not old else f"«{title}»: дата выхода изменилась"
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
                               item['source_url'], item['image'], media, detail['id'], previous['release_date'])
        if release == today().isoformat():
            post("release:" + release, f"«{title}»: выход по календарю сегодня", f"По данным TMDB, выход {kind} указан на {date_ru(release)}.{context}",
                 [f"В каталоге TMDB указана сегодняшняя дата выхода.{context}", "Доступность в кинотеатрах и онлайн-сервисах зависит от региона. Проверяйте сведения у распространителя."])
        if previous and item["status"] != previous.get("status") and item["status"]:
            labels = {"Canceled": "закрыт", "Ended": "завершён", "In Production": "в производстве", "Post Production": "на постпродакшне", "Released": "вышел", "Returning Series": "продолжается", "Planned": "запланирован"}
            status = labels.get(item["status"], item["status"])
            post("status:" + item["status"], f"«{title}»: изменился статус проекта", f"Текущий статус в TMDB: {status}.",
                 [f"При автоматической проверке обнаружено изменение статуса: {status}.", "Изменение статуса в каталоге не означает анонс нового сезона. Для подтверждения деталей проверяйте страницу проекта и сообщения создателей."])
        if trailer and previous and previous.get("trailer") != trailer:
            post("trailer:" + trailer, f"«{title}»: новый трейлер в каталоге TMDB", "В записи проекта появился трейлер с отметкой official.",
                 ["В каталоге TMDB появился новый ролик типа Trailer с отметкой official.", f"Смотреть: https://www.youtube.com/watch?v={trailer}"])
        # Preserve only current or future titles in the upcoming calendar
        if release and release >= today().isoformat():
            self.store.save_title(key, item)
        elif release and release < today().isoformat():
            self.store.delete_title(key)

    async def sync(self):
        if self.lock.locked():
            return
        async with self.lock:
            self.store.import_channel(self.config["bot_database"], self.config["channel_url"])
            if not self.config["api_key"]:
                self.store.state("sync_error", "Не задан TMDB_API_KEY. Новости канала доступны; обновление каталога ожидает ключ.")
                return
            errors = []
            try:
                connector = aiohttp.TCPConnector()
                async with aiohttp.ClientSession(connector=connector, trust_env=True, timeout=aiohttp.ClientTimeout(total=20)) as session:
                    self.session = session
                    candidates = []
                    for media, endpoint in (("movie", "/movie/upcoming"), ("tv", "/tv/on_the_air"), ("tv", "/tv/popular")):
                        try:
                            data = await self.fetch(endpoint)
                            candidates.extend((media, r["id"]) for r in data.get("results", [])[:self.config["batch_size"]] if not r.get("adult"))
                        except Exception as exc:
                            errors.append(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
                    # Upcoming may include films whose primary release already passed.
                    # Discover explicitly supplies genuinely future international dates.
                    try:
                        movies = await self.fetch("/discover/movie", **{
                            "primary_release_date.gte": today().isoformat(),
                            "primary_release_date.lte": (today() + timedelta(days=120)).isoformat(),
                            "include_adult": "false", "include_video": "false", "sort_by": "popularity.desc"})
                        candidates.extend(("movie", r['id']) for r in movies.get('results', [])[:self.config['batch_size']] if not r.get('adult'))
                    except Exception as exc:
                        errors.append(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
                    try:
                        series = await self.fetch("/discover/tv", **{
                            "first_air_date.gte": today().isoformat(),
                            "first_air_date.lte": (today() + timedelta(days=120)).isoformat(),
                            "include_adult": "false", "sort_by": "popularity.desc"})
                        candidates.extend(("tv", r['id']) for r in series.get('results', [])[:self.config['batch_size']] if not r.get('adult'))
                    except Exception as exc:
                        errors.append(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
                    candidates.extend((t["media_type"], t["id"]) for t in self.store.titles())
                    # Bounded refresh; rotate entries if the catalogue grows.
                    unique = list(dict.fromkeys(candidates))
                    cursor = int(self.store.state("refresh_cursor") or 0) % max(1, len(unique))
                    ordered = unique[cursor:] + unique[:cursor]
                    for media, tmdb_id in ordered[:150]:
                        try:
                            detail = await self.fetch(f"/{media}/{tmdb_id}", append_to_response="videos")
                            self.process(media, detail)
                        except Exception as exc:
                            errors.append(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
                    self.store.state("refresh_cursor", str((cursor + 150) % max(1, len(unique))))
                    if not errors:
                        self.store.state("last_sync", datetime.now(timezone.utc).isoformat())
                    self.store.state("sync_error", "; ".join(sorted(set(errors))) if errors else "")
            except Exception as exc:
                self.store.state("sync_error", f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
            finally:
                self.session = None
            logger.info("Website sync finished: %s titles; %s errors", len(self.store.titles()), len(errors))

    async def run(self):
        while True:
            await self.sync()
            await asyncio.sleep(self.config["sync_seconds"])
