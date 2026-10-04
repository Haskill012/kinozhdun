"""Сервис проверки обновлений сериалов и фильмов через TMDB API."""

import datetime
import logging
from typing import Any
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db.models import TrackedItem
from bot.db.repositories import Repository
from bot.services.tmdb import TMDBClient

logger = logging.getLogger(__name__)


class TrackerService:
    """Сервис для проверки выхода новых сезонов, дат премьер и статусов проектов."""

    def __init__(self, session_factory: async_sessionmaker, tmdb: TMDBClient):
        self.session_factory = session_factory
        self.tmdb = tmdb

    def evaluate_tv_update(self, item: TrackedItem, details: dict[str, Any]) -> dict[str, Any] | None:
        """Сравнивает текущие данные сериала в БД с информацией из TMDB."""
        if not details:
            return None

        today = datetime.date.today()
        next_ep = details.get("next_episode_to_air")
        tmdb_status = details.get("status")

        # 1. Проверяем появление или изменение даты следующего эпизода / сезона
        if next_ep and next_ep.get("air_date"):
            try:
                new_date = datetime.date.fromisoformat(next_ep["air_date"])
                new_season = next_ep.get("season_number")

                # Если даты раньше не было или она изменилась на будущую
                if item.next_air_date != new_date and new_date >= today:
                    return {
                        "type": "announced",
                        "next_season": new_season,
                        "next_air_date": new_date,
                        "status": "announced",
                        "source_url": details.get("tmdb_url"),
                    }
                # Если дата наступила
                elif new_date <= today and item.status != "released" and not item.notified_released:
                    return {
                        "type": "released",
                        "next_season": new_season,
                        "next_air_date": new_date,
                        "status": "released",
                        "source_url": details.get("tmdb_url"),
                    }
            except (ValueError, TypeError):
                pass

        # 2. Проверяем появление нового сезона в массиве сезонов
        seasons = details.get("seasons", [])
        if seasons:
            for s in reversed(seasons):
                s_num = s.get("season_number", 0)
                if s_num == 0:
                    continue  # Пропускаем спецвыпуски
                s_air_date_str = s.get("air_date")
                if s_air_date_str:
                    try:
                        s_air_date = datetime.date.fromisoformat(s_air_date_str)
                        if (item.last_known_season and s_num > item.last_known_season) or (item.next_air_date != s_air_date):
                            if s_air_date >= today and item.next_air_date != s_air_date:
                                return {
                                    "type": "announced",
                                    "next_season": s_num,
                                    "next_air_date": s_air_date,
                                    "status": "announced",
                                    "source_url": details.get("tmdb_url"),
                                }
                    except (ValueError, TypeError):
                        pass

        # 3. Изменение статуса сериала (закрыт, отменен)
        if tmdb_status in ("Ended", "Canceled") and item.status not in ("Ended", "Canceled"):
            return {
                "type": "status_change",
                "next_season": None,
                "next_air_date": None,
                "status": tmdb_status,
                "source_url": details.get("tmdb_url"),
            }

        return None

    def evaluate_movie_update(self, item: TrackedItem, details: dict[str, Any]) -> dict[str, Any] | None:
        """Сравнивает текущие данные фильма в БД с информацией из TMDB."""
        if not details:
            return None

        today = datetime.date.today()
        rel_str = details.get("release_date")
        if not rel_str:
            return None

        try:
            rel_date = datetime.date.fromisoformat(rel_str)
            # Если появилась новая дата в будущем
            if rel_date >= today and item.next_air_date != rel_date:
                return {
                    "type": "announced",
                    "next_season": None,
                    "next_air_date": rel_date,
                    "status": "announced",
                    "source_url": details.get("tmdb_url"),
                }
            # Если фильм уже вышел, а уведомление не отправлялось
            elif rel_date <= today and item.status != "released" and not item.notified_released:
                return {
                    "type": "released",
                    "next_season": None,
                    "next_air_date": rel_date,
                    "status": "released",
                    "source_url": details.get("tmdb_url"),
                }
        except (ValueError, TypeError):
            pass

        return None

    async def check_all_updates(self) -> list[dict[str, Any]]:
        """Проверяет обновления для всех отслеживаемых элементов в БД.

        Запросы к TMDB кэшируются по (media_type, tmdb_id), чтобы не дублировать запросы
        для сериалов/фильмов, которые отслеживают несколько пользователей.
        """
        notifications: list[dict[str, Any]] = []

        try:
            async with self.session_factory() as session:
                repo = Repository(session)
                items = await repo.get_all_waiting_items()

                if not items:
                    return []

                # Кэш результатов запросов к TMDB за один цикл проверки
                tmdb_cache: dict[tuple[str, int], dict[str, Any]] = {}

                for item in items:
                    cache_key = (item.media_type, item.tmdb_id)
                    if cache_key not in tmdb_cache:
                        if item.media_type == "tv":
                            tmdb_cache[cache_key] = await self.tmdb.get_tv_details(item.tmdb_id)
                        else:
                            tmdb_cache[cache_key] = await self.tmdb.get_movie_details(item.tmdb_id)

                    details = tmdb_cache.get(cache_key) or {}

                    update_info = None
                    if item.media_type == "tv":
                        update_info = self.evaluate_tv_update(item, details)
                    else:
                        update_info = self.evaluate_movie_update(item, details)

                    if update_info:
                        update_type = update_info["type"]
                        # Проверяем, не отправляли ли уже уведомление
                        already_notified = False
                        if update_type == "announced" and item.notified_announced:
                            already_notified = True
                        elif update_type == "released" and item.notified_released:
                            already_notified = True

                        # Обновляем поля сущности в БД
                        if update_info.get("next_air_date"):
                            item.next_air_date = update_info["next_air_date"]
                        if update_info.get("next_season"):
                            item.next_season_number = update_info["next_season"]
                        if update_info.get("status"):
                            item.status = update_info["status"]

                        item.updated_at = datetime.datetime.utcnow()

                        if not already_notified and item.user:
                            notifications.append({
                                "telegram_id": item.user.telegram_id,
                                "item": item,
                                "type": update_type,
                                "info": update_info,
                            })

                await session.commit()

        except Exception as e:
            logger.error(f"Ошибка при периодической проверке обновлений: {e}", exc_info=True)

        return notifications
