"""Хендлеры команд /start, /help и единый диспетчер входящих Telegram Deep Links."""

import json
import logging
import re
from typing import Optional
from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject, Command, or_f
from aiogram.types import Message, CallbackQuery

from bot.db.repositories import Repository
from bot.keyboards.inline import (
    shared_item_recipient_keyboard,
    shared_watchlist_recipient_keyboard,
    channel_referral_keyboard,
)
from bot.keyboards.reply import main_menu_keyboard
from bot.services.analytics import AnalyticsService
from bot.utils.formatting import (
    format_welcome_message,
    format_help_message,
    format_shared_item_prompt,
    format_shared_watchlist_message,
    format_channel_referral_prompt,
)

logger = logging.getLogger(__name__)

router = Router(name="start_router")


def parse_content_deep_link(payload: str) -> Optional[tuple[str, int, Optional[int]]]:
    """Парсит payload шеринга контента: c_<media_type>_<tmdb_id>[_u<referrer_id>] или share_<media_type>_<tmdb_id>.
    
    Примеры:
    - c_tv_82856
    - c_movie_550
    - c_tv_82856_u123456789
    - share_tv_82856
    """
    match = re.match(r"^(?:c|share)_(tv|movie)_(\d+)(?:_u(\d+))?$", payload)
    if match:
        media_type = match.group(1)
        tmdb_id = int(match.group(2))
        referrer_id = int(match.group(3)) if match.group(3) else None
        return media_type, tmdb_id, referrer_id
    return None


def parse_watchlist_deep_link(payload: str) -> Optional[str]:
    """Парсит payload расшаренного списка: w_<token> (например: w_a1b2c3d4e5)."""
    match = re.match(r"^w_([a-zA-Z0-9_-]{4,32})$", payload)
    if match:
        return match.group(1)
    return None


