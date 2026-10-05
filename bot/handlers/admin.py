"""Административная панель для модерации очереди публикаций и аналитики Telegram-канала."""

import logging
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import Settings
from bot.db.repositories import Repository
from bot.services.channel import ChannelPublisher
from bot.utils.formatting import format_date_ru

logger = logging.getLogger(__name__)

router = Router(name="admin_router")


class AdminEditPostState(StatesGroup):
    """FSM состояния для редактирования текста публикации."""
    waiting_for_text = State()


def is_admin(user_id: int, settings: Settings) -> bool:
    """Проверяет, входит ли пользователь в список администраторов."""
    return user_id in settings.ADMIN_USER_IDS


def format_pending_post_card(post, current_index: int, total_count: int) -> str:
    """Форматирует карточку публикации для модерации администратором."""
    date_str = format_date_ru(post.air_date) if post.air_date else "не указана"
    return (
        f"📋 <b>Очередь публикаций ({current_index + 1} из {total_count})</b>\n\n"
        f"🎬 <b>{post.title}</b>\n"
        f"🏷 <b>Событие:</b> <code>{post.event_type}</code>\n"
        f"🌐 <b>Источник:</b> {post.source} (статус: <i>{post.credibility}</i>)\n"
        f"📅 <b>Дата:</b> {date_str}\n\n"
        "<b>Текст публикации:</b>\n"
        f"{post.post_text or '—'}\n"
    )


def pending_post_admin_keyboard(post_id: int, current_index: int, total_count: int) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру модерации для публикации."""
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"admin_pub:{post_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_rej:{post_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"admin_edt:{post_id}"),
        ],
    ]

    # Навигация по очереди
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Предыдущий", callback_data=f"admin_q:{current_index - 1}"))
    if current_index + 1 < total_count:
        nav_buttons.append(InlineKeyboardButton(text="➡️ Следующий", callback_data=f"admin_q:{current_index + 1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="admin_q:0")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("admin"))
@router.message(Command("queue"))
async def cmd_admin_queue(message: Message, state: FSMContext) -> None:
    """Просмотр очереди публикаций, ожидающих модерации."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        return

    await state.clear()
    session_factory = message.bot["session_factory"]

    async with session_factory() as session:
        repo = Repository(session)
        total_count = await repo.get_pending_channel_posts_count()

        if total_count == 0:
            mode_label = "AUTO MODE (автопостинг)" if settings.CHANNEL_AUTO_PUBLISH else "SAFE MODE (ручная модерация)"
            await message.answer(
                f"📭 <b>Очередь публикаций пуста!</b>\n\n"
                f"Все подготовленные публикации проверены.\n"
                f"Текущий режим: <b>{mode_label}</b>\n\n"
                "<b>Управление каналом:</b>\n"
                "• <code>/channel_test</code> — проверить права бота в канале\n"
                "• <code>/channel_digest</code> — опубликовать дайджест на сегодня\n"
                "• <code>/channel_weekly</code> — опубликовать дайджест недели\n"
                "• <code>/channel_check</code> — запустить поиск обновлений TMDB\n"
                "• <code>/stats</code> — посмотреть аналитику канала",
            )
            return

        post = await repo.get_pending_channel_post_by_index(0)
        if not post:
            await message.answer("📭 В очереди нет активных записей.")
            return

        text = format_pending_post_card(post, 0, total_count)
        kb = pending_post_admin_keyboard(post.id, 0, total_count)
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin_q:"))
async def process_queue_navigation(callback: CallbackQuery) -> None:
    """Навигация по очереди публикаций."""
    settings: Settings = callback.bot["settings"]
    if not is_admin(callback.from_user.id, settings):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return

    await callback.answer()
    offset = int(callback.data.split(":")[1])
    session_factory = callback.bot["session_factory"]

    async with session_factory() as session:
        repo = Repository(session)
        total_count = await repo.get_pending_channel_posts_count()

        if total_count == 0:
            await callback.message.edit_text("📭 В очереди публикаций больше нет записей!")
            return

        if offset >= total_count:
            offset = 0

        post = await repo.get_pending_channel_post_by_index(offset)
        if not post:
            await callback.message.edit_text("📭 Публикация не найдена.")
            return

        text = format_pending_post_card(post, offset, total_count)
        kb = pending_post_admin_keyboard(post.id, offset, total_count)
        await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("admin_pub:"))
