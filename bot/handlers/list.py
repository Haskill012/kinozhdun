"""Хендлеры для просмотра списка отслеживаемых элементов, проверки их статуса и расшаривания «Мой Кинождун»."""

import datetime
import json
import logging
from aiogram import Router, F
from aiogram.filters import Command, or_f
from aiogram.types import Message, CallbackQuery

from bot.db.repositories import Repository
from bot.keyboards.inline import (
    user_items_keyboard,
    back_to_list_keyboard,
    shared_watchlist_created_keyboard,
    shared_watchlist_recipient_keyboard,
    confirm_batch_track_keyboard,
)
from bot.keyboards.reply import main_menu_keyboard
from bot.services.analytics import AnalyticsService
from bot.utils.formatting import (
    format_item_list,
    format_item_details,
    format_shared_watchlist_message,
)

logger = logging.getLogger(__name__)

router = Router(name="list_router")


async def render_user_list(telegram_id: int, username: str | None, first_name: str | None, session_factory) -> tuple[str, any]:
    """Вспомогательная функция для получения текста и клавиатуры списка отслеживаемого."""
    async with session_factory() as session:
        repo = Repository(session)
        await repo.get_or_create_user(telegram_id, username, first_name)
        items = await repo.get_user_items(telegram_id)

        if not items:
            return (
                "📭 <b>Ваш список ожидания пуст.</b>\n\n"
                "Нажмите <b>«🔍 Найти сериал / фильм»</b> или просто напишите название в чат, чтобы добавить тайтл!",
                None
            )

        text = format_item_list(items)
        reply_markup = user_items_keyboard(items, action="info")
        return text, reply_markup


@router.message(or_f(Command("list"), F.text == "🍿 Мой список ожидания", F.text == "📋 Мой список"))
async def cmd_list(message: Message) -> None:
    """Команда /list или кнопка «📋 Мой список» — показать список отслеживаемых проектов."""
    session_factory = message.bot["session_factory"]
    text, reply_markup = await render_user_list(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        session_factory,
    )
    await message.answer(text, reply_markup=reply_markup)


@router.message(or_f(Command("status"), F.text == "🔄 Проверить статус"))
async def cmd_status(message: Message) -> None:
    """Команда /status или кнопка «🔄 Проверить статус» — актуализация данных и вывод списка."""
    session_factory = message.bot["session_factory"]
    tmdb_client = message.bot["tmdb_client"]

    status_msg = await message.answer("🔄 Запрашиваю свежие данные с TMDB...")

    async with session_factory() as session:
        repo = Repository(session)
        await repo.get_or_create_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
        items = await repo.get_user_items(message.from_user.id)

        if not items:
            await status_msg.edit_text(
                "📭 Ваш список ожидания пуст. Отправьте название фильма или сериала для поиска."
            )
            return

        # Обновляем каждый элемент актуальными данными с TMDB
        for item in items:
            if item.media_type == "tv":
                details = await tmdb_client.get_tv_details(item.tmdb_id)
                if details:
                    if details.get("network"):
                        item.network = details["network"]
                    next_ep = details.get("next_episode_to_air")
                    if next_ep and next_ep.get("air_date"):
                        try:
                            item.next_air_date = datetime.date.fromisoformat(next_ep["air_date"])
                            item.next_season_number = next_ep.get("season_number")
                            item.status = "announced"
                        except (ValueError, TypeError):
                            pass
                    if details.get("status"):
                        item.status = "ended" if details.get("status") in ("Ended", "Canceled") else item.status
            else:
                details = await tmdb_client.get_movie_details(item.tmdb_id)
                if details:
                    if details.get("network"):
                        item.network = details["network"]
                    if details.get("release_date"):
                        try:
                            rd = datetime.date.fromisoformat(details["release_date"])
                            if rd > datetime.date.today():
                                item.next_air_date = rd
                                item.status = "announced"
                        except (ValueError, TypeError):
                            pass

        await session.commit()
        refreshed_items = await repo.get_user_items(message.from_user.id)

    text = format_item_list(refreshed_items)
    reply_markup = user_items_keyboard(refreshed_items, action="info")
    await status_msg.edit_text(text, reply_markup=reply_markup)


@router.callback_query(F.data.startswith("info:"))
async def process_info(callback: CallbackQuery) -> None:
    """Просмотр детальной карточки элемента."""
    await callback.answer()
    item_id = int(callback.data.split(":")[1])

    session_factory = callback.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        item = await repo.get_tracked_item(item_id)

        if not item or (item.user and item.user.telegram_id != callback.from_user.id):
            await callback.message.edit_text(
                "❌ Элемент не найден или удалён.",
                reply_markup=back_to_list_keyboard(),
            )
            return

        text = format_item_details(item)
        await callback.message.edit_text(text, reply_markup=back_to_list_keyboard())


