"""Фоновые периодические задачи планировщика APScheduler."""

import logging
from pathlib import Path
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
from bot.services.social_editorial import catalog_candidates, resolve_catalog_item
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
                    unnotified_episodes = []
                    for episode in cache[item.tmdb_id]:
                        event = f"episode_tomorrow:{episode['season_number']}:{episode['episode_number']}:{target.isoformat()}"
                        if not await repo.has_notification(item.id, event):
                            unnotified_episodes.append(episode)
                    if not unnotified_episodes:
                        continue
                    text = format_episode_tomorrow_notification(item, unnotified_episodes)
                    kb = notification_item_keyboard(item_id=item.id, media_type="tv",
                                                   tmdb_id=item.tmdb_id, tmdb_url=item.tmdb_url,
                                                   bot_username=settings.BOT_USERNAME)
                    await bot.send_message(item.user.telegram_id, text, reply_markup=kb,
                                           parse_mode=ParseMode.HTML)
                    for episode in unnotified_episodes:
                        event = f"episode_tomorrow:{episode['season_number']}:{episode['episode_number']}:{target.isoformat()}"
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
    if settings.DAILY_DIGEST_SKIP_WEEKLY_DAY and settings.WEEKLY_DIGEST_ENABLED and episode_reminder_now().weekday() == settings.WEEKLY_DIGEST_DAY:
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


async def daily_shorts_job(
    bot: Bot, session_factory, settings: Settings, tmdb_client: Optional[TMDBClient] = None
) -> None:
    """Ежедневное создание и дистрибуция вертикального шортса (Shorts/Reels/Clips) о главной премьере."""
    if not getattr(settings, "SHORTS_ENABLED", True) or not getattr(settings, "SHORTS_AUTO_PUBLISH", True):
        return
    logger.info("Запуск ежедневной генерации премьерного шортса...")
    try:
        publisher = ChannelPublisher(session_factory, settings, bot, tmdb_client=tmdb_client)
        post = await publisher.create_daily_premiere_short()
        if post:
            logger.info(f"Ежедневный шортс успешно сформирован и опубликован (ID: {post.id}, тайтл: «{post.title}»).")
        else:
            logger.info("Кандидатов для ежедневного шортса не найдено или шортс на сегодня уже опубликован.")
    except Exception as e:
        logger.error(f"Ошибка при создании ежедневного шортса: {e}", exc_info=True)


