"""Фоновые периодические задачи планировщика APScheduler."""

import logging
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.db.repositories import Repository
from bot.services.tmdb import TMDBClient
from bot.services.tracker import TrackerService
from bot.utils.formatting import (
    format_announced_notification,
    format_released_notification,
    format_reminder_notification,
)

logger = logging.getLogger(__name__)


async def check_updates_job(bot: Bot, session_factory, tmdb_client: TMDBClient) -> None:
    """Периодическая проверка появления дат выхода новых сезонов и релизов."""
    logger.info("Запуск фоновой проверки обновлений по каталогу TMDB...")
    try:
        tracker = TrackerService(session_factory, tmdb_client)
        updates = await tracker.check_all_updates()

        if not updates:
            logger.info("Проверка завершена. Новых анонсов и релизов не обнаружено.")
            return

        logger.info(f"Обнаружено {len(updates)} обновлений, отправляю уведомления...")

        async with session_factory() as session:
            repo = Repository(session)
            for update in updates:
                telegram_id = update.get("telegram_id")
                item = update.get("item")
                update_type = update.get("type")
                info = update.get("info", {})

                if not telegram_id or not item:
                    continue

                if update_type == "announced":
                    text = format_announced_notification(item, info)
                elif update_type == "released":
                    text = format_released_notification(item)
                elif update_type == "status_change":
                    text = (
                        f"ℹ️ <b>Статус проекта изменился!</b>\n\n"
                        f"<b>{item.title}</b> — текущий статус: <i>{info.get('status')}</i>\n"
                        f"🔗 <a href='{item.tmdb_url}'>TMDB</a>"
                    )
                else:
                    continue

                try:
                    await bot.send_message(telegram_id, text)
                    await repo.mark_notified(item.id, update_type)
                    await repo.log_notification(item.id, update_type, text)
                except Exception as send_err:
                    logger.warning(f"Не удалось отправить уведомление пользователю {telegram_id}: {send_err}")

            await session.commit()

        logger.info("Все уведомления успешно обработаны.")

    except Exception as e:
        logger.error(f"Ошибка при выполнении задачи check_updates_job: {e}", exc_info=True)


async def check_reminders_job(bot: Bot, session_factory) -> None:
    """Периодическая проверка приближающихся премьер (за 3 дня)."""
    logger.info("Запуск проверки приближающихся премьер (напоминания)...")
    try:
        async with session_factory() as session:
            repo = Repository(session)
            items_to_remind = await repo.get_items_for_reminder(days_before=3)

            if not items_to_remind:
                logger.info("Нет премьер, требующих напоминания за 3 дня.")
                return

            for item in items_to_remind:
                if item.user and item.user.telegram_id:
                    text = format_reminder_notification(item, days_left=3)
                    try:
                        await bot.send_message(item.user.telegram_id, text)
                        await repo.mark_notified(item.id, "reminder")
                        await repo.log_notification(item.id, "reminder", text)
                    except Exception as send_err:
                        logger.warning(
                            f"Не удалось отправить напоминание {item.user.telegram_id}: {send_err}"
                        )

            await session.commit()

        logger.info("Обработка напоминаний завершена.")

    except Exception as e:
        logger.error(f"Ошибка при выполнении задачи check_reminders_job: {e}", exc_info=True)


def setup_scheduler(
    bot: Bot, session_factory, tmdb_client: TMDBClient, settings: Settings
) -> AsyncIOScheduler:
    """Настройка и конфигурирование планировщика задач."""
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Основная проверка выхода новых сезонов / дат
    scheduler.add_job(
        check_updates_job,
        "interval",
        hours=settings.CHECK_INTERVAL_HOURS,
        kwargs={"bot": bot, "session_factory": session_factory, "tmdb_client": tmdb_client},
        id="check_tmdb_updates",
        replace_existing=True,
    )

    # Проверка напоминаний за 3 дня до даты премьеры (каждые 12 часов)
    scheduler.add_job(
        check_reminders_job,
        "interval",
        hours=12,
        kwargs={"bot": bot, "session_factory": session_factory},
        id="check_upcoming_reminders",
        replace_existing=True,
    )

    return scheduler
