"""Хендлеры для просмотра списка отслеживаемых элементов и проверки их статуса."""

import datetime
from aiogram import Router, F
from aiogram.filters import Command, or_f
from aiogram.types import Message, CallbackQuery

from bot.db.repositories import Repository
from bot.keyboards.inline import user_items_keyboard, back_to_list_keyboard
from bot.keyboards.reply import main_menu_keyboard
from bot.utils.formatting import format_item_list, format_item_details

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


@router.message(or_f(Command("list"), F.text == "📋 Мой список"))
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