@router.callback_query(F.data == "back_to_list")
async def process_back_to_list(callback: CallbackQuery) -> None:
    """Возврат к общему списку отслеживания."""
    await callback.answer()
    session_factory = callback.bot["session_factory"]
    text, reply_markup = await render_user_list(
        callback.from_user.id,
        callback.from_user.username,
        callback.from_user.first_name,
        session_factory,
    )
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- 2. Раздел «Мой Кинождун»: Создание и шеринг списка ожидания ---

@router.callback_query(F.data == "share_watchlist")
async def process_share_watchlist(callback: CallbackQuery) -> None:
    """Формирует снапшот списка ожидания пользователя и выдаёт готовую ссылку для отправки друзьям."""
    await callback.answer()
    session_factory = callback.bot["session_factory"]
    settings = callback.bot["settings"]
    analytics = AnalyticsService(session_factory)

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        items = await repo.get_user_items(callback.from_user.id)

        if not items:
            await callback.message.edit_text(
                "📭 Ваш список ожидания пуст. Добавьте хотя бы один фильм или сериал, чтобы поделиться!",
                reply_markup=back_to_list_keyboard(),
            )
            return

        # Создаём изолированный снапшот
        shared = await repo.create_shared_watchlist(user.id, items)
        await session.commit()
        token = shared.token
        items_count = len(items)
        titles = [it.title for it in items]

    # Логируем аналитику создания расшаренного списка
    await analytics.log_watchlist_shared(callback.from_user.id, token, items_count)

    text = (
        "🍿 <b>Ваш список ожидания готов к отправке!</b>\n"
        "────────────────────────\n"
        f"В снапшот включено проектов: <b>{items_count}</b>.\n\n"
        "Вы можете отправить его друзьям или в любой Telegram-чат одним нажатием кнопки ниже.\n\n"
        "✨ <i>Получатели смогут изучить ваш список ожидания и добавить любые тайтлы в свой Кинождун в 1 клик!</i>"
    )
    reply_markup = shared_watchlist_created_keyboard(token, settings.BOT_USERNAME, titles)
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- 2. Раздел «Мой Кинождун»: Добавление отдельного тайтла из расшаренного списка ---

@router.callback_query(F.data.startswith("track_shared_item:"))
async def process_track_shared_item(callback: CallbackQuery) -> None:
    """Добавление одной позиции из расшаренного списка друга."""
    parts = callback.data.split(":")
    token = parts[1]
    idx = int(parts[2])

    session_factory = callback.bot["session_factory"]
    settings = callback.bot["settings"]
    analytics = AnalyticsService(session_factory)

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            referral_source=f"share_watchlist:{token}",
        )
        shared = await repo.get_shared_watchlist_by_token(token)
        if not shared:
            await callback.answer("❌ Список не найден или ссылка устарела.", show_alert=True)
            return

        try:
            items_snapshot = json.loads(shared.items_snapshot)
        except Exception:
            items_snapshot = []

        if idx >= len(items_snapshot):
            await callback.answer("❌ Элемент не найден в списке.", show_alert=True)
            return

        target_item = items_snapshot[idx]
        m_type = target_item.get("media_type", "movie")
        t_id = int(target_item.get("tmdb_id", 0))

        if await repo.is_already_tracking(callback.from_user.id, t_id, m_type):
            await callback.answer("Этот проект уже есть в вашем списке ожидания! 🍿", show_alert=True)
            return

        # Добавляем в отслеживание
        added_count, _ = await repo.batch_add_tracked_items(
            user_id=user.id,
            items_data=[target_item],
            max_items=settings.MAX_ITEMS_PER_USER,
        )
        await session.commit()

        # Актуализируем список отслеживаемых для обновления кнопок
        user_items = await repo.get_user_items(callback.from_user.id)
        tracked_keys = {(it.media_type, it.tmdb_id) for it in user_items}

    if added_count > 0:
        await analytics.log_watchlist_item_followed(callback.from_user.id, token, m_type, t_id)
        await callback.answer(f"✅ «{target_item.get('title')}» добавлен в ваш список!", show_alert=False)
    else:
        await callback.answer("⚠️ Не удалось добавить (возможно, превышен лимит тайтлов).", show_alert=True)

    # Обновляем клавиатуру расшаренного списка
    new_text = format_shared_watchlist_message(items_snapshot, shared.title)
    new_markup = shared_watchlist_recipient_keyboard(token, items_snapshot, tracked_keys)
    try:
        await callback.message.edit_text(new_text, reply_markup=new_markup)
    except Exception:
        pass


