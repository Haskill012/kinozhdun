"""Хендлеры для добавления, удаления и настройки отслеживаемых элементов."""

import datetime
import logging

from aiogram import Router, F
from aiogram.filters import Command, or_f
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.db.repositories import Repository
from bot.keyboards.inline import (
    search_results_keyboard,
    user_items_keyboard,
    confirm_remove_keyboard,
)
from bot.keyboards.reply import main_menu_keyboard
from bot.utils.formatting import (
    format_item_details,
    format_search_results_message,
    format_date_ru,
)

logger = logging.getLogger(__name__)

router = Router(name="tracking_router")

MENU_BUTTON_TEXTS = {
    "🔍 Найти сериал / фильм",
    "📋 Мой список",
    "🔄 Проверить статус",
    "📅 Указать дату",
    "🗑 Удалить из списка",
    "ℹ️ Справка",
}


class DateState(StatesGroup):
    """Состояния FSM для ввода даты пользователем."""
    waiting_for_date = State()


# --- Кнопка меню «Поиск» ---

@router.message(F.text == "🔍 Найти сериал / фильм")
async def btn_search_prompt(message: Message) -> None:
    """Подсказка при нажатии кнопки поиска в меню."""
    await message.answer(
        "🔍 <b>Поиск фильма или сериала</b>\n\n"
        "Напишите в ответ название проекта, который вы ждёте "
        "(например: <i>Ведьмак</i>, <i>Мандалорец</i> или <i>Дюна</i>):",
        reply_markup=main_menu_keyboard(),
    )


# --- Поиск по произвольному тексту ---

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_(MENU_BUTTON_TEXTS))
async def process_search(message: Message) -> None:
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

    text = format_search_results_message(query, results)
    reply_markup = search_results_keyboard(results)

    await search_status_msg.edit_text(text, reply_markup=reply_markup)


# --- Добавление в отслеживание ---

@router.callback_query(F.data.startswith("track:"))
async def process_track_item(callback: CallbackQuery) -> None:
    """Добавление выбранного элемента в список отслеживания."""
    await callback.answer()
    _, media_type, tmdb_id_str = callback.data.split(":")
    tmdb_id = int(tmdb_id_str)

    session_factory = callback.bot["session_factory"]
    tmdb_client = callback.bot["tmdb_client"]
    settings = callback.bot["settings"]

    async with session_factory() as session:
        repo = Repository(session)
        user = await repo.get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
        )

        # Проверка: уже отслеживается?
        if await repo.is_already_tracking(callback.from_user.id, tmdb_id, media_type):
            await callback.message.edit_text("ℹ️ Вы уже отслеживаете этот проект.")
            return

        # Проверка лимита
        items = await repo.get_user_items(callback.from_user.id)
        if len(items) >= settings.MAX_ITEMS_PER_USER:
            await callback.message.edit_text(
                f"⚠️ Достигнут лимит отслеживания ({settings.MAX_ITEMS_PER_USER} проектов). "
                "Удалите ненужные тайтлы кнопкой «🗑 Удалить из списка»."
            )
            return

        # Получаем полные детали из TMDB
        if media_type == "tv":
            details = await tmdb_client.get_tv_details(tmdb_id)
        else:
            details = await tmdb_client.get_movie_details(tmdb_id)

        if not details:
            await callback.message.edit_text("❌ Не удалось получить информацию о проекте.")
            return

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
            next_ep = details.get("next_episode_to_air")
            if next_ep and next_ep.get("air_date"):
                try:
                    next_air_date = datetime.date.fromisoformat(next_ep["air_date"])
                except (ValueError, TypeError):
                    pass
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

        item = await repo.add_tracked_item(
            user_id=user.id,
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

        text = f"✅ <b>{title}</b> успешно добавлен в ваш список ожидания!\n\n"
        text += format_item_details(item)
        await callback.message.edit_text(text)


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

@router.message(or_f(Command("setdate"), F.text == "📅 Указать дату"))
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

    text = message.text.strip()
    try:
        parsed_date = datetime.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат даты!</b>\n"
            "Пожалуйста, введите дату строго в формате <b>ДД.ММ.ГГГГ</b> (например: <code>15.03.2027</code>):"
        )
        return

    session_factory = message.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        await repo.set_custom_date(item_id, parsed_date)
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Дата премьеры <b>{format_date_ru(parsed_date)}</b> успешно сохранена!\n"
        "Бот напомнит вам о ней за 3 дня до выхода 🍿",
        reply_markup=main_menu_keyboard(),
    )
