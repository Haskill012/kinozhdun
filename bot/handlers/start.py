"""Хендлеры команд /start и /help."""

from aiogram import Router, F
from aiogram.filters import CommandStart, Command, or_f
from aiogram.types import Message

from bot.db.repositories import Repository
from bot.keyboards.reply import main_menu_keyboard
from bot.utils.formatting import format_welcome_message, format_help_message

router = Router(name="start_router")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Обработка команды /start — регистрация, приветствие и вывод главного меню."""
    session_factory = message.bot["session_factory"]
    async with session_factory() as session:
        repo = Repository(session)
        await repo.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        await session.commit()

    await message.answer(
        format_welcome_message(message.from_user.first_name or "друг"),
        reply_markup=main_menu_keyboard(),
    )


@router.message(or_f(Command("help"), F.text == "ℹ️ Справка и помощь", F.text == "ℹ️ Справка"))
async def cmd_help(message: Message) -> None:
    """Обработка команды /help и кнопки «ℹ️ Справка»."""
    await message.answer(format_help_message(), reply_markup=main_menu_keyboard())
