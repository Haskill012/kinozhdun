"""Хендлеры для поиска, предпросмотра, добавления, удаления и настройки отслеживаемых элементов."""

from bot.services.season_dates import upcoming_season
from shared.viewing import viewing_state

import datetime
import logging
from typing import Any, Optional

from aiogram import Router, F
from aiogram.filters import Command, or_f
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.db.repositories import Repository
from bot.keyboards.inline import (
    search_results_keyboard,
    preview_item_keyboard,
    track_success_keyboard,
    user_items_keyboard,
    confirm_remove_keyboard,
)
from bot.keyboards.reply import main_menu_keyboard
from bot.services.analytics import AnalyticsService
from bot.utils.formatting import (
    linked_title,
    format_item_details,
    format_search_results_message,
    format_date_ru,
    safe_html,
)

logger = logging.getLogger(__name__)

router = Router(name="tracking_router")

MENU_BUTTON_TEXTS = {
    "🔍 Найти фильм / сериал",
    "🔍 Найти сериал / фильм",
    "🍿 Мой Кинождун",
    "🍿 Мой список ожидания",
    "📋 Мой список",
    "🔄 Проверить статус",
    "📅 Своя дата",
    "📅 Указать дату",
    "🗑 Удалить из списка",
    "ℹ️ Справка и помощь",
    "ℹ️ Справка",
}


class DateState(StatesGroup):
    """Состояния FSM для ввода даты пользователем."""
    waiting_for_date = State()


# --- Кнопка меню «Поиск» ---

@router.message(or_f(F.text == "🔍 Найти фильм / сериал", F.text == "🔍 Найти сериал / фильм"))
async def btn_search_prompt(message: Message) -> None:
    """Подсказка при нажатии кнопки поиска в меню."""
    await message.answer(
        "🔍 <b>Поиск фильма или сериала</b>\n\n"
        "Напишите в ответ название проекта, который вы ждёте.\n"
        "<i>Например: Ведьмак, Мандалорец, Дюна, Пацаны...</i>",
        reply_markup=main_menu_keyboard(),
    )


# --- Поиск по произвольному тексту ---

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_(MENU_BUTTON_TEXTS))
async def process_search(message: Message, state: FSMContext) -> None:
    """Поиск фильма/сериала по тексту сообщения."""
    tmdb_client = message.bot["tmdb_client"]
    query = message.text.strip()

    search_status_msg = await message.answer("🔎 Ищу на TMDB...")

    results = await tmdb_client.search_multi(query)

    if not results:
        await search_status_msg.edit_text(
            f"🔍 По запросу <b>«{query}»</b> ничего не найдено.\n"
            "Попробуйте уточнить название или проверьте опечатки."
        )
        return

    # Сохраняем результаты поиска в состояние для возможности возврата назад
    await state.update_data(last_query=query, last_results=results)

    text = format_search_results_message(query, results)
    reply_markup = search_results_keyboard(results)

    await search_status_msg.edit_text(text, reply_markup=reply_markup)


# --- Карточка предпросмотра с кнопкой «Добавить в отслеживание» ---

