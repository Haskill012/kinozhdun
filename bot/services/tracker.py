"""Сервис проверки обновлений сериалов и фильмов через TMDB API."""

import datetime
import logging
from typing import Any
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db.models import TrackedItem
from bot.db.repositories import Repository
from bot.services.tmdb import TMDBClient
from bot.services.season_dates import upcoming_season, season_premieres

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
        season, premiere = upcoming_season(details, today)
        next_ep = {"air_date": premiere.isoformat(), "season_number": season} if premiere else None
        tmdb_status = details.get("status")

        # 1. Проверяем появление или изменение даты премьеры сезона
        if next_ep and next_ep.get("air_date"):
            try:
                new_date = datetime.date.fromisoformat(next_ep["air_date"])
                new_season = next_ep.get("season_number")

                # Если даты раньше не было или она изменилась на будущую
                if item.next_air_date != new_date and new_date >= today:
                    is_postponed = (item.next_air_date is not None and new_date > item.next_air_date
                                    and item.next_season_number == new_season)
                    channel_event = "date_postponed" if is_postponed else "date_announced"
                    return {
                        "type": "announced",
                        "channel_event_type": channel_event,
                        "next_season": new_season,
                        "next_air_date": new_date,
                        "old_air_date": item.next_air_date,
                        "status": "announced",
                        "source_url": details.get("tmdb_url"),
                    }
                # Если дата наступила
                elif new_date <= today and item.status != "released" and not item.notified_released:
                    return {
                        "type": "released",
                        "channel_event_type": "released",
                        "next_season": new_season,
                        "next_air_date": new_date,
                        "status": "released",
                        "source_url": details.get("tmdb_url"),
                    }
            except (ValueError, TypeError):
                pass

        # Confirm a tracked premiere from season data even after TMDB advances the episode.
        for number, premiered in season_premieres(details):
            if (premiered <= today and item.next_air_date == premiered
                    and item.status != "released" and not item.notified_released):
                return {"type": "released", "channel_event_type": "released",
                        "next_season": number, "next_air_date": premiered,
                        "status": "released", "source_url": details.get("tmdb_url")}

        # 3. Изменение статуса сериала (съёмки, закрыт, продлён)
        if tmdb_status and tmdb_status != item.status:
            channel_event = "status_change"
            if tmdb_status == "In Production":
                channel_event = "filming_started"
            elif tmdb_status == "Post Production":
                channel_event = "filming_finished"
            elif tmdb_status == "Returning Series":
                channel_event = "renewed"
            elif tmdb_status == "Canceled":
                channel_event = "canceled"
            elif tmdb_status == "Ended":
                channel_event = "ended"

            if channel_event != "status_change" or tmdb_status in ("Ended", "Canceled", "Returning Series"):
                return {
                    "type": "status_change",
                    "channel_event_type": channel_event,
                    "next_season": item.next_season_number,
                    "next_air_date": item.next_air_date,
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
        tmdb_status = details.get("status")

        if rel_str:
            try:
                rel_date = datetime.date.fromisoformat(rel_str)
                # Если появилась новая дата в будущем
                if rel_date >= today and item.next_air_date != rel_date:
                    is_postponed = item.next_air_date is not None and rel_date > item.next_air_date
                    channel_event = "date_postponed" if is_postponed else "date_announced"
                    return {
                        "type": "announced",
                        "channel_event_type": channel_event,
                        "next_season": None,
                        "next_air_date": rel_date,
                        "old_air_date": item.next_air_date,
                        "status": "announced",
                        "source_url": details.get("tmdb_url"),
                    }
                # Если фильм уже вышел, а уведомление не отправлялось
                elif rel_date <= today and item.status != "released" and not item.notified_released:
                    return {
                        "type": "released",
                        "channel_event_type": "released",
                        "next_season": None,
                        "next_air_date": rel_date,
                        "status": "released",
                        "source_url": details.get("tmdb_url"),
                    }
            except (ValueError, TypeError):
                pass

        if tmdb_status and tmdb_status != item.status:
            channel_event = "status_change"
            if tmdb_status == "In Production":
                channel_event = "filming_started"
            elif tmdb_status == "Post Production":
                channel_event = "filming_finished"
            elif tmdb_status == "Canceled":
                channel_event = "canceled"

            if channel_event != "status_change":
                return {
                    "type": "status_change",
                    "channel_event_type": channel_event,
                    "next_season": None,
                    "next_air_date": item.next_air_date,
                    "status": tmdb_status,
                    "source_url": details.get("tmdb_url"),
                }

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
                    if item.media_type == "tv" and details:
                        valid_premieres = {d for _, d in season_premieres(details)}
                        if item.next_air_date and item.next_air_date not in valid_premieres:
                            item.next_season_number, item.next_air_date = upcoming_season(details)
                            item.notified_announced = False
                            item.notified_released = False
                            item.notified_reminder = False
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
