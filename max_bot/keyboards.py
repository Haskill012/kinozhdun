"""Генераторы инлайн-клавиатур для мессенджера Макс (MAX Messenger)."""

from typing import Any, Optional
from bot.utils.formatting import site_title_url


def callback_button(text: str, payload: str) -> dict[str, str]:
    """Создаёт инлайн callback-кнопку."""
    # Ограничение MAX API: text до 128 символов, payload до 1024 символов
    return {
        "type": "callback",
        "text": text[:128],
        "payload": payload[:1024],
    }


def link_button(text: str, url: str) -> dict[str, str]:
    """Создаёт URL-кнопку."""
    return {
        "type": "link",
        "text": text[:128],
        "url": url[:2048],
    }


def inline_keyboard(rows: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
    """Оборачивает ряды кнопок в массив attachments для MAX Bot API."""
    # Фильтруем пустые ряды
    clean_rows = [r for r in rows if r]
    if not clean_rows:
        return []
    return [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": clean_rows,
            },
        }
    ]


def main_menu_keyboard() -> list[dict[str, Any]]:
    """Главное меню управления ботом КиноЖдун."""
    rows = [
        [
            callback_button("🔍 Найти сериал / фильм", "menu:search"),
            callback_button("🍿 Мой Кинождун", "menu:list"),
        ],
        [
            callback_button("🔄 Проверить статус", "menu:status"),
            callback_button("📅 Указать дату", "menu:setdate"),
        ],
        [
            callback_button("🗑 Удалить из списка", "menu:remove"),
            callback_button("ℹ️ Справка и помощь", "menu:help"),
        ],
    ]
    return inline_keyboard(rows)


def search_results_keyboard(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Клавиатура с результатами поиска фильмов и сериалов."""
    rows = []
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]

    for i, res in enumerate(results[:6]):
        num_icon = numbers[i] if i < len(numbers) else f"{i + 1}."
        media_type = res.get("media_type", "movie")
        raw_title = res.get("title") or res.get("name") or "Без названия"
        raw_date = res.get("release_date") or res.get("first_air_date") or ""
        icon = "📺" if media_type == "tv" else "🎬"

        year_str = f" ({str(raw_date)[:4]})" if raw_date and len(str(raw_date)) >= 4 else ""
        btn_text = f"{num_icon} {icon} {raw_title}{year_str}"
        if len(btn_text) > 45:
            btn_text = btn_text[:42] + "..."

        tmdb_id = res.get("tmdb_id") or res.get("id")
        rows.append([callback_button(btn_text, f"preview:{media_type}:{tmdb_id}")])

    rows.append([callback_button("❌ Отмена поиска", "cancel_search")])
    return inline_keyboard(rows)


def preview_item_keyboard(
    media_type: str,
    tmdb_id: int,
    is_already_tracked: bool = False,
    tracked_item_id: Optional[int] = None,
    title: str = "",
    site_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Клавиатура для карточки предпросмотра фильма или сериала."""
    rows = []

    if is_already_tracked:
        rows.append([callback_button("✅ Уже в вашем списке", "already_tracked")])
        if tracked_item_id:
            rows.append([callback_button("🗑 Удалить из списка", f"remove:{tracked_item_id}")])
    else:
        rows.append([callback_button("➕ Добавить в отслеживание", f"confirm_track:{media_type}:{tmdb_id}")])

    nav_row = [
        callback_button("🔙 Назад к поиску", "back_to_search"),
        callback_button("❌ Закрыть", "cancel_search"),
    ]
    rows.append(nav_row)

    site_link = site_title_url(media_type, tmdb_id, site_url)
    if site_link:
        rows.append([link_button("🌐 Страница на KinoJdun.ru", site_link)])

    return inline_keyboard(rows)


def track_success_keyboard(
    media_type: str,
    tmdb_id: int,
    site_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Клавиатура после успешного добавления в список."""
    rows = [
        [
            callback_button("🍿 Мой Кинождун", "menu:list"),
            callback_button("🔍 Искать ещё", "menu:search"),
        ],
    ]
    site_link = site_title_url(media_type, tmdb_id, site_url)
    if site_link:
        rows.append([link_button("🌐 Страница на KinoJdun.ru", site_link)])
    return inline_keyboard(rows)


def user_items_keyboard(items: list[Any], action: str = "details") -> list[dict[str, Any]]:
    """Клавиатура со списком отслеживаемых тайтлов пользователя."""
    rows = []
    for item in items[:15]:
        media_type = getattr(item, "media_type", "movie")
        icon = "📺" if media_type == "tv" else "🎬"
        title = getattr(item, "title", "Без названия")
        btn_text = f"{icon} {title}"
        if len(btn_text) > 45:
            btn_text = btn_text[:42] + "..."

        if action == "remove":
            rows.append([callback_button(f"🗑 {btn_text}", f"remove:{item.id}")])
        elif action == "setdate":
            rows.append([callback_button(f"📅 {btn_text}", f"setdate:{item.id}")])
        else:
            rows.append([callback_button(btn_text, f"details:{item.id}")])

    rows.append([callback_button("🏠 Главное меню", "menu:main")])
    return inline_keyboard(rows)


def item_details_keyboard(
    item: Any,
    site_url: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Клавиатура карточки детального просмотра уже отслеживаемого тайтла."""
    item_id = getattr(item, "id", 0)
    media_type = getattr(item, "media_type", "movie")
    tmdb_id = getattr(item, "tmdb_id", 0)

    rows = [
        [
            callback_button("📅 Указать дату", f"setdate:{item_id}"),
            callback_button("🗑 Удалить", f"remove:{item_id}"),
        ],
        [
            callback_button("🔙 К списку ожидания", "menu:list"),
            callback_button("🔍 Поиск", "menu:search"),
        ],
    ]

    site_link = site_title_url(media_type, tmdb_id, site_url)
    if site_link:
        rows.append([link_button("🌐 Страница на KinoJdun.ru", site_link)])

    return inline_keyboard(rows)


def confirm_remove_keyboard(item_id: int) -> list[dict[str, Any]]:
    """Клавиатура подтверждения удаления элемента."""
    rows = [
        [
            callback_button("🗑 Да, удалить", f"confirm_remove:{item_id}"),
            callback_button("❌ Отмена", "menu:list"),
        ]
    ]
    return inline_keyboard(rows)


def cancel_keyboard() -> list[dict[str, Any]]:
    """Простая кнопка отмены текущего действия."""
    return inline_keyboard([[callback_button("❌ Отмена", "menu:main")]])