@router.callback_query(F.data.startswith("preview:"))
async def process_preview_item(callback: CallbackQuery) -> None:
    """Показывает подробную карточку выбранного проекта с явной кнопкой добавления в отслеживание."""
    await callback.answer()
    _, media_type, tmdb_id_str = callback.data.split(":")
    tmdb_id = int(tmdb_id_str)

    session_factory = callback.bot["session_factory"]
    tmdb_client = callback.bot["tmdb_client"]

    if media_type == "tv":
        details = await tmdb_client.get_tv_details(tmdb_id)
    else:
        details = await tmdb_client.get_movie_details(tmdb_id)

    if not details:
        await callback.message.edit_text("❌ Не удалось получить информацию о проекте.")
        return

    # Проверяем, отслеживается ли проект уже пользователем
    async with session_factory() as session:
        repo = Repository(session)
        is_tracked = await repo.is_already_tracking(callback.from_user.id, tmdb_id, media_type)
        tracked_item_id = None
        if is_tracked:
            items = await repo.get_user_items(callback.from_user.id)
            match = next((i for i in items if i.tmdb_id == tmdb_id and i.media_type == media_type), None)
            if match:
                tracked_item_id = match.id

    title = details.get("title") or details.get("name") or "Без названия"
    settings = callback.bot["settings"]
    text = "🔍 <b>Карточка выбранного проекта:</b>\n\n" + format_item_details(details, media_type)
    reply_markup = preview_item_keyboard(
        media_type=media_type,
        tmdb_id=tmdb_id,
        is_already_tracked=is_tracked,
        tracked_item_id=tracked_item_id,
        bot_username=settings.BOT_USERNAME,
        title=title,
        referrer_id=callback.from_user.id,
        action_label=viewing_state(dict(details, media_type=media_type))['label'],
    )
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- Возврат назад к результатам поиска ---

@router.callback_query(F.data == "back_to_search")
async def process_back_to_search(callback: CallbackQuery, state: FSMContext) -> None:
    """Возвращает пользователя обратно к списку найденных вариантов."""
    await callback.answer()
    data = await state.get_data()
    last_query = data.get("last_query")
    last_results = data.get("last_results")

    if last_query and last_results:
        text = format_search_results_message(last_query, last_results)
        reply_markup = search_results_keyboard(last_results)
        await callback.message.edit_text(text, reply_markup=reply_markup)
    else:
        await callback.message.edit_text(
            "🔍 Введите название фильма или сериала для нового поиска."
        )


@router.callback_query(F.data == "already_tracked")
async def process_already_tracked(callback: CallbackQuery) -> None:
    """Информационное оповещение, если проект уже отслеживается."""
    await callback.answer("Этот проект уже находится в вашем списке ожидания! 🍿", show_alert=True)


# --- Подтверждение добавления в отслеживание ---

