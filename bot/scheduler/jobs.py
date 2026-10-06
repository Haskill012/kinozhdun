"""Фоновые периодические задачи планировщика APScheduler."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from aiogram import Bot
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.db.repositories import Repository
from bot.services.channel import ChannelPublisher
from bot.services.tmdb import TMDBClient
from bot.services.tracker import TrackerService
from bot.services.episode_reminders import episodes_on_date
from bot.keyboards.inline import notification_item_keyboard
from bot.utils.formatting import (
    format_announced_notification,
    format_released_notification,
    format_reminder_notification,
    format_status_change_notification,
    format_episode_tomorrow_notification,
)

logger = logging.getLogger(__name__)


def episode_reminder_now():
    return datetime.now(ZoneInfo("Europe/Moscow"))


async def check_episode_reminders_job(bot: Bot, session_factory, tmdb_client: TMDBClient,
                                     settings: Settings) -> None:
    """Notify subscribers once per episode on the preceding Moscow calendar day."""
    now = episode_reminder_now()
    if not 10 <= now.hour < 22:
        return
    target = now.date() + timedelta(days=1)
    try:
        async with session_factory() as session:
            repo = Repository(session)
            items = await repo.get_tracked_series()
            cache = {}
            for item in items:
                if not item.user or not item.user.telegram_id:
                    continue
                try:
                    if item.tmdb_id not in cache:
                        details = await tmdb_client.get_tv_details(item.tmdb_id)
                        cache[item.tmdb_id] = (await episodes_on_date(tmdb_client, item.tmdb_id, details, target)
                                              if details else [])
                    for episode in cache[item.tmdb_id]:
                        event = f"episode_tomorrow:{episode['season_number']}:{episode['episode_number']}:{target.isoformat()}"
                        if await repo.has_notification(item.id, event):
                            continue
                        text = format_episode_tomorrow_notification(item, episode)
                        kb = notification_item_keyboard(item_id=item.id, media_type="tv",
                                                       tmdb_id=item.tmdb_id, tmdb_url=item.tmdb_url,
                                                       bot_username=settings.BOT_USERNAME)
                        await bot.send_message(item.user.telegram_id, text, reply_markup=kb,
                                               parse_mode=ParseMode.HTML)
                        await repo.log_notification(item.id, event, text)
                        # Persist each successful send before moving to another subscriber.
                        await session.commit()
                except Exception:
                    logger.warning("Не удалось обработать напоминание о серии; повтор при следующей проверке.")
    except Exception:
        logger.exception("Ошибка проверки напоминаний о новых сериях.")


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
                    media_type=item.media_type,
                    tmdb_id=item.tmdb_id,
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
                        media_type=item.media_type,
                        tmdb_id=item.tmdb_id,
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

    # First check at 10:00 Moscow; daytime retries also catch late catalogue updates.
    scheduler.add_job(
        check_episode_reminders_job,
        "cron", hour="10-21", minute=0,
        next_run_time=now_utc + timedelta(seconds=30),
        kwargs={"bot": bot, "session_factory": session_factory,
                "tmdb_client": tmdb_client, "settings": settings},
        id="check_episode_reminders", replace_existing=True, max_instances=1,
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