# --- 2. Раздел «Мой Кинождун»: Запрос подтверждения «Отслеживать всё» ---

@router.callback_query(F.data.startswith("prompt_batch_track:"))
async def process_prompt_batch_track(callback: CallbackQuery) -> None:
    """Показывает экран подтверждения со списком тайтлов перед массовым добавлением."""
    await callback.answer()
    token = callback.data.split(":")[1]

    session_factory = callback.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        shared = await repo.get_shared_watchlist_by_token(token)
        if not shared:
            await callback.message.edit_text("❌ Список не найден или ссылка устарела.")
            return

        try:
            items_snapshot = json.loads(shared.items_snapshot)
        except Exception:
            items_snapshot = []

        user_items = await repo.get_user_items(callback.from_user.id)
        tracked_keys = {(it.media_type, it.tmdb_id) for it in user_items}

    untracked_items = [
        it for it in items_snapshot
        if (it.get("media_type", "movie"), int(it.get("tmdb_id", 0))) not in tracked_keys
    ]

    if not untracked_items:
        await callback.message.edit_text(
            "🍿 <b>Все проекты из этого списка уже находятся в вашем списке ожидания!</b>",
            reply_markup=back_to_list_keyboard(),
        )
        return

    titles_list = "\n".join(f"• <b>{it.get('title')}</b>" for it in untracked_items[:10])
    if len(untracked_items) > 10:
        titles_list += f"\n• <i>... и ещё {len(untracked_items) - 10} тайтлов</i>"

    text = (
        "📋 <b>Подтверждение отслеживания</b>\n"
        "────────────────────────\n"
        f"Вы собираетесь добавить в свой список ожидания <b>{len(untracked_items)}</b> новых проектов:\n\n"
        f"{titles_list}\n\n"
        "Добавить их все в ваш Кинождун?"
    )
    reply_markup = confirm_batch_track_keyboard(token)
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- 2. Раздел «Мой Кинождун»: Выполнение пакетного добавления ---

@router.callback_query(F.data.startswith("confirm_batch_track:"))
async def process_confirm_batch_track(callback: CallbackQuery) -> None:
    """Выполняет пакетное добавление всех тайтлов из расшаренного списка."""
    await callback.answer()
    token = callback.data.split(":")[1]

    session_factory = callback.bot["session_factory"]
    settings = callback.bot["settings"]
    analytics = AnalyticsService(session_factory)

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            referral_source=f"share_watchlist:{token}",
        )
        shared = await repo.get_shared_watchlist_by_token(token)
        if not shared:
            await callback.message.edit_text("❌ Список не найден или ссылка устарела.")
            return

        try:
            items_snapshot = json.loads(shared.items_snapshot)
        except Exception:
            items_snapshot = []

        added_count, added_titles = await repo.batch_add_tracked_items(
            user_id=user.id,
            items_data=items_snapshot,
            max_items=settings.MAX_ITEMS_PER_USER,
        )
        await session.commit()

    await analytics.log_watchlist_follow_all(callback.from_user.id, token, added_count)

    text = (
        f"🎉 <b>Успешно добавлено проектов: {added_count}!</b>\n"
        "────────────────────────\n"
        "Все выбранные тайтлы теперь находятся в вашем списке ожидания.\n\n"
        "Как только появятся новые сезоны, даты выхода или официальные трейлеры — "
        "Кинождун пришлёт вам персональное уведомление 🍿"
    )
    await callback.message.edit_text(text, reply_markup=back_to_list_keyboard())


@router.callback_query(F.data.startswith("cancel_batch_track:"))
async def process_cancel_batch_track(callback: CallbackQuery) -> None:
    """Отмена массового добавления — возврат к просмотру расшаренного списка."""
    await callback.answer()
    token = callback.data.split(":")[1]

    session_factory = callback.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        shared = await repo.get_shared_watchlist_by_token(token)
        if not shared:
            await callback.message.edit_text("❌ Список не найден.")
            return

        try:
            items_snapshot = json.loads(shared.items_snapshot)
        except Exception:
            items_snapshot = []

        user_items = await repo.get_user_items(callback.from_user.id)
        tracked_keys = {(it.media_type, it.tmdb_id) for it in user_items}

    text = format_shared_watchlist_message(items_snapshot, shared.title)
    reply_markup = shared_watchlist_recipient_keyboard(token, items_snapshot, tracked_keys)
    await callback.message.edit_text(text, reply_markup=reply_markup)