async def process_admin_publish(callback: CallbackQuery) -> None:
    """Одобрение и немедленная публикация поста в канал."""
    settings: Settings = callback.bot["settings"]
    if not is_admin(callback.from_user.id, settings):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return

    await callback.answer("Публикую в канал...")
    post_id = int(callback.data.split(":")[1])
    session_factory = callback.bot["session_factory"]

    publisher = ChannelPublisher(session_factory, settings, callback.bot)
    success = await publisher.publish_post_by_id(post_id)

    if success:
        await callback.message.edit_text(
            f"✅ <b>Публикация #{post_id} успешно отправлена в канал!</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📋 К очереди", callback_data="admin_q:0")]]
            ),
        )
    else:
        await callback.message.edit_text(
            f"❌ <b>Не удалось опубликовать #{post_id}.</b> Проверьте логи и права бота в канале.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📋 К очереди", callback_data="admin_q:0")]]
            ),
        )


@router.callback_query(F.data.startswith("admin_rej:"))
async def process_admin_reject(callback: CallbackQuery) -> None:
    """Отклонение поста из очереди."""
    settings: Settings = callback.bot["settings"]
    if not is_admin(callback.from_user.id, settings):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return

    await callback.answer("Отклоняю...")
    post_id = int(callback.data.split(":")[1])
    session_factory = callback.bot["session_factory"]

    async with session_factory() as session:
        repo = Repository(session)
        await repo.update_channel_post_status(post_id, "rejected")
        await session.commit()

    await callback.message.edit_text(
        f"❌ <b>Публикация #{post_id} отклонена.</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📋 К очереди", callback_data="admin_q:0")]]
        ),
    )


@router.callback_query(F.data.startswith("admin_edt:"))
async def process_admin_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало процесса редактирования текста публикации."""
    settings: Settings = callback.bot["settings"]
    if not is_admin(callback.from_user.id, settings):
        await callback.answer("У вас нет прав администратора.", show_alert=True)
        return

    await callback.answer()
    post_id = int(callback.data.split(":")[1])

    await state.set_state(AdminEditPostState.waiting_for_text)
    await state.update_data(editing_post_id=post_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_cancel_edt:{post_id}")]]
    )

    await callback.message.reply(
        f"✏️ <b>Редактирование публикации #{post_id}</b>\n\n"
        "Отправьте в чат новый текст для этого поста (поддерживается HTML-разметка):",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("admin_cancel_edt:"))
async def process_admin_edit_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена редактирования текста."""
    await callback.answer("Редактирование отменено.")
    await state.clear()
    await callback.message.delete()


