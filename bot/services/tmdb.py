import asyncio
import logging
from typing import Optional, Any
import aiohttp

logger = logging.getLogger(__name__)


class TMDBClient:
    """Асинхронный клиент для работы с API The Movie Database (TMDB)."""

    def __init__(self, api_key: str, base_url: str = "https://api.themoviedb.org/3"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(headers=self._get_headers())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Закрывает сессию aiohttp."""
        if self._session:
            await self._session.close()
            self._session = None

    def _get_headers(self) -> dict[str, str]:
        """Формирует заголовки запроса в зависимости от типа ключа TMDB."""
        if len(self.api_key) > 50 or self.api_key.startswith("eyJ"):
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Вспомогательный метод для выполнения GET запросов."""
        if not self._session:
            self._session = aiohttp.ClientSession(headers=self._get_headers())

        url = f"{self.base_url}{endpoint}"

        default_params: dict[str, Any] = {"language": "ru-RU"}
        # Если ключ короткий (стандартный v3 ключ из 32 символов), передаем через query параметр
        if len(self.api_key) <= 50 and not self.api_key.startswith("eyJ"):
            default_params["api_key"] = self.api_key

        if params:
            default_params.update(params)

        try:
            async with self._session.get(url, params=default_params) as response:
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            logger.error(f"Ошибка при запросе к TMDB {url}: {e}")
            return {}

    async def _fetch_network_info(self, media_type: str, tmdb_id: int) -> tuple[str, Optional[int]]:
        """Получает название телеканала/платформы/кинокомпании и количество сезонов."""
        try:
            endpoint = f"/tv/{tmdb_id}" if media_type == "tv" else f"/movie/{tmdb_id}"
            details = await self._get(endpoint)
            if not details:
                return "", None

            company = ""
            if media_type == "tv":
                networks = details.get("networks", [])
                if networks and isinstance(networks, list) and networks[0].get("name"):
                    company = networks[0]["name"]
                elif details.get("production_companies"):
                    comps = details["production_companies"]
                    if comps and isinstance(comps, list) and comps[0].get("name"):
                        company = comps[0]["name"]
                seasons = details.get("number_of_seasons")
                return company, seasons
            else:
                comps = details.get("production_companies", [])
                if comps and isinstance(comps, list) and comps[0].get("name"):
                    company = comps[0]["name"]
                return company, None
        except Exception:
            return "", None

    async def search_multi(self, query: str) -> list[dict[str, Any]]:
        """Ищет фильмы и сериалы по запросу, обогащая их информацией о компании/платформе."""
        data = await self._get("/search/multi", {"query": query, "page": 1})
        raw_results = data.get("results", [])

        # Фильтруем только tv и movie, берем топ-5
        filtered: list[dict[str, Any]] = []
        for item in raw_results:
            media_type = item.get("media_type")
            if media_type not in ("tv", "movie"):
                continue

            filtered.append({
                "tmdb_id": item.get("id"),
                "media_type": media_type,
                "title": item.get("title") if media_type == "movie" else item.get("name"),
                "original_title": item.get("original_title") if media_type == "movie" else item.get("original_name"),
                "overview": item.get("overview") or "",
                "poster_path": item.get("poster_path"),
                "release_date": item.get("release_date") if media_type == "movie" else item.get("first_air_date"),
                "vote_average": item.get("vote_average") or 0.0,
                "network": "",
                "number_of_seasons": None,
            })

            if len(filtered) >= 5:
                break

        if not filtered:
            return []

        # Параллельно запрашиваем компанию/платформу для каждого из результатов
        tasks = [
            self._fetch_network_info(item["media_type"], item["tmdb_id"])
            for item in filtered
        ]
        network_infos = await asyncio.gather(*tasks, return_exceptions=True)

        for item, info in zip(filtered, network_infos):
            if isinstance(info, tuple):
                company, seasons = info
                item["network"] = company
                item["number_of_seasons"] = seasons

        return filtered

    async def get_tv_details(self, tv_id: int) -> dict[str, Any]:
        """Получает детальную информацию о сериале."""
        data = await self._get(f"/tv/{tv_id}")
        if not data:
            return {}

        network = ""
        networks = data.get("networks", [])
        if networks and isinstance(networks, list) and networks[0].get("name"):
            network = networks[0]["name"]
        elif data.get("production_companies"):
            comps = data["production_companies"]
            if comps and isinstance(comps, list) and comps[0].get("name"):
                network = comps[0]["name"]

        return {
            "tmdb_id": data.get("id"),
            "title": data.get("name"),
            "original_title": data.get("original_name"),
            "overview": data.get("overview"),
            "poster_path": data.get("poster_path"),
            "status": data.get("status"),
            "number_of_seasons": data.get("number_of_seasons"),
            "seasons": data.get("seasons", []),
            "next_episode_to_air": data.get("next_episode_to_air"),
            "last_episode_to_air": data.get("last_episode_to_air"),
            "first_air_date": data.get("first_air_date"),
            "network": network,
            "tmdb_url": f"https://www.themoviedb.org/tv/{tv_id}",
        }

    async def get_tv_season(self, tv_id: int, season_number: int) -> dict[str, Any]:
        """Получает информацию о конкретном сезоне сериала."""
        data = await self._get(f"/tv/{tv_id}/season/{season_number}")
        if not data:
            return {}

        return {
            "season_number": data.get("season_number"),
            "air_date": data.get("air_date"),
            "episode_count": len(data.get("episodes", [])),
            "name": data.get("name"),
            "overview": data.get("overview"),
        }

    async def get_movie_details(self, movie_id: int) -> dict[str, Any]:
        """Получает детальную информацию о фильме."""
        data = await self._get(f"/movie/{movie_id}")
        if not data:
            return {}

        network = ""
        comps = data.get("production_companies", [])
        if comps and isinstance(comps, list) and comps[0].get("name"):
            network = comps[0]["name"]

        return {
            "tmdb_id": data.get("id"),
            "title": data.get("title"),
            "original_title": data.get("original_title"),
            "overview": data.get("overview"),
            "poster_path": data.get("poster_path"),
            "status": data.get("status"),
            "release_date": data.get("release_date"),
            "network": network,
            "belongs_to_collection": data.get("belongs_to_collection"),
            "tmdb_url": f"https://www.themoviedb.org/movie/{movie_id}",
        }

    async def get_collection(self, collection_id: int) -> dict[str, Any]:
        """Получает информацию о коллекции фильмов."""
        data = await self._get(f"/collection/{collection_id}")
        if not data:
            return {}

        return {
            "name": data.get("name"),
            "parts": data.get("parts", []),
        }

    async def get_videos(self, media_type: str, tmdb_id: int) -> list[dict[str, Any]]:
        """Получает список видеороликов (трейлеры, тизеры) для фильма или сериала."""
        endpoint = f"/{media_type}/{tmdb_id}/videos"
        # Сначала пробуем на русском
        data_ru = await self._get(endpoint, {"language": "ru-RU"})
        results = data_ru.get("results", [])

        # Если на русском трейлеров нет, запрашиваем оригинальные (en-US / all)
        if not results:
            data_en = await self._get(endpoint, {"language": "en-US"})
            results = data_en.get("results", [])

        return results

    async def get_official_trailer(self, media_type: str, tmdb_id: int) -> Optional[dict[str, str]]:
        """Ищет официальный YouTube-трейлер проекта.
        
        Возвращает словарь с url и title либо None.
        """
        videos = await self.get_videos(media_type, tmdb_id)
        if not videos:
            return None

        # Ищем строго официальный трейлер на YouTube
        for v in videos:
            if v.get("site") == "YouTube" and v.get("type") == "Trailer" and v.get("official") is True:
                key = v.get("key")
                if key:
                    return {
                        "url": f"https://www.youtube.com/watch?v={key}",
                        "name": v.get("name", "Официальный трейлер"),
                        "key": key,
                    }

        # Если официального флага нет, берем первый Trailer на YouTube
        for v in videos:
            if v.get("site") == "YouTube" and v.get("type") == "Trailer":
                key = v.get("key")
                if key:
                    return {
                        "url": f"https://www.youtube.com/watch?v={key}",
                        "name": v.get("name", "Трейлер"),
                        "key": key,
                    }

        return None

    async def get_upcoming_movies(self, page: int = 1) -> list[dict[str, Any]]:
        """Получает список предстоящих релизов фильмов из TMDB."""
        data = await self._get("/movie/upcoming", {"page": page})
        return data.get("results", [])

    async def get_airing_today_tv(self, page: int = 1) -> list[dict[str, Any]]:
        """Получает сериалы с новыми эпизодами сегодня из TMDB."""
        data = await self._get("/tv/airing_today", {"page": page})
        return data.get("results", [])

