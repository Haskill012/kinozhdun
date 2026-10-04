"""Утилиты для форматирования сообщений бота КиноЖдун (эстетичная HTML-разметка)."""

import datetime
from typing import Any

DIVIDER = "────────────────────────"


def format_date_ru(value: Any) -> str:
    """Форматирует дату строго в русский формат ДД.ММ.ГГГГ.

    Принимает datetime.date, datetime.datetime или строку вида 'YYYY-MM-DD'.
    """
    if not value:
        return ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, str):
        val = value.strip()
        if len(val) >= 10 and val[4] == "-" and val[7] == "-":
            try:
                parsed = datetime.date.fromisoformat(val[:10])
                return parsed.strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                pass
        return val
    return str(value)


def format_status_emoji(status: str | None) -> str:
    """Возвращает понятное русское описание и эмодзи для статуса из TMDB."""
    if not status:
        return "⏳ Ожидание новостей"

    status_map = {
        "Returning Series": "🔄 Выходят новые сезоны",
        "Ended": "🏁 Завершён",
        "Canceled": "❌ Закрыт / Отменён",
        "Released": "✅ Премьера состоялась",
        "Post Production": "🛠 Пост-продакшн",
        "In Production": "🎥 В производстве",
        "Planned": "📅 Запланирован",
        "Rumored": "🗣 По слухам",
        "waiting": "⏳ В ожидании анонса",
        "announced": "📢 Анонсирована дата выхода",
    }
    return status_map.get(status, f"ℹ️ {status}")


def format_search_results_message(query: str, results: list[dict[str, Any]]) -> str:
    """Красиво форматирует структурированное сообщение с результатами поиска."""
    if not results:
        return (
            f"🔍 <b>Поиск:</b> <i>«{query}»</i>\n"
            f"{DIVIDER}\n"
            "По вашему запросу ничего не найдено.\n"
            "Попробуйте написать название иначе или проверить опечатки."
        )

    lines = [
        f"🔎 <b>Результаты поиска по запросу «{query}»</b>",
        DIVIDER,
    ]
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]

    for i, res in enumerate(results[:6]):
        num_icon = numbers[i] if i < len(numbers) else f"{i + 1}."
        media_type = res.get("media_type", "movie")
        icon = "📺" if media_type == "tv" else "🎬"
        type_str = "Сериал" if media_type == "tv" else "Фильм"
        title = res.get("title") or res.get("name") or "Без названия"

        raw_date = res.get("release_date")
        date_str = format_date_ru(raw_date)
        date_label = f" ({date_str})" if date_str else ""

        network = res.get("network")
        network_str = f" • 🏢 <b>{network}</b>" if network else ""

        rating = res.get("vote_average") or 0.0
        rating_str = f" • ⭐ {rating:.1f}" if rating > 0 else ""

        seasons_info = ""
        if media_type == "tv" and res.get("number_of_seasons"):
            seasons_info = f" • 🎞 {res['number_of_seasons']} сезон(а)"

        overview = res.get("overview", "").strip()
        if len(overview) > 130:
            overview = overview[:127] + "..."
        overview_str = f"\n   <i>«{overview}»</i>" if overview else ""

        lines.append(
            f"{num_icon} {icon} <b>{title}</b>{date_label}\n"
            f"   🏷 {type_str}{network_str}{seasons_info}{rating_str}"
            f"{overview_str}\n"
        )

    lines.append(DIVIDER)
    lines.append("👇 <i>Нажмите кнопку ниже, чтобы открыть карточку проекта:</i>")
    return "\n".join(lines)


