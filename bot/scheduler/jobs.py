"""Фоновые периодические задачи планировщика APScheduler."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.db.repositories import Repository
from bot.services.channel import ChannelPublisher
from bot.services.tmdb import TMDBClient
from bot.services.tracker import TrackerService
from bot.keyboards.inline import notification_item_keyboard
from bot.utils.formatting import (
    format_announced_notification,
    format_released_notification,
    format_reminder_notification,
    format_status_change_notification,
)

logger = logging.getLogger(__name__)


async def check_updates_job(
    bot: Bot, session_factory, tmdb_client: TMDBClient, settings: Settings
) -> None:
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
                    text = format_status_change_notification(item, info)
                else:
                    continue

                kb = notification_item_keyboard(
                    item_id=item.id,
                    tmdb_url=getattr(item, "tmdb_url", None),
                    bot_username=settings.BOT_USERNAME,
                )

                try:
                    await bot.send_message(telegram_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
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
                    bot_username = getattr(bot, "settings", None).BOT_USERNAME if hasattr(bot, "settings") and bot.settings else "kinojdun_bot"
                    kb = notification_item_keyboard(
                        item_id=item.id,
                        tmdb_url=getattr(item, "tmdb_url", None),
                        bot_username=bot_username,
                    )
                    try:
                        await bot.send_message(item.user.telegram_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
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


async def check_channel_queue_job(bot: Bot, session_factory, settings: Settings) -> None:
    """Периодическая проверка и публикация отложенных постов из очереди в Telegram-канал."""
    if not settings.TELEGRAM_CHANNEL_ID or not settings.CHANNEL_POSTING_ENABLED:
        return

    try:
        publisher = ChannelPublisher(session_factory, settings, bot)
        published_count = await publisher.publish_pending_queue()
        if published_count > 0:
            logger.info(f"Опубликовано {published_count} отложенных постов в Telegram-канал.")
    except Exception as e:
        logger.error(f"Ошибка при публикации очереди в канал: {e}", exc_info=True)


async def daily_digest_job(
    bot: Bot, session_factory, settings: Settings, tmdb_client: Optional[TMDBClient] = None
) -> None:
    """Ежедневный выпуск дайджеста «Что выходит сегодня»."""
    if not settings.DAILY_DIGEST_ENABLED:
        return
    logger.info("Запуск формирования утреннего дайджеста «Что выходит сегодня»...")
    try:
        publisher = ChannelPublisher(session_factory, settings, bot, tmdb_client=tmdb_client)
        post = await publisher.create_daily_digest()
        if post:
            logger.info(f"Утренний дайджест успешно сформирован (ID: {post.id}, статус: {post.status}).")
    except Exception as e:
        logger.error(f"Ошибка при формировании утреннего дайджеста: {e}", exc_info=True)


async def weekly_digest_job(
    bot: Bot, session_factory, settings: Settings, tmdb_client: Optional[TMDBClient] = None
) -> None:
    """Еженедельный выпуск дайджеста «Главные премьеры недели»."""
    if not settings.WEEKLY_DIGEST_ENABLED:
        return
    logger.info("Запуск формирования еженедельного дайджеста «Главные премьеры недели»...")
    try:
        publisher = ChannelPublisher(session_factory, settings, bot, tmdb_client=tmdb_client)
        post = await publisher.create_weekly_digest()
        if post:
            logger.info(f"Еженедельный дайджест успешно сформирован (ID: {post.id}, статус: {post.status}).")
    except Exception as e:
        logger.error(f"Ошибка при формировании еженедельного дайджеста: {e}", exc_info=True)


def setup_scheduler(
    bot: Bot, session_factory, tmdb_client: TMDBClient, settings: Settings
) -> AsyncIOScheduler:
    """Настройка и конфигурирование планировщика задач."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    now_utc = datetime.now(timezone.utc)

    # Личные уведомления по отслеживаемым фильмам и сериалам (первый запуск через 5 сек)
    scheduler.add_job(
        check_updates_job,
        "interval",
        hours=settings.CHECK_INTERVAL_HOURS,
        next_run_time=now_utc + timedelta(seconds=5),
        kwargs={
            "bot": bot,
            "session_factory": session_factory,
            "tmdb_client": tmdb_client,
            "settings": settings,
        },
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

    # Публикация отложенных постов в канал (каждые 15 минут, первый запуск через 15 сек)
    queue_interval = max(5, settings.CHANNEL_MIN_POST_INTERVAL_MINUTES)
    scheduler.add_job(
        check_channel_queue_job,
        "interval",
        minutes=queue_interval,
        next_run_time=now_utc + timedelta(seconds=15),
        kwargs={"bot": bot, "session_factory": session_factory, "settings": settings},
        id="check_channel_queue",
        replace_existing=True,
    )

    # Ежедневный утренний дайджест «Что выходит сегодня» (по расписанию)
    scheduler.add_job(
        daily_digest_job,
        "cron",
        hour=settings.DAILY_DIGEST_HOUR,
        minute=30,
        kwargs={
            "bot": bot,
            "session_factory": session_factory,
            "settings": settings,
            "tmdb_client": tmdb_client,
        },
        id="channel_daily_digest",
        replace_existing=True,
    )

    # Еженедельный дайджест «Главные премьеры недели» (по расписанию)
    scheduler.add_job(
        weekly_digest_job,
        "cron",
        day_of_week=settings.WEEKLY_DIGEST_DAY,
        hour=settings.WEEKLY_DIGEST_HOUR,
        minute=0,
        kwargs={
            "bot": bot,
            "session_factory": session_factory,
            "settings": settings,
            "tmdb_client": tmdb_client,
        },
        id="channel_weekly_digest",
        replace_existing=True,
    )

    return scheduler