async def save_single_tracked_item(
    user_id: int,
    telegram_id: int,
    media_type: str,
    tmdb_id: int,
    session_factory: Any,
    tmdb_client: Any,
    settings: Any,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """Вспомогательная функция для добавления тайтла в отслеживание с проверками."""
    async with session_factory() as session:
        repo = Repository(session)

        # 1. Проверка: уже отслеживается?
        if await repo.is_already_tracking(telegram_id, tmdb_id, media_type):
            return False, "already_tracked", None

        # 2. Проверка лимита
        items = await repo.get_user_items(telegram_id)
        if len(items) >= settings.MAX_ITEMS_PER_USER:
            return False, "limit_exceeded", None

        # 3. Получаем детали из TMDB
        if media_type == "tv":
            details = await tmdb_client.get_tv_details(tmdb_id)
        else:
            details = await tmdb_client.get_movie_details(tmdb_id)

        if not details:
            return False, "not_found", None

        title = details.get("title", "Без названия")
        original_title = details.get("original_title")
        poster_path = details.get("poster_path")
        tmdb_url = details.get("tmdb_url", "")
        network = details.get("network")

        last_known_season = None
        last_known_air_date = None
        next_air_date = None

        if media_type == "tv":
            last_known_season = details.get("number_of_seasons")
            last_ep = details.get("last_episode_to_air")
            if last_ep and last_ep.get("air_date"):
                try:
                    last_known_air_date = datetime.date.fromisoformat(last_ep["air_date"])
                except (ValueError, TypeError):
                    pass
            next_air_date = upcoming_season(details)[1]
        else:
            release = details.get("release_date")
            if release:
                try:
                    rd = datetime.date.fromisoformat(release)
                    if rd > datetime.date.today():
                        next_air_date = rd
                    else:
                        last_known_air_date = rd
                except (ValueError, TypeError):
                    pass

        await repo.add_tracked_item(
            user_id=user_id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            title=title,
            original_title=original_title,
            poster_path=poster_path,
            last_known_season=last_known_season,
            last_known_air_date=last_known_air_date,
            next_air_date=next_air_date,
            tmdb_url=tmdb_url,
            network=network,
        )
        await session.commit()

        return True, "ok", {
            "title": title,
            "network": network,
            "next_air_date": next_air_date,
            "viewing": viewing_state(dict(details, media_type=media_type)),
        }


# --- Подтверждение добавления в отслеживание ---

@router.callback_query(or_f(F.data.startswith("confirm_track:"), F.data.startswith("track:")))
async def process_confirm_track(callback: CallbackQuery) -> None:
    """Фактическое сохранение проекта в базу данных по нажатию кнопки «Добавить в отслеживание»."""
    await callback.answer()
    parts = callback.data.split(":")
    media_type = parts[1]
    tmdb_id = int(parts[2])

    session_factory = callback.bot["session_factory"]
    tmdb_client = callback.bot["tmdb_client"]
    settings = callback.bot["settings"]
    analytics = AnalyticsService(session_factory)

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )
        user_id = user.id
        await session.commit()

    success, reason, info = await save_single_tracked_item(
        user_id=user_id,
        telegram_id=callback.from_user.id,
        media_type=media_type,
        tmdb_id=tmdb_id,
        session_factory=session_factory,
        tmdb_client=tmdb_client,
        settings=settings,
    )

    if not success:
        if reason == "already_tracked":
            await callback.message.edit_text("ℹ️ Этот проект уже находится в вашем списке ожидания.")
        elif reason == "limit_exceeded":
            await callback.message.edit_text(
                f"⚠️ Достигнут лимит отслеживания ({settings.MAX_ITEMS_PER_USER} проектов). "
                "Удалите ненужные тайтлы кнопкой «🗑 Удалить из списка»."
            )
        else:
            await callback.message.edit_text("❌ Не удалось получить информацию о проекте.")
        return

    title = info["title"]
    action = info['viewing']
    text = (
        f"✅ <b>«{linked_title(title, {'media_type': media_type, 'tmdb_id': tmdb_id})}»</b> сохранён в вашем списке.\n\n"
        f"<b>{safe_html(action['status'])}</b>\n{safe_html(action['note'])}"
    )
    reply_markup = track_success_keyboard(
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        bot_username=settings.BOT_USERNAME,
        referrer_id=callback.from_user.id,
    )
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- Добавление по виральной ссылке шеринга контента ---

@router.callback_query(F.data.startswith("track_from_share:"))
async def process_track_from_share(callback: CallbackQuery) -> None:
    """Добавление фильма/сериала получателем ссылки расшаривания контента."""
    await callback.answer()
    parts = callback.data.split(":")
    media_type = parts[1]
    tmdb_id = int(parts[2])
    referrer_id = int(parts[3]) if len(parts) > 3 and parts[3] else None

    session_factory = callback.bot["session_factory"]
    tmdb_client = callback.bot["tmdb_client"]
    settings = callback.bot["settings"]
    analytics = AnalyticsService(session_factory)

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            referral_source=f"share_content:{media_type}:{tmdb_id}",
            referrer_id=referrer_id,
        )
        user_id = user.id
        await session.commit()

    success, reason, info = await save_single_tracked_item(
        user_id=user_id,
        telegram_id=callback.from_user.id,
        media_type=media_type,
        tmdb_id=tmdb_id,
        session_factory=session_factory,
        tmdb_client=tmdb_client,
        settings=settings,
    )

    if not success:
        if reason == "already_tracked":
            await callback.message.edit_text("ℹ️ Этот проект уже находится в вашем списке ожидания 🍿")
        elif reason == "limit_exceeded":
            await callback.message.edit_text(
                f"⚠️ Достигнут лимит отслеживания ({settings.MAX_ITEMS_PER_USER} проектов)."
            )
        else:
            await callback.message.edit_text("❌ Не удалось получить информацию о проекте.")
        return

    # Логируем аналитическое событие
    await analytics.log_content_followed_from_share(callback.from_user.id, media_type, tmdb_id, referrer_id)

    title = info["title"]
    action = info['viewing']
    text = (
        f"✅ <b>«{linked_title(title, {'media_type': media_type, 'tmdb_id': tmdb_id})}»</b> сохранён в вашем списке.\n\n"
        f"<b>{safe_html(action['status'])}</b>\n{safe_html(action['note'])}"
    )
    reply_markup = track_success_keyboard(
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        bot_username=settings.BOT_USERNAME,
        referrer_id=callback.from_user.id,
    )
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- Добавление по ссылке из Telegram-канала ---