def format_item_details(item: Any, media_type_hint: str | None = None) -> str:
    """Форматирует детальную карточку проекта в стильном дизайне."""
    if isinstance(item, dict):
        media_type = media_type_hint or item.get("media_type", "movie")
        title = item.get("title") or item.get("name") or "Без названия"
        orig_title = item.get("original_title") or item.get("original_name")
        status_raw = item.get("status", "")
        network = item.get("network")
        seasons_count = item.get("number_of_seasons")
        tmdb_url = item.get("tmdb_url", "")
        next_ep = item.get("next_episode_to_air")
        next_date = next_ep.get("air_date") if isinstance(next_ep, dict) else item.get("release_date")
        custom_date = None
        first_date = item.get("first_air_date")
        overview = item.get("overview", "")
        rating = item.get("vote_average")
    else:
        media_type = getattr(item, "media_type", media_type_hint or "movie")
        title = getattr(item, "title", "Без названия")
        orig_title = getattr(item, "original_title", None)
        status_raw = getattr(item, "status", "")
        network = getattr(item, "network", None)
        seasons_count = getattr(item, "last_known_season", None)
        next_date = getattr(item, "next_air_date", None)
        custom_date = getattr(item, "custom_date", None)
        tmdb_url = getattr(item, "tmdb_url", "")
        first_date = getattr(item, "last_known_air_date", None)
        overview = getattr(item, "overview", "")
        rating = getattr(item, "vote_average", None)

    icon = "📺" if media_type == "tv" else "🎬"
    type_label = "Сериал" if media_type == "tv" else "Фильм"

    lines = [
        f"{icon} <b>{title}</b>",
    ]
    if orig_title and orig_title != title:
        lines.append(f"<i>({orig_title})</i>")

    lines.append(DIVIDER)
    lines.append(f"🏷 <b>Категория:</b> {type_label}")

    if network:
        lines.append(f"🏢 <b>Платформа / Студия:</b> <b>{network}</b>")

    lines.append(f"📊 <b>Статус проекта:</b> {format_status_emoji(status_raw)}")

    if media_type == "tv" and seasons_count:
        lines.append(f"🎞 <b>Сезонов в базе:</b> {seasons_count}")

    if rating and float(rating) > 0:
        lines.append(f"⭐ <b>Рейтинг TMDB:</b> {float(rating):.1f} / 10")

    if next_date:
        lines.append(f"📅 <b>Дата премьеры нового сезона/части:</b> <code>{format_date_ru(next_date)}</code>")
    else:
        lines.append("📅 <b>Дата премьеры:</b> <i>пока не объявлена</i> 🔍")

    if custom_date:
        lines.append(f"⏰ <b>Ваша личная дата напоминания:</b> <code>{format_date_ru(custom_date)}</code>")

    if first_date:
        lines.append(f"🗓 <b>Первый релиз:</b> <code>{format_date_ru(first_date)}</code>")

    if overview and len(overview.strip()) > 0:
        lines.append(DIVIDER)
        ov = overview.strip()
        if len(ov) > 280:
            ov = ov[:277] + "..."
        lines.append(f"📝 <b>Сюжет:</b>\n<i>{ov}</i>")

    if tmdb_url:
        lines.append(DIVIDER)
        lines.append(f"🔗 <a href='{tmdb_url}'>Официальная страница на TMDB</a>")

    return "\n".join(lines)


def format_announced_notification(item: Any, update: dict[str, Any]) -> str:
    """Форматирует уведомление о появлении даты выхода."""
    title = getattr(item, "title", "Без названия")
    season = update.get("next_season")
    air_date = update.get("next_air_date")
    url = update.get("source_url") or getattr(item, "tmdb_url", "")
    network = getattr(item, "network", None)

    lines = [
        "🎉 <b>НОВОСТИ ПО СПИСКУ ОЖИДАНИЯ!</b>",
        DIVIDER,
        f"У проекта <b>{title}</b> появилась официальная дата выхода!",
    ]

    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    if season:
        lines.append(f"🆕 <b>Сезон:</b> {season}")
    if air_date:
        lines.append(f"📅 <b>Дата премьеры:</b> <code>{format_date_ru(air_date)}</code>")

    if url:
        lines.append(DIVIDER)
        lines.append(f"🔗 <a href='{url}'>Источник: TMDB</a>")

    return "\n".join(lines)


def format_released_notification(item: Any) -> str:
    """Форматирует уведомление о премьере."""
    title = getattr(item, "title", "Без названия")
    season = getattr(item, "next_season_number", None) or getattr(item, "last_known_season", None)
    media_type = getattr(item, "media_type", "movie")
    url = getattr(item, "tmdb_url", "")
    air_date = getattr(item, "next_air_date", None)
    network = getattr(item, "network", None)

    season_info = f" (сезон {season})" if (media_type == "tv" and season) else ""
    net_info = f" на {network}" if network else ""

    lines = [
        "🍿 <b>СЕГОДНЯ ПРЕМЬЕРА!</b>",
        DIVIDER,
        f"Вышел долгожданный релиз: <b>{title}</b>{season_info}{net_info}! 🎉",
    ]

    if air_date:
        lines.append(f"📅 <b>Дата:</b> <code>{format_date_ru(air_date)}</code>")

    lines.append("Приятного просмотра!")

    if url:
        lines.append(DIVIDER)
        lines.append(f"🔗 <a href='{url}'>Подробнее на TMDB</a>")

    return "\n".join(lines)


