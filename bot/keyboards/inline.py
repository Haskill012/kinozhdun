"""Инлайн-клавиатуры для бота КиноЖдун (включая виральный шеринг, расшаривание списков и переходы из канала)."""

import urllib.parse
from typing import Any, Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.utils.formatting import site_title_url


def add_site_title_button(builder, media_type, tmdb_id):
    url = site_title_url(media_type, tmdb_id)
    if url:
        builder.button(text="🌐 Карточка и новости на сайте", url=url)


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
        builder.button(text=btn_text, callback_data=f"preview:{media_type}:{tmdb_id}")

    builder.button(text="❌ Отмена поиска", callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def preview_item_keyboard(
    media_type: str,
    tmdb_id: int,
    is_already_tracked: bool = False,
    tracked_item_id: int | None = None,
    bot_username: str = "kinojdun_bot",
    title: str = "",
    referrer_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """Клавиатура для карточки предпросмотра проекта с кнопкой добавления в отслеживание."""
    builder = InlineKeyboardBuilder()
    if is_already_tracked:
        builder.button(text="✅ Уже в вашем списке", callback_data="already_tracked")
        # Возможность поделиться проектом через красивый инлайн-режим
        if title:
            ref_part = f"_u{referrer_id}" if referrer_id else ""
            builder.button(
                text="📤 Поделиться с другом",
                switch_inline_query=f"share_{media_type}_{tmdb_id}{ref_part}"
            )
        if tracked_item_id:
            builder.button(text="🗑 Удалить из списка", callback_data=f"remove:{tracked_item_id}")
    else:
        builder.button(text="➕ Добавить в отслеживание", callback_data=f"confirm_track:{media_type}:{tmdb_id}")

    builder.button(text="🔙 Назад к результатам поиска", callback_data="back_to_search")
    builder.button(text="❌ Закрыть", callback_data="cancel_search")
    add_site_title_button(builder, media_type, tmdb_id)
    builder.adjust(1)
    return builder.as_markup()


def track_success_keyboard(
    media_type: str,
    tmdb_id: int,
    title: str,
    bot_username: str = "kinojdun_bot",
    referrer_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """Клавиатура после успешного добавления проекта с кнопкой инлайн-шеринга карточки с постером."""
    builder = InlineKeyboardBuilder()

    ref_part = f"_u{referrer_id}" if referrer_id else ""
    builder.button(
        text="📤 Поделиться с другом",
        switch_inline_query=f"share_{media_type}_{tmdb_id}{ref_part}"
    )
    builder.button(text="🍿 Мой Кинождун", callback_data="back_to_list")
    builder.button(text="🔍 Искать ещё", callback_data="cancel_search")
    add_site_title_button(builder, media_type, tmdb_id)
    builder.adjust(1, 2)
    return builder.as_markup()


def user_items_keyboard(items: list[Any], action: str = "info") -> InlineKeyboardMarkup:
    """Клавиатура списка отслеживаемых элементов с кнопкой «📤 Поделиться списком»."""
    builder = InlineKeyboardBuilder()

    # При просмотре списка ставим кнопку шеринга В САМЫЙ ВЕРХ, чтобы её сразу заметили!
    if action == "info" and len(items) > 0:
        builder.button(text="📤 Поделиться моим Кинождуном", callback_data="share_watchlist")

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

    # Внизу длинного списка также добавляем кнопку
    if action == "info" and len(items) > 3:
        builder.button(text="📤 Поделиться списком", callback_data="share_watchlist")

    builder.button(text="❌ Закрыть", callback_data="cancel_search")
    builder.adjust(1)
    return builder.as_markup()


def shared_watchlist_created_keyboard(token: str, bot_username: str, titles: list[str]) -> InlineKeyboardMarkup:
    """Клавиатура для создателя списка со ссылкой для быстрой отправки в чаты Telegram."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📤 Отправить друзьям в Telegram",
        switch_inline_query=f"list_{token}"
    )
    builder.button(text="📋 К моему списку", callback_data="back_to_list")
    builder.adjust(1)
    return builder.as_markup()


def shared_item_recipient_keyboard(
    media_type: str,
    tmdb_id: int,
    is_already_tracked: bool = False,
    referrer_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """Клавиатура для получателя ссылки на конкретный фильм/сериал."""
    builder = InlineKeyboardBuilder()
    if is_already_tracked:
        builder.button(text="✅ Уже в вашем списке ожидания", callback_data="already_tracked")
        builder.button(text="📋 Открыть мой список", callback_data="back_to_list")
    else:
        ref_part = f":{referrer_id}" if referrer_id else ""
        builder.button(text="🔔 Отслеживать", callback_data=f"track_from_share:{media_type}:{tmdb_id}{ref_part}")
        builder.button(text="🔎 Посмотреть подробнее", callback_data=f"preview:{media_type}:{tmdb_id}")

    builder.button(text="🔍 Найти другой фильм/сериал", callback_data="cancel_search")
    add_site_title_button(builder, media_type, tmdb_id)
    builder.adjust(1)
    return builder.as_markup()


def shared_watchlist_recipient_keyboard(
    token: str,
    items: list[dict[str, Any]],
    tracked_keys: set[tuple[str, int]],
) -> InlineKeyboardMarkup:
    """Клавиатура для получателя расшаренного списка: кнопки по каждому тайтлу + «Отслеживать всё»."""
    builder = InlineKeyboardBuilder()

    # Кнопки для отдельных элементов (первые 8, чтобы не перегружать клавиатуру)
    for idx, item in enumerate(items[:8]):
        m_type = item.get("media_type", "movie")
        t_id = int(item.get("tmdb_id", 0))
        title = item.get("title", "Без названия")
        is_tracked = (m_type, t_id) in tracked_keys

        if is_tracked:
            btn_text = f"✅ {title} (уже у вас)"
            callback = "already_tracked"
        else:
            icon = "📺" if m_type == "tv" else "🎬"
            btn_text = f"➕ {icon} {title}"
            if len(btn_text) > 40:
                btn_text = btn_text[:37] + "..."
            callback = f"track_shared_item:{token}:{idx}"

        builder.button(text=btn_text, callback_data=callback)

    # Кнопка «Отслеживать всё»
    untracked_count = sum(1 for it in items if (it.get("media_type", "movie"), int(it.get("tmdb_id", 0))) not in tracked_keys)
    if untracked_count > 0:
        builder.button(text=f"➕ Отслеживать всё ({untracked_count})", callback_data=f"prompt_batch_track:{token}")
    else:
        builder.button(text="✅ Все тайтлы уже в вашем списке", callback_data="already_tracked")

    builder.button(text="📋 Мой список ожидания", callback_data="back_to_list")
    builder.adjust(1)
    return builder.as_markup()


def confirm_batch_track_keyboard(token: str) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения массового добавления тайтлов из списка друга."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отслеживать всё", callback_data=f"confirm_batch_track:{token}")
    builder.button(text="❌ Отмена", callback_data=f"cancel_batch_track:{token}")
    builder.adjust(2)
    return builder.as_markup()


def channel_referral_keyboard(
    post_id: int,
    media_type: str,
    tmdb_id: int,
    title: str,
    is_already_tracked: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура для пользователя, перешедшего из публикации Telegram-канала."""
    builder = InlineKeyboardBuilder()
    clean_title = title if len(title) <= 24 else title[:21] + "..."

    if is_already_tracked:
        builder.button(text=f"✅ «{clean_title}» уже в вашем списке", callback_data="already_tracked")
        builder.button(text="📋 Мой список ожидания", callback_data="back_to_list")
    else:
        builder.button(
            text=f"🔔 Отслеживать «{clean_title}»",
            callback_data=f"track_from_channel:{post_id}:{media_type}:{tmdb_id}"
        )
        builder.button(text="🔎 Подробнее о проекте", callback_data=f"preview:{media_type}:{tmdb_id}")

    builder.button(text="🔍 Найти другой фильм/сериал", callback_data="cancel_search")
    add_site_title_button(builder, media_type, tmdb_id)
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
    builder.button(text="📋 К списку «Мой Кинождун»", callback_data="back_to_list")
    return builder.as_markup()


def item_details_keyboard(
    item: Any,
    bot_username: str = "kinojdun_bot",
    referrer_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """Клавиатура детальной карточки проекта из списка отслеживания с кнопкой инлайн-шеринга."""
    builder = InlineKeyboardBuilder()
    title = getattr(item, "title", "")
    media_type = getattr(item, "media_type", "movie")
    tmdb_id = getattr(item, "tmdb_id", 0)
    item_id = getattr(item, "id", 0)

    if title and tmdb_id:
        ref_part = f"_u{referrer_id}" if referrer_id else ""
        builder.button(
            text="📤 Поделиться с другом",
            switch_inline_query=f"share_{media_type}_{tmdb_id}{ref_part}"
        )

    tmdb_url = getattr(item, "tmdb_url", None)
    if tmdb_url and str(tmdb_url).startswith("http"):
        builder.button(text="🌐 Страница на TMDB", url=str(tmdb_url))

    builder.button(text="🗑 Удалить из списка", callback_data=f"remove:{item_id}")
    builder.button(text="📋 К списку «Мой Кинождун»", callback_data="back_to_list")
    add_site_title_button(builder, media_type, tmdb_id)
    builder.adjust(1)
    return builder.as_markup()


def generate_share_url(deep_link: str, share_text: str) -> str:
    """Генерирует ссылку t.me/share/url с текстом впереди ссылки, чтобы ссылка не отображалась голой сверху."""
    full_message = f"{share_text}\n\n👉 {deep_link}"
    return f"https://t.me/share/url?url={urllib.parse.quote(full_message)}"


def notification_item_keyboard(
    item_id: int,
    tmdb_url: Optional[str] = None,
    bot_username: str = "kinojdun_bot",
    media_type: str | None = None,
    tmdb_id: int | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура для уведомлений пользователю: кнопка перехода к карточке и ссылка на TMDB."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🍿 Открыть в Кинождуне", callback_data=f"info:{item_id}")
    if tmdb_url and str(tmdb_url).startswith("http"):
        builder.button(text="🌐 Страница на TMDB", url=str(tmdb_url))
    add_site_title_button(builder, media_type, tmdb_id)
    builder.adjust(1)
    return builder.as_markup()