async def check_vk_feed_job(session_factory, settings: Settings, tmdb_client=None) -> None:
    """Периодическая публикация очередной новинки из каталога в сообщество ВКонтакте."""
    if not getattr(settings, "VK_POSTING_ENABLED", False):
        return
    if not settings.VK_AUTO_PUBLISH:
        return
    if not settings.VK_ACCESS_TOKEN or not settings.VK_GROUP_ID:
        return

    publisher = None
    try:
        import json
        from datetime import date
        from zoneinfo import ZoneInfo
        from bot.services.vk_publisher import VKPublisher
        from bot.services.channel import generate_event_fingerprint

        publisher = VKPublisher(session_factory, settings)
        if not publisher.is_configured():
            return

        seed_file = Path(__file__).parent.parent.parent / "website" / "catalog_seed.json"
        if not seed_file.exists():
            return

        with open(seed_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        titles = data.get("titles", [])
        if not titles:
            return

        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        async with session_factory() as session:
            repo = Repository(session)
            candidates_list = list(catalog_candidates(titles, today))

            # Если в сид-каталоге закончились свежие премьеры, дополняем из TMDB Discover
            if tmdb_client:
                try:
                    fresh_m = await tmdb_client.discover_upcoming_movies(today, today + timedelta(days=45))
                    for m in fresh_m:
                        if m.get("id") and not any(c.get("id") == m["id"] for c in candidates_list):
                            candidates_list.append({
                                "id": m["id"],
                                "media_type": "movie",
                                "title": m.get("title"),
                                "overview": m.get("overview"),
                                "release_date": m.get("release_date"),
                                "poster": m.get("poster_path"),
                                "popularity": m.get("popularity", 0),
                                "rating": m.get("vote_average", 0),
                            })
                except Exception as tmdb_err:
                    logger.warning("Ошибка получения TMDB discover для VK feed: %s", tmdb_err)

            for item in candidates_list:
                item = await resolve_catalog_item(item, tmdb_client, today, settings)
                if item is None:
                    continue
                release_d = item["air_date"]
                # СТРОГО: прошедшие премьеры (старше 7 дней) не публикуются в ленту!
                if release_d and (release_d - today).days < -7:
                    continue
                date_str = release_d.isoformat() if release_d else "nodate"
                event_type = item["event_type"]

                h = generate_event_fingerprint(
                    tmdb_id=item.get("id"),
                    media_type=item.get("media_type", "movie"),
                    event_type=event_type,
                    season_number=item.get("season"),
                    extra_key=date_str,
                )
                if not await repo.is_vk_post_exists(h):
                    post_id = await publisher.publish_event(
                        title=item["title"],
                        media_type=item.get("media_type", "movie"),
                        event_type=event_type,
                        season_number=item.get("season"),
                        tmdb_id=item.get("id"),
                        air_date=release_d,
                        episode_number=item.get("episode_number"),
                        genres=item.get("genres", []),
                        overview=item.get("overview"),
                        network=item.get("network"),
                        poster_path=(item.get("image") or item.get("poster")) if settings.VK_ATTACHMENT_MODE == "community_photo" else (item.get("poster") or item.get("image")),
                        item_id=item.get("id"),
                    )
                    if post_id:
                        logger.info(f"Фоновая автопубликация в VK: «{item['title']}» (post_id={post_id})")
                    break
    except Exception as e:
        logger.error(f"Ошибка при фоновой публикации в VK: {e}", exc_info=True)
    finally:
        if publisher:
            await publisher.close()


async def check_dzen_feed_job(session_factory, settings: Settings, bot: Optional[Bot] = None, tmdb_client=None) -> None:
    """Периодическая публикация актуальной премьеры или отправка очереди в канал Дзена."""
    if not getattr(settings, "DZEN_POSTING_ENABLED", False):
        return
    if not getattr(settings, "DZEN_AUTO_PUBLISH", True):
        return
    if settings.DZEN_SYNC_MODE == "telegram_sync":
        return

    publisher = None
    try:
        import json
        from datetime import date
        from zoneinfo import ZoneInfo
        from bot.services.dzen_publisher import DzenPublisher
        from bot.services.channel import generate_event_fingerprint

        publisher = DzenPublisher(session_factory, settings, bot=bot)
        if not publisher.is_configured():
            return

        # Сначала проверяем отложенную очередь
        sent = await publisher.publish_pending_queue()
        if sent > 0:
            return

        seed_file = Path(__file__).parent.parent.parent / "website" / "catalog_seed.json"
        if not seed_file.exists():
            return

        with open(seed_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        titles = data.get("titles", [])
        if not titles:
            return

        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        async with session_factory() as session:
            repo = Repository(session)
            candidates_list = list(catalog_candidates(titles, today))

            if tmdb_client:
                try:
                    fresh_m = await tmdb_client.discover_upcoming_movies(today, today + timedelta(days=45))
                    for m in fresh_m:
                        if m.get("id") and not any(c.get("id") == m["id"] for c in candidates_list):
                            candidates_list.append({
                                "id": m["id"],
                                "media_type": "movie",
                                "title": m.get("title"),
                                "overview": m.get("overview"),
                                "release_date": m.get("release_date"),
                                "poster": m.get("poster_path"),
                                "popularity": m.get("popularity", 0),
                                "rating": m.get("vote_average", 0),
                            })
                except Exception as tmdb_err:
                    logger.warning("Ошибка получения TMDB discover для Dzen feed: %s", tmdb_err)

            for item in candidates_list:
                item = await resolve_catalog_item(item, tmdb_client, today, settings)
                if item is None:
                    continue
                release_d = item["air_date"]
                # СТРОГО: прошедшие премьеры (старше 7 дней) не публикуются в ленту!
                if release_d and (release_d - today).days < -7:
                    continue
                date_str = release_d.isoformat() if release_d else "nodate"
                event_type = item["event_type"]

                h = generate_event_fingerprint(
                    tmdb_id=item.get("id"),
                    media_type=item.get("media_type", "movie"),
                    event_type=event_type,
                    season_number=item.get("season"),
                    extra_key=date_str,
                )
                if not await repo.is_dzen_post_exists(h):
                    post = await publisher.publish_event(
                        title=item["title"],
                        media_type=item.get("media_type", "movie"),
                        event_type=event_type,
                        season_number=item.get("season"),
                        tmdb_id=item.get("id"),
                        air_date=release_d,
                        episode_number=item.get("episode_number"),
                        genres=item.get("genres", []),
                        overview=item.get("overview"),
                        network=item.get("network"),
                        poster_path=item.get("poster") or item.get("image"),
                    )
                    if post:
                        logger.info(f"Фоновая автопубликация в Дзен: «{item['title']}» (status={post.status})")
                    break
    except Exception as e:
        logger.error(f"Ошибка при фоновой публикации в Дзен: {e}", exc_info=True)
    finally:
        if publisher:
            await publisher.close()


def setup_scheduler(
    bot: Bot, session_factory, tmdb_client: TMDBClient, settings: Settings
) -> AsyncIOScheduler:
    """Настройка и конфигурирование планировщика задач."""
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    now_utc = datetime.now(timezone.utc)

    if settings.VK_POSTING_ENABLED and settings.VK_AUTO_PUBLISH:
        scheduler.add_job(
            check_vk_feed_job, "cron", day_of_week=settings.VK_POST_DAYS,
            hour=settings.VK_POST_HOUR, minute=settings.VK_POST_MINUTE,
            kwargs={"session_factory": session_factory, "settings": settings, "tmdb_client": tmdb_client},
            coalesce=True, max_instances=1, misfire_grace_time=900,
            id="check_vk_feed", replace_existing=True,
        )

    if getattr(settings, "DZEN_POSTING_ENABLED", False) and settings.DZEN_AUTO_PUBLISH and settings.DZEN_SYNC_MODE != "telegram_sync":
        scheduler.add_job(
            check_dzen_feed_job, "cron", day_of_week=settings.DZEN_POST_DAYS,
            hour=settings.DZEN_POST_HOUR, minute=settings.DZEN_POST_MINUTE,
            coalesce=True, max_instances=1, misfire_grace_time=900,
            kwargs={"session_factory": session_factory, "settings": settings, "bot": bot, "tmdb_client": tmdb_client},
            id="check_dzen_feed", replace_existing=True,
        )

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
        day_of_week=",".join(str(day) for day in range(7) if not (
            settings.DAILY_DIGEST_SKIP_WEEKLY_DAY and settings.WEEKLY_DIGEST_ENABLED and day == settings.WEEKLY_DIGEST_DAY)),
        coalesce=True, max_instances=1, misfire_grace_time=900,
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
        coalesce=True, max_instances=1, misfire_grace_time=900,
        kwargs={
            "bot": bot,
            "session_factory": session_factory,
            "settings": settings,
            "tmdb_client": tmdb_client,
        },
        id="channel_weekly_digest",
        replace_existing=True,
    )

    # Ежедневный шортс о топ-премьере (по расписанию в 12:00 МСК)
    shorts_hour = getattr(settings, "SHORTS_DAILY_HOUR", 12)
    shorts_minute = getattr(settings, "SHORTS_DAILY_MINUTE", 0)
    scheduler.add_job(
        daily_shorts_job,
        "cron",
        hour=shorts_hour,
        minute=shorts_minute,
        coalesce=True, max_instances=1, misfire_grace_time=1800,
        kwargs={
            "bot": bot,
            "session_factory": session_factory,
            "settings": settings,
            "tmdb_client": tmdb_client,
        },
        id="channel_daily_shorts",
        replace_existing=True,
    )

    return scheduler