@router.callback_query(F.data.startswith("track_from_channel:"))
async def process_track_from_channel(callback: CallbackQuery) -> None:
    """Добавление проекта в отслеживание после перехода из Telegram-канала."""
    await callback.answer()
    parts = callback.data.split(":")
    post_id = int(parts[1])
    media_type = parts[2]
    tmdb_id = int(parts[3])

    session_factory = callback.bot["session_factory"]
    tmdb_client = callback.bot["tmdb_client"]
    settings = callback.bot["settings"]
    analytics = AnalyticsService(session_factory)

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            referral_source=f"telegram_channel:{post_id}",
        )
        user_id = user.id
        await session.commit()

    success, reason, info = await save_single_tracked_item(
        user_id=user_id,
        telegram_id=callback.from_user.id,
        media_type=media_type,
        tmdb_id=tmdb_id,
        session_factory=session_factory,
        tmdb_client=tmdb_client,
        settings=settings,
    )

    if not success:
        if reason == "already_tracked":
            await callback.message.edit_text("ℹ️ Этот проект уже находится в вашем списке ожидания 🍿")
        elif reason == "limit_exceeded":
            await callback.message.edit_text(
                f"⚠️ Достигнут лимит отслеживания ({settings.MAX_ITEMS_PER_USER} проектов)."
            )
        else:
            await callback.message.edit_text("❌ Не удалось получить информацию о проекте.")
        return

    # Логируем событие
    await analytics.log_content_followed_from_channel(callback.from_user.id, post_id, media_type, tmdb_id)

    title = info["title"]
    action = info['viewing']
    text = (
        f"✅ <b>«{linked_title(title, {'media_type': media_type, 'tmdb_id': tmdb_id})}»</b> сохранён в вашем списке.\n\n"
        f"<b>{safe_html(action['status'])}</b>\n{safe_html(action['note'])}"
    )
    reply_markup = track_success_keyboard(
        media_type=media_type,
        tmdb_id=tmdb_id,
        title=title,
        bot_username=settings.BOT_USERNAME,
        referrer_id=callback.from_user.id,
    )
    await callback.message.edit_text(text, reply_markup=reply_markup)


# --- Отмена поиска ---