def format_reminder_notification(item: Any, days_left: int = 3) -> str:
    """Форматирует напоминание за 3 дня до даты."""
    title = getattr(item, "title", "Без названия")
    air_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
    url = getattr(item, "tmdb_url", "")
    network = getattr(item, "network", None)

    lines = [
        "⏰ <b>СКОРО ПРЕМЬЕРА!</b>",
        DIVIDER,
        f"До выхода <b>{title}</b> осталось дней: <b>{days_left}</b>!",
    ]

    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    if air_date:
        lines.append(f"📅 <b>Дата:</b> <code>{format_date_ru(air_date)}</code>")

    if url:
        lines.append(DIVIDER)
        lines.append(f"🔗 <a href='{url}'>TMDB</a>")

    return "\n".join(lines)


def format_item_list(items: list[Any]) -> str:
    """Форматирует список отслеживаемых тайтлов."""
    if not items:
        return (
            "🍿 <b>МОЙ КИНОЖДУН</b>\n"
            f"{DIVIDER}\n"
            "📭 Ваш список ожидания пока пуст.\n\n"
            "Нажмите <b>«🔍 Найти фильм / сериал»</b> ниже или просто отправьте название тайтла в чат!"
        )

    lines = [
        "🍿 <b>МОЙ КИНОЖДУН</b>",
        f"Ты ждёшь ({len(items)}):",
        DIVIDER,
    ]

    for i, item in enumerate(items, 1):
        status = getattr(item, "status", "waiting")
        icon = "📺" if getattr(item, "media_type", "") == "tv" else "🎬"

        status_badge = "⏳"
        if status == "announced":
            status_badge = "📢"
        elif status == "released":
            status_badge = "✅"

        title = getattr(item, "title", "Без названия")
        network = getattr(item, "network", None)
        network_str = f" • {network}" if network else ""

        next_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
        date_info = f" — <code>{format_date_ru(next_date)}</code>" if next_date else " — <i>дата не объявлена</i>"

        lines.append(f"{i}. {status_badge} {icon} <b>{title}</b>{network_str}{date_info}")

    lines.append(DIVIDER)
    lines.append("📤 <i>Нажмите <b>«📤 Поделиться моим Кинождуном»</b> вверху, чтобы отправить подборку друзьям!</i>")
    return "\n".join(lines)


def format_welcome_message(first_name: str) -> str:
    """Приветственное сообщение."""
    return (
        f"🎬 <b>КИНОЖДУН</b> • Личный трекер премьер\n"
        f"{DIVIDER}\n"
        f"Привет, <b>{first_name}</b>! 👋\n\n"
        "Я слежу за выходом новых сезонов сериалов и продолжений фильмов в официальных каталогах "
        "(TMDB, Netflix, HBO, Disney+, Apple TV+ и др.).\n\n"
        "✨ <b>Возможности бота:</b>\n"
        "• 🔍 <b>Поиск и отслеживание</b>: напишите название любого фильма или сериала\n"
        "• 🍿 <b>«Мой Кинождун»</b>: ваш личный список ожидания + кнопка «📤 Поделиться списком»\n"
        "• 📤 <b>Виральный шеринг</b>: делитесь фильмами с друзьями в 1 клик через ссылку\n"
        "• 🔔 <b>Уведомления</b>: моментальное оповещение, когда появится дата премьеры\n\n"
        f"{DIVIDER}\n"
        "👇 <b>Быстрый доступ через меню внизу:</b>"
    )


def format_help_message() -> str:
    """Справка по возможностям бота."""
    return (
        "📖 <b>СПРАВКА ПО БОТУ КИНОЖДУН</b>\n"
        f"{DIVIDER}\n"
        "<b>Кнопки меню внизу экрана:</b>\n"
        "🔍 <b>Найти фильм / сериал</b> — поиск любого кино и выбор из списка\n"
        "🍿 <b>Мой Кинождун</b> — ваш список ожидания + кнопка «📤 Поделиться списком»\n"
        "🔄 <b>Проверить статус</b> — запрос свежих дат с TMDB прямо сейчас\n"
        "📅 <b>Своя дата</b> — установка личной даты напоминания (ДД.ММ.ГГГГ)\n"
        "🗑 <b>Удалить из списка</b> — удаление проекта из отслеживания\n"
        "ℹ️ <b>Справка и помощь</b> — это справочное руководство\n\n"
        f"{DIVIDER}\n"
        "💡 <i>Подсказка: Вы можете поделиться любым фильмом или всем своим списком ожидания с друзьями!</i>"
    )


