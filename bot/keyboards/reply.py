"""Постоянное нижнее меню (ReplyKeyboardMarkup) для бота КиноЖдун."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню бота с аккуратным и удобным расположением кнопок."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔍 Найти фильм / сериал"),
                KeyboardButton(text="🍿 Мой Кинождун"),
            ],
            [
                KeyboardButton(text="🔄 Проверить статус"),
                KeyboardButton(text="📅 Своя дата"),
            ],
            [
                KeyboardButton(text="🗑 Удалить из списка"),
                KeyboardButton(text="ℹ️ Справка и помощь"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
