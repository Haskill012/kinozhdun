"""Постоянное нижнее меню (ReplyKeyboardMarkup) для бота КиноЖдун."""

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню бота, закреплённое внизу экрана."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔍 Найти сериал / фильм"),
                KeyboardButton(text="📋 Мой список"),
            ],
            [
                KeyboardButton(text="🔄 Проверить статус"),
                KeyboardButton(text="📅 Указать дату"),
            ],
            [
                KeyboardButton(text="🗑 Удалить из списка"),
                KeyboardButton(text="ℹ️ Справка"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