@router.callback_query(F.data == "cancel_search")
async def cancel_search(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена текущего поиска / действия."""
    await state.clear()
    await callback.answer()
    await callback.message.delete()


# --- Удаление ---

@router.message(or_f(Command("remove"), F.text == "🗑 Удалить из списка"))
async def cmd_remove(message: Message) -> None:
    """Показать список для удаления элемента из отслеживания."""
    session_factory = message.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        await repo.get_or_create_user(
            message.from_user.id, message.from_user.username, message.from_user.first_name
        )
        items = await repo.get_user_items(message.from_user.id)

        if not items:
            await message.answer("📭 Ваш список отслеживания пуст.", reply_markup=main_menu_keyboard())
            return

        await message.answer(
            "🗑 Выберите проект для удаления из списка:",
            reply_markup=user_items_keyboard(items, action="remove"),
        )


@router.callback_query(F.data.startswith("remove:"))
async def process_remove_btn(callback: CallbackQuery) -> None:
    """Запрос подтверждения удаления."""
    await callback.answer()
    item_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⚠️ Вы уверены, что хотите удалить этот проект из отслеживания?",
        reply_markup=confirm_remove_keyboard(item_id),
    )


@router.callback_query(F.data.startswith("confirm_remove:"))
async def confirm_remove(callback: CallbackQuery) -> None:
    """Подтверждение удаления элемента."""
    await callback.answer()
    item_id = int(callback.data.split(":")[1])
    session_factory = callback.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        removed = await repo.remove_tracked_item(item_id, callback.from_user.id)
        await session.commit()

    if removed:
        await callback.message.edit_text("✅ Проект удалён из вашего списка ожидания.")
    else:
        await callback.message.edit_text("❌ Элемент не найден или уже удалён.")


@router.callback_query(F.data == "cancel_remove")
async def cancel_remove(callback: CallbackQuery) -> None:
    """Отмена удаления."""
    await callback.answer()
    await callback.message.delete()


# --- Установка своей даты ---

@router.message(or_f(Command("setdate"), F.text == "📅 Своя дата", F.text == "📅 Указать дату"))
async def cmd_setdate(message: Message) -> None:
    """Показать список для установки пользовательской даты."""
    session_factory = message.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        await repo.get_or_create_user(
            message.from_user.id, message.from_user.username, message.from_user.first_name
        )
        items = await repo.get_user_items(message.from_user.id)

        if not items:
            await message.answer("📭 Ваш список пуст. Сначала добавьте сериал или фильм.", reply_markup=main_menu_keyboard())
            return

        await message.answer(
            "📅 Выберите проект, для которого хотите вручную указать дату премьеры:",
            reply_markup=user_items_keyboard(items, action="setdate"),
        )


@router.callback_query(F.data.startswith("setdate:"))
async def process_setdate_btn(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрос ввода даты пользователем (FSM)."""
    await callback.answer()
    item_id = int(callback.data.split(":")[1])
    async with callback.bot["session_factory"]() as session:
        item = await Repository(session).get_tracked_item(item_id)
        if not item or not item.user or item.user.telegram_id != callback.from_user.id:
            await state.clear()
            await callback.message.edit_text("Этот проект недоступен. Выберите проект из своего списка ожидания.")
            return
    await state.update_data(item_id=item_id)
    await state.set_state(DateState.waiting_for_date)
    await callback.message.edit_text(
        "📅 Введите желаемую дату в формате <b>ДД.ММ.ГГГГ</b>\n"
        "(например: <code>15.03.2027</code>):"
    )


@router.message(DateState.waiting_for_date)
async def process_date_input(message: Message, state: FSMContext) -> None:
    """Обработка введённой пользователем даты."""
    data = await state.get_data()
    item_id = data.get("item_id")
    if not item_id:
        await state.clear()
        await message.answer("Выберите проект в своём списке и укажите дату ещё раз.")
        return

    text = message.text.strip()
    try:
        parsed_date = datetime.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат даты!</b>\n"
            "Пожалуйста, введите дату строго в формате <b>ДД.ММ.ГГГГ</b> (например: <code>15.03.2027</code>):"
        )
        return

    if parsed_date < datetime.date.today():
        await message.answer("Эта дата уже прошла. Укажите сегодняшнюю или будущую дату.")
        return

    session_factory = message.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        saved = await repo.set_custom_date(item_id, parsed_date, message.from_user.id)
        await session.commit()

    await state.clear()
    if not saved:
        await message.answer("Этот проект недоступен. Выберите проект из своего списка ожидания.")
        return
    await message.answer(
        f"✅ Дата премьеры <b>{format_date_ru(parsed_date)}</b> успешно сохранена!\n"
        + ("Бот напомнит вам о ней за 3 дня до выхода 🍿" if parsed_date >= datetime.date.today() + datetime.timedelta(days=3)
         else "До премьеры меньше трёх дней — дата сохранена в вашем списке 🍿"),
        reply_markup=main_menu_keyboard(),
    )
