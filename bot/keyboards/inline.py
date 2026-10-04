"""Инлайн-клавиатуры для бота КиноЖдун."""

from typing import Any
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def search_results_keyboard(results: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Клавиатура с результатами поиска, включающая студию/платформу."""
    builder = InlineKeyboardBuilder()
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

    for i, result in enumerate(results[:6]):
        num_icon = numbers[i] if i < len(numbers) else f"{i + 1}."
        media_type = result.get("media_type", "movie")
        title = result.get("title") or result.get("name") or "Без названия"
        date = result.get("release_date") or result.get("first_air_date") or ""
        icon = "📺" if media_type == "tv" else "🎬"

        year = ""
        if date and len(str(date)) >= 4:
            year = f" ({str(date)[:4]})"

        network = result.get("network")
        net_str = f" • {network}" if network else ""

        btn_text = f"{num_icon} {icon} {title}{year}{net_str}"
        if len(btn_text) > 60:
            btn_text = btn_text[:57] + "..."

        tmdb_id = result.get("tmdb_id") or result.get("id")
        # Ведёт на карточку предпросмотра с кнопкой «Добавить в отслеживание»
        builder.button(text=btn_text, callback_data=f"preview:{media_type}:{tmdb_id}")

    builder.button(text="❌ Отмена поиска", callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def preview_item_keyboard(
    media_type: str,
    tmdb_id: int,
    is_already_tracked: bool = False,
    tracked_item_id: int | None = None
) -> InlineKeyboardMarkup:
    """Клавиатура для карточки предпросмотра проекта с кнопкой добавления в отслеживание."""
    builder = InlineKeyboardBuilder()
    if is_already_tracked:
        builder.button(text="✅ Уже в вашем списке отслеживания", callback_data="already_tracked")
        if tracked_item_id:
            builder.button(text="🗑 Удалить из списка", callback_data=f"remove:{tracked_item_id}")
    else:
        builder.button(text="➕ Добавить в отслеживание", callback_data=f"confirm_track:{media_type}:{tmdb_id}")

    builder.button(text="🔙 Назад к результатам поиска", callback_data="back_to_search")
    builder.button(text="❌ Закрыть", callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def track_success_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура после успешного добавления проекта в отслеживание."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мой список", callback_data="back_to_list")
    builder.button(text="🔍 Искать ещё", callback_data="cancel_search")
    builder.adjust(2)
    return builder.as_markup()


def user_items_keyboard(items: list[Any], action: str = "info") -> InlineKeyboardMarkup:
    """Клавиатура списка отслеживаемых элементов пользователя."""
    builder = InlineKeyboardBuilder()
    for item in items:
        title = getattr(item, "title", f"Элемент {getattr(item, 'id', '')}")
        media_type = getattr(item, "media_type", "movie")
        network = getattr(item, "network", None)
        icon = "📺" if media_type == "tv" else "🎬"

        net_str = f" • {network}" if network else ""
        btn_text = f"{icon} {title}{net_str}"
        if len(btn_text) > 60:
            btn_text = btn_text[:57] + "..."

        builder.button(text=btn_text, callback_data=f"{action}:{item.id}")

    builder.button(text="❌ Закрыть", callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def confirm_remove_keyboard(item_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления элемента."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"confirm_remove:{item_id}")
    builder.button(text="❌ Отмена", callback_data="cancel_remove")
    builder.adjust(2)
    return builder.as_markup()


def back_to_list_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата к списку отслеживаемого."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 К списку", callback_data="back_to_list")
    return builder.as_markup()