@router.message(StateFilter(AdminEditPostState.waiting_for_text))
async def process_admin_edited_text(message: Message, state: FSMContext) -> None:
    """Сохранение отредактированного текста публикации."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        return

    data = await state.get_data()
    post_id = data.get("editing_post_id")
    await state.clear()

    if not post_id:
        await message.answer("Ошибка: ID публикации не найден.")
        return

    new_text = message.text or message.caption or ""
    session_factory = message.bot["session_factory"]

    async with session_factory() as session:
        repo = Repository(session)
        await repo.update_channel_post_text(post_id, new_text)
        await session.commit()
        post = await repo.get_channel_post(post_id)

    if not post:
        await message.answer("Публикация не найдена.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Опубликовать сейчас", callback_data=f"admin_pub:{post.id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_rej:{post.id}"),
            ],
            [
                InlineKeyboardButton(text="📋 К очереди", callback_data="admin_q:0"),
            ],
        ]
    )

    await message.answer(
        f"✅ <b>Текст публикации #{post_id} успешно обновлён!</b>\n\n"
        f"<b>Новый текст:</b>\n{new_text}",
        reply_markup=kb,
    )


@router.message(Command("channel_test"))
async def cmd_channel_test(message: Message) -> None:
    """Тестовая публикация в канал для проверки прав администратора."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        return

    session_factory = message.bot["session_factory"]
    publisher = ChannelPublisher(session_factory, settings, message.bot)

    status_msg = await message.answer("🔄 Отправляю тестовое сообщение в канал...")
    result = await publisher.publish_test_post()

    if result.get("success"):
        await status_msg.edit_text(
            f"✅ <b>Тестовое сообщение успешно опубликовано!</b>\n"
            f"Канал: <code>{result.get('channel')}</code>\n"
            f"Message ID: <code>{result.get('message_id')}</code>"
        )
    else:
        await status_msg.edit_text(
            f"❌ <b>Ошибка отправки в канал!</b>\n"
            f"Канал: <code>{result.get('channel')}</code>\n"
            f"Причина: <code>{result.get('error')}</code>\n\n"
            "Убедитесь, что:\n"
            "1. Бот добавлен в канал как Администратор;\n"
            "2. У бота включено право «Публикация сообщений»;\n"
            "3. В .env файле корректно указан <code>TELEGRAM_CHANNEL_ID</code>."
        )


@router.message(Command("stats"))
@router.message(Command("channel_stats"))
async def cmd_channel_stats(message: Message) -> None:
    """Сводка аналитики по Telegram-каналу."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        return

    session_factory = message.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        stats = await repo.get_channel_analytics_summary()

    mode_label = "AUTO MODE (автопостинг)" if settings.CHANNEL_AUTO_PUBLISH else "SAFE MODE (ручная модерация)"
    posting_label = "Включён ✅" if settings.CHANNEL_POSTING_ENABLED else "Отключён ❌"

    text = (
        "📊 <b>Аналитика Telegram-канала «Кинождун 🍿»</b>\n\n"
        f"⚙️ <b>Режим канала:</b> {mode_label}\n"
        f"📢 <b>Публикации:</b> {posting_label}\n"
        f"⏱ <b>Интервал антиспама:</b> {settings.CHANNEL_MIN_POST_INTERVAL_MINUTES} мин.\n\n"
        f"📝 <b>Опубликовано постов:</b> <b>{stats['posts_count']}</b>\n"
        f"🔗 <b>Переходов в бота:</b> <b>{stats['opens_count']}</b>\n"
        f"👤 <b>Уникальных пользователей:</b> <b>{stats['unique_users']}</b>\n"
        f"🔔 <b>Добавлено тайтлов в трекер:</b> <b>{stats['follows_count']}</b>\n"
        f"📈 <b>Конверсия воронки:</b> <b>{stats['conversion_rate']}%</b>\n\n"
        "💡 <i>Воронка: канал -> переход в бота -> нажатие «Отслеживать»</i>"
    )
    await message.answer(text)


@router.message(Command("mode"))
async def cmd_mode(message: Message) -> None:
    """Отображение текущего режима публикации канала."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        return

    mode = "AUTO MODE (автопостинг)" if settings.CHANNEL_AUTO_PUBLISH else "SAFE MODE (ручная модерация)"
    instructions = (
        f"⚙️ <b>Текущий режим канала:</b> <b>{mode}</b>\n\n"
        "• <b>SAFE MODE</b>: бот готовит подборки и дайджесты, формирует посты и кладёт в очередь <code>/queue</code>. Администратор проверяет и публикует кнопкой «✅ Опубликовать».\n"
        "• <b>AUTO MODE</b>: подборки и дайджесты публикуются в канал автоматически с соблюдением интервала антиспама.\n\n"
        "Для переключения режима измените в <code>.env</code>:\n"
        "<code>CHANNEL_AUTO_PUBLISH=true</code> (или <code>false</code>)\n"
        "и перезапустите бота."
    )
    await message.answer(instructions)


