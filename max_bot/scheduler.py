"""Фоновые периодические задачи планировщика для бота в MAX Messenger."""

import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.db.repositories import Repository
from bot.services.episode_reminders import episodes_on_date
from bot.services.tmdb import TMDBClient
from bot.services.tracker import TrackerService
from bot.utils.formatting import (
    format_announced_notification,
    format_episode_tomorrow_notification,
    format_released_notification,
    format_reminder_notification,
    format_status_change_notification,
)
from max_bot.client import MaxBotClient
from max_bot.config import MaxBotSettings
from max_bot.keyboards import item_details_keyboard

logger = logging.getLogger(__name__)


def moscow_now():
    """Текущее время по Москве."""
    return datetime.datetime.now(ZoneInfo("Europe/Moscow"))


async def check_updates_job(
    client: MaxBotClient,
    session_factory: Any,
    tmdb_client: TMDBClient,
    settings: MaxBotSettings,
) -> None:
    """Проверка появления дат выхода новых сезонов и релизов."""
    logger.info("[MAX] Запуск фоновой проверки обновлений по каталогу TMDB...")
    try:
        tracker = TrackerService(session_factory, tmdb_client)
        updates = await tracker.check_all_updates()
        if not updates:
            logger.info("[MAX] Фоновая проверка завершена, новых релизов не найдено.")
            return

        logger.info("[MAX] Найдено %d обновлений, отправка подписчикам...", len(updates))
        async with session_factory() as session:
            repo = Repository(session)
            for upd in updates:
                user_id = upd.get("telegram_id")
                item = upd.get("item")
                upd_type = upd.get("type")
                info = upd.get("info", {})

                if not user_id or not item:
                    continue

                if upd_type == "announced":
                    text = format_announced_notification(item, info)
                elif upd_type == "released":
                    text = format_released_notification(item)
                elif upd_type == "status_change":
                    text = format_status_change_notification(item, info)
                else:
                    continue

                keyboard = item_details_keyboard(item, site_url=settings.SITE_BASE_URL)
                try:
                    await client.send_message(
                        user_id=user_id,
                        text=text,
                        attachments=keyboard,
                    )
                    await repo.log_notification(item.id, upd_type, text)
                    await session.commit()
                except Exception as e:
                    logger.warning("[MAX] Не удалось отправить уведомление пользователю %s: %s", user_id, e)

    except Exception:
        logger.exception("[MAX] Ошибка при проверке обновлений TMDB.")


async def check_reminders_job(
    client: MaxBotClient,
    session_factory: Any,
    settings: MaxBotSettings,
) -> None:
    """Напоминания за 3 дня до даты премьеры."""
    logger.info("[MAX] Запуск проверки напоминаний о премьерах...")
    try:
        async with session_factory() as session:
            repo = Repository(session)
            items = await repo.get_items_for_reminder()
            for item in items:
                if not item.user or not item.user.telegram_id:
                    continue

                text = format_reminder_notification(item)
                keyboard = item_details_keyboard(item, site_url=settings.SITE_BASE_URL)
                try:
                    await client.send_message(
                        user_id=item.user.telegram_id,
                        text=text,
                        attachments=keyboard,
                    )
                    await repo.mark_notified(item.id, "reminder")
                    await repo.log_notification(item.id, "reminder", text)
                    await session.commit()
                except Exception as e:
                    logger.warning("[MAX] Ошибка отправки напоминания пользователю %s: %s", item.user.telegram_id, e)
    except Exception:
        logger.exception("[MAX] Ошибка при проверке напоминаний о премьерах.")


async def check_episode_reminders_job(
    client: MaxBotClient,
    session_factory: Any,
    tmdb_client: TMDBClient,
    settings: MaxBotSettings,
) -> None:
    """Напоминания о новых сериях за 1 день до выхода."""
    now = moscow_now()
    if not (10 <= now.hour < 22):
        return

    target_date = now.date() + datetime.timedelta(days=1)
    try:
        async with session_factory() as session:
            repo = Repository(session)
            series_list = await repo.get_tracked_series()
            cache: dict[int, list[dict]] = {}

            for item in series_list:
                if not item.user or not item.user.telegram_id:
                    continue

                if item.tmdb_id not in cache:
                    details = await tmdb_client.get_tv_details(item.tmdb_id)
                    cache[item.tmdb_id] = (
                        await episodes_on_date(tmdb_client, item.tmdb_id, details, target_date)
                        if details else []
                    )

                unnotified = []
                for ep in cache[item.tmdb_id]:
                    event_key = f"episode_tomorrow:{ep['season_number']}:{ep['episode_number']}:{target_date.isoformat()}"
                    if not await repo.has_notification(item.id, event_key):
                        unnotified.append(ep)

                if not unnotified:
                    continue

                text = format_episode_tomorrow_notification(item, unnotified)
                keyboard = item_details_keyboard(item, site_url=settings.SITE_BASE_URL)
                try:
                    await client.send_message(
                        user_id=item.user.telegram_id,
                        text=text,
                        attachments=keyboard,
                    )
                    for ep in unnotified:
                        event_key = f"episode_tomorrow:{ep['season_number']}:{ep['episode_number']}:{target_date.isoformat()}"
                        await repo.log_notification(item.id, event_key, text)
                    await session.commit()
                except Exception as e:
                    logger.warning("[MAX] Ошибка отправки напоминания о серии: %s", e)

    except Exception:
        logger.exception("[MAX] Ошибка проверки напоминаний о новых сериях.")


def setup_scheduler(
    client: MaxBotClient,
    session_factory: Any,
    tmdb_client: TMDBClient,
    settings: MaxBotSettings,
) -> AsyncIOScheduler:
    """Инициализация и запуск фонового планировщика задач."""
    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Moscow"))

    # Проверка обновлений в TMDB каждые N часов
    scheduler.add_job(
        check_updates_job,
        trigger="interval",
        hours=settings.CHECK_INTERVAL_HOURS,
        args=[client, session_factory, tmdb_client, settings],
        id="max_check_updates",
        name="Проверка обновлений TMDB для MAX",
    )

    # Напоминания за 3 дня до премьеры — каждый день в 11:00
    scheduler.add_job(
        check_reminders_job,
        trigger="cron",
        hour=11,
        minute=0,
        args=[client, session_factory, settings],
        id="max_check_reminders",
        name="Напоминания о премьерах для MAX",
    )

    # Напоминания о выходе новой серии завтра — каждый час с 10:00 до 21:00
    scheduler.add_job(
        check_episode_reminders_job,
        trigger="cron",
        hour="10-21",
        minute=15,
        args=[client, session_factory, tmdb_client, settings],
        id="max_check_episodes",
        name="Напоминания о сериях завтра для MAX",
    )

    return scheduler