def format_shared_item_prompt(title: str, details: dict[str, Any], media_type: str) -> str:
    """Форматирует карточку проекта для получателя ссылки шеринга."""
    icon = "📺" if media_type == "tv" else "🎬"
    type_str = "сериал" if media_type == "tv" else "фильм"
    network = details.get("network")
    net_str = f"\n🏢 <b>Платформа:</b> {network}" if network else ""

    next_date = None
    if media_type == "tv":
        next_ep = details.get("next_episode_to_air")
        if next_ep and next_ep.get("air_date"):
            next_date = next_ep["air_date"]
    else:
        next_date = details.get("release_date")

    date_str = f"\n📅 <b>Дата выхода:</b> <code>{format_date_ru(next_date)}</code>" if next_date else "\n📅 <b>Дата выхода:</b> <i>пока не объявлена</i>"

    overview = details.get("overview", "").strip()
    if len(overview) > 200:
        overview = overview[:197] + "..."
    overview_str = f"\n\n📝 <i>«{overview}»</i>" if overview else ""

    return (
        f"🍿 <b>Тоже ждёшь «{title}»?</b>\n"
        f"{DIVIDER}\n"
        f"Друг поделился с вами {type_str}ом {icon} <b>«{title}»</b>.{net_str}{date_str}{overview_str}\n\n"
        "Кинождун пришлёт вам уведомление, как только появится официальная дата премьеры, трейлер или новый сезон 🍿\n\n"
        "👇 <i>Нажмите <b>«🔔 Отслеживать»</b> ниже, чтобы добавить в свой список в 1 клик:</i>"
    )


def format_shared_watchlist_message(items: list[dict[str, Any]], title: str = "Список ожидания") -> str:
    """Форматирует карточку расшаренного списка для получателя."""
    if not items:
        return (
            f"🍿 <b>{title}</b>\n"
            f"{DIVIDER}\n"
            "Этот список ожидания пуст."
        )

    lines = [
        f"🍿 <b>{title}</b>",
        f"Всего тайтлов: <b>{len(items)}</b>",
        DIVIDER,
        "Вот какие фильмы и сериалы сейчас ждёт автор списка:\n",
    ]

    for i, it in enumerate(items, 1):
        m_type = it.get("media_type", "movie")
        icon = "📺" if m_type == "tv" else "🎬"
        item_title = it.get("title", "Без названия")
        network = it.get("network")
        net_str = f" • {network}" if network else ""

        next_date = it.get("next_air_date")
        date_str = f" — <code>{format_date_ru(next_date)}</code>" if next_date else " — <i>дата не объявлена</i>"

        lines.append(f"{i}. {icon} <b>{item_title}</b>{net_str}{date_str}")

    lines.append(f"\n{DIVIDER}")
    lines.append("👇 <i>Выберите позиции для добавления или нажмите «➕ Отслеживать всё»:</i>")
    return "\n".join(lines)


def format_channel_referral_prompt(post: Any) -> str:
    """Форматирует карточку для пользователя, перешедшего из Telegram-канала."""
    post_type = getattr(post, "post_type", "news")
    if post_type in ("daily_digest", "weekly_digest"):
        title = getattr(post, "title", "Премьеры")
        return (
            f"🍿 <b>{title}</b>\n"
            f"{DIVIDER}\n"
            "Вы перешли по подборке премьер из нашего Telegram-канала!\n\n"
            "Воспользуйтесь поиском в меню ниже, чтобы добавить интересующие фильмы и сериалы в свой Кинождун 🍿"
        )

    media_type = getattr(post, "media_type", "")
    icon = "📺" if media_type == "tv" else "🎬"
    title = getattr(post, "title", "Без названия")
    season_number = getattr(post, "season_number", None)

    season_suffix = f" — сезон {season_number}" if (media_type == "tv" and season_number) else ""
    headline = f"🍿 <b>Тоже ждёшь «{title}{season_suffix}»?</b>"

    network = getattr(post, "network", None)
    net_str = f"\n🏢 <b>Платформа / Студия:</b> {network}" if network else ""

    air_date = getattr(post, "air_date", None)
    date_str = f"\n📅 <b>Дата премьеры:</b> <code>{format_date_ru(air_date)}</code>" if air_date else "\n📅 <b>Дата премьеры:</b> <i>уточняется</i>"

    return (
        f"🔥 <b>Новость из Telegram-канала «Кинождун»</b>\n"
        f"{DIVIDER}\n"
        f"{headline}\n"
        f"{icon} <b>{title}</b>{season_suffix}{net_str}{date_str}\n\n"
        "Кинождун сообщит вам, как только появятся важные новости, трейлеры или выйдет премьера 🍿\n\n"
        "👇 <i>Нажмите кнопку ниже, чтобы начать отслеживание в 1 клик:</i>"
    )