def parse_channel_deep_link(payload: str) -> Optional[int]:
    """Парсит payload перехода из канала: ch_<post_id> (например: ch_42)."""
    match = re.match(r"^ch_(\d+)$", payload)
    if match:
        return int(match.group(1))
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    """Единая точка входа /start — регистрация, маршрутизация deep links и показ меню."""
    session_factory = message.bot["session_factory"]
    tmdb_client = message.bot["tmdb_client"]
    analytics = AnalyticsService(session_factory)
    payload = (command.args or "").strip()

    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    # --- 1. Обычный старт без аргументов ---
    if not payload:
        async with session_factory() as session:
            repo = Repository(session)
            await repo.get_or_create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                referral_source="organic",
            )
            await session.commit()

        await message.answer(
            format_welcome_message(first_name or "друг"),
            reply_markup=main_menu_keyboard(),
        )
        return

    # --- 2. Виральный переход по отдельному фильму/сериалу (c_*) ---
    content_data = parse_content_deep_link(payload)
    if content_data:
        media_type, tmdb_id, referrer_id = content_data
        ref_source = f"share_content:{media_type}:{tmdb_id}"

        async with session_factory() as session:
            repo = Repository(session)
            await repo.get_or_create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                referral_source=ref_source,
                referrer_id=referrer_id,
            )
            is_tracked = await repo.is_already_tracking(telegram_id, tmdb_id, media_type)
            await session.commit()

        # Логируем аналитику перехода
        await analytics.log_share_link_opened(telegram_id, media_type, tmdb_id, referrer_id)

        # Получаем данные о тайтле из TMDB
        if media_type == "tv":
            details = await tmdb_client.get_tv_details(tmdb_id)
        else:
            details = await tmdb_client.get_movie_details(tmdb_id)

        if not details:
            await message.answer(
                "❌ К сожалению, не удалось загрузить информацию об этом проекте.\n"
                "Воспользуйтесь поиском в меню ниже:",
                reply_markup=main_menu_keyboard(),
            )
            return

        title = details.get("title", "Без названия")
        text = format_shared_item_prompt(title, details, media_type)
        reply_markup = shared_item_recipient_keyboard(
            media_type=media_type,
            tmdb_id=tmdb_id,
            is_already_tracked=is_tracked,
            referrer_id=referrer_id,
        )
        await message.answer(text, reply_markup=reply_markup)
        return

    # --- 3. Переход по расшаренному списку «Мой Кинождун» (w_*) ---
    watchlist_token = parse_watchlist_deep_link(payload)
    if watchlist_token:
        ref_source = f"share_watchlist:{watchlist_token}"

        async with session_factory() as session:
            repo = Repository(session)
            await repo.get_or_create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                referral_source=ref_source,
            )
            shared_watchlist = await repo.get_shared_watchlist_by_token(watchlist_token)
            if shared_watchlist:
                await repo.increment_watchlist_views(watchlist_token)
            # Узнаем текущие тайтлы пользователя, чтобы отметить уже отслеживаемые
            user_items = await repo.get_user_items(telegram_id)
            tracked_keys = {(it.media_type, it.tmdb_id) for it in user_items}
            await session.commit()

        if not shared_watchlist:
            await message.answer(
                "⚠️ <b>Этот список ожидания не найден или ссылка устарела.</b>\n\n"
                "Вы можете создать свой собственный список ожидания — воспользуйтесь поиском ниже:",
                reply_markup=main_menu_keyboard(),
            )
            return

        # Логируем аналитику открытия списка
        await analytics.log_watchlist_link_opened(telegram_id, watchlist_token)

        try:
            items_snapshot = json.loads(shared_watchlist.items_snapshot)
        except Exception:
            items_snapshot = []

        text = format_shared_watchlist_message(items_snapshot, shared_watchlist.title)
        reply_markup = shared_watchlist_recipient_keyboard(watchlist_token, items_snapshot, tracked_keys)
        await message.answer(text, reply_markup=reply_markup)
        return

    # --- 4. Переход из Telegram-канала (ch_*) ---
    post_id = parse_channel_deep_link(payload)
    if post_id is not None:
        ref_source = f"telegram_channel:{post_id}"

        async with session_factory() as session:
            repo = Repository(session)
            await repo.get_or_create_user(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                referral_source=ref_source,
            )
            post = await repo.get_channel_post(post_id)
            is_tracked = False
            if post:
                is_tracked = await repo.is_already_tracking(telegram_id, post.tmdb_id, post.media_type)
            await session.commit()

        if not post:
            await message.answer(
                "⚠️ <b>Публикация не найдена или устарела.</b>\n\n"
                "Вы можете найти интересующий вас сериал или фильм через поиск:",
                reply_markup=main_menu_keyboard(),
            )
            return

        # Логируем аналитику открытия ссылки из канала
        await analytics.log_channel_link_opened(telegram_id, post_id, post.tmdb_id)

        text = format_channel_referral_prompt(post)
        reply_markup = channel_referral_keyboard(
            post_id=post.id,
            media_type=post.media_type,
            tmdb_id=post.tmdb_id,
            title=post.title,
            is_already_tracked=is_tracked,
        )
        await message.answer(text, reply_markup=reply_markup)
        return

    # --- 5. Неизвестный или неподдерживаемый формат ссылки ---
    async with session_factory() as session:
        repo = Repository(session)
        await repo.get_or_create_user(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            referral_source=f"unknown:{payload[:32]}",
        )
        await session.commit()

    await message.answer(
        format_welcome_message(first_name or "друг"),
        reply_markup=main_menu_keyboard(),
    )


@router.message(or_f(Command("help"), F.text == "ℹ️ Справка и помощь", F.text == "ℹ️ Справка"))
async def cmd_help(message: Message) -> None:
    """Обработка команды /help и кнопки «ℹ️ Справка»."""
    await message.answer(format_help_message(), reply_markup=main_menu_keyboard())