@router.message(Command("channel_digest", "digest_today", "digest"))
async def cmd_channel_digest(message: Message) -> None:
    """Генерация и публикация утреннего дайджеста «Что выходит сегодня»."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        await message.answer(f"⛔ Команда доступна только администраторам (ваш ID: <code>{message.from_user.id}</code>).")
        return

    session_factory = message.bot["session_factory"]
    tmdb_client = getattr(message.bot, "tmdb_client", None)
    publisher = ChannelPublisher(session_factory, settings, message.bot, tmdb_client=tmdb_client)

    status_msg = await message.answer("🔄 Формирую дайджест «Что выходит сегодня»...")
    try:
        post = await publisher.create_daily_digest()
        if not post:
            await status_msg.edit_text("ℹ️ На сегодня не найдено запланированных релизов в каталоге для дайджеста.")
            return

        if post.status == "published":
            await status_msg.edit_text(f"✅ <b>Дайджест успешно опубликован в канале!</b>\nID: <code>{post.id}</code>")
        else:
            published = await publisher.publish_post_by_id(post.id)
            if published:
                await status_msg.edit_text(f"✅ <b>Дайджест #{post.id} успешно опубликован в канале!</b>")
            else:
                await status_msg.edit_text(f"⚠️ Дайджест #{post.id} создан и находится в /queue. Проверьте права бота в канале.")
    except Exception as e:
        logger.error(f"Ошибка в cmd_channel_digest: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Ошибка генерации дайджеста:</b> <code>{e}</code>")


@router.message(Command("channel_weekly", "digest_weekly", "weekly"))
async def cmd_channel_weekly(message: Message) -> None:
    """Генерация и публикация еженедельного дайджеста «Главные премьеры недели»."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        await message.answer(f"⛔ Команда доступна только администраторам (ваш ID: <code>{message.from_user.id}</code>).")
        return

    session_factory = message.bot["session_factory"]
    tmdb_client = getattr(message.bot, "tmdb_client", None)
    publisher = ChannelPublisher(session_factory, settings, message.bot, tmdb_client=tmdb_client)

    status_msg = await message.answer("🔄 Формирую еженедельный дайджест «Главные премьеры недели»...")
    try:
        post = await publisher.create_weekly_digest()
        if not post:
            await status_msg.edit_text("ℹ️ На эту неделю не найдено достаточного количества релизов (минимум 2).")
            return

        if post.status == "published":
            await status_msg.edit_text(f"✅ <b>Еженедельный дайджест успешно опубликован в канале!</b>\nID: <code>{post.id}</code>")
        else:
            published = await publisher.publish_post_by_id(post.id)
            if published:
                await status_msg.edit_text(f"✅ <b>Еженедельный дайджест #{post.id} успешно опубликован в канале!</b>")
            else:
                await status_msg.edit_text(f"⚠️ Еженедельный дайджест #{post.id} создан и находится в /queue.")
    except Exception as e:
        logger.error(f"Ошибка в cmd_channel_weekly: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Ошибка генерации еженедельного дайджеста:</b> <code>{e}</code>")


@router.message(Command("channel_check", "force_check", "check"))
async def cmd_channel_check(message: Message) -> None:
    """Принудительный запуск фоновой проверки обновлений каталога TMDB."""
    settings: Settings = message.bot["settings"]
    if not is_admin(message.from_user.id, settings):
        await message.answer(f"⛔ Команда доступна только администраторам (ваш ID: <code>{message.from_user.id}</code>).")
        return

    session_factory = message.bot["session_factory"]
    tmdb_client = getattr(message.bot, "tmdb_client", None)
    if not tmdb_client:
        await message.answer("❌ TMDB клиент недоступен.")
        return

    status_msg = await message.answer("🔄 Запускаю проверку обновлений каталога TMDB...")
    from bot.scheduler.jobs import check_updates_job
    try:
        await check_updates_job(message.bot, session_factory, tmdb_client, settings)
        await status_msg.edit_text("✅ <b>Проверка обновлений завершена!</b>\nВсе подтверждённые новинки обработаны.")
    except Exception as e:
        logger.error(f"Ошибка в cmd_channel_check: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Ошибка при проверке:</b> <code>{e}</code>")

