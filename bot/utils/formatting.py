"""Утилиты для форматирования сообщений бота КиноЖдун (HTML-разметка)."""

import datetime
from typing import Any


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
        # Проверяем формат YYYY-MM-DD
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
        "waiting": "⏳ В ожидании новостей",
        "announced": "📢 Анонсирована дата",
    }
    return status_map.get(status, f"ℹ️ {status}")


def format_search_results_message(query: str, results: list[dict[str, Any]]) -> str:
    """Форматирует структурированное сообщение с результатами поиска."""
    if not results:
        return f"🔍 По запросу <b>«{query}»</b> ничего не найдено.\nПопробуйте уточнить название."

    lines = [f"🔎 <b>Результаты поиска по запросу «{query}»:</b>\n"]
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

    for i, res in enumerate(results):
        num_icon = numbers[i] if i < len(numbers) else f"{i + 1}."
        media_type = res.get("media_type", "movie")
        icon = "📺" if media_type == "tv" else "🎬"
        type_str = "Сериал" if media_type == "tv" else "Фильм"
        title = res.get("title") or res.get("name") or "Без названия"

        # Дата в формате ДД.ММ.ГГГГ или год
        raw_date = res.get("release_date")
        date_str = format_date_ru(raw_date)
        date_label = f" ({date_str})" if date_str else ""

        network = res.get("network")
        network_str = f"\n🏢 <b>Платформа/Студия:</b> {network}" if network else ""

        rating = res.get("vote_average") or 0.0
        rating_str = f" ⭐ {rating:.1f}" if rating > 0 else ""

        seasons_info = ""
        if media_type == "tv" and res.get("number_of_seasons"):
            seasons_info = f" • {res['number_of_seasons']} сезон(а)"

        overview = res.get("overview", "").strip()
        if len(overview) > 120:
            overview = overview[:117] + "..."
        overview_str = f"\n<i>{overview}</i>" if overview else ""

        lines.append(
            f"{num_icon} {icon} <b>{title}</b>{date_label}{network_str}\n"
            f"   {type_str}{seasons_info}{rating_str}{overview_str}\n"
        )

    lines.append("<i>Выберите нужный проект кнопкой ниже для отслеживания:</i>")
    return "\n".join(lines)


def format_item_details(item: Any, media_type_hint: str | None = None) -> str:
    """Форматирует детальную карточку проекта для просмотра."""
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

    icon = "📺" if media_type == "tv" else "🎬"
    type_label = "Сериал" if media_type == "tv" else "Фильм"

    lines = [f"{icon} <b>{title}</b>"]
    if orig_title and orig_title != title:
        lines.append(f"<i>({orig_title})</i>")

    lines.append(f"\n<b>Тип:</b> {type_label}")

    if network:
        lines.append(f"🏢 <b>Платформа / Студия:</b> <b>{network}</b>")

    lines.append(f"<b>Статус:</b> {format_status_emoji(status_raw)}")

    if media_type == "tv" and seasons_count:
        lines.append(f"<b>Сезонов в базе:</b> {seasons_count}")

    if next_date:
        lines.append(f"📅 <b>Дата премьеры нового сезона/части:</b> <code>{format_date_ru(next_date)}</code>")
    else:
        lines.append("📅 <b>Дата премьеры:</b> <i>пока не объявлена</i> 🔍")

    if custom_date:
        lines.append(f"⏰ <b>Ваша дата напоминания:</b> <code>{format_date_ru(custom_date)}</code>")

    if first_date:
        lines.append(f"🗓 <b>Дата релиза:</b> <code>{format_date_ru(first_date)}</code>")

    if tmdb_url:
        lines.append(f"\n🔗 <a href='{tmdb_url}'>Страница проекта на TMDB</a>")

    return "\n".join(lines)


def format_announced_notification(item: Any, update: dict[str, Any]) -> str:
    """Форматирует уведомление о появлении официальной даты выхода."""
    title = getattr(item, "title", "Без названия")
    season = update.get("next_season")
    air_date = update.get("next_air_date")
    url = update.get("source_url") or getattr(item, "tmdb_url", "")
    network = getattr(item, "network", None)

    lines = [
        "🎉 <b>Новости по вашему списку ожидания!</b>\n",
        f"У <b>{title}</b> появилась официальная дата выхода!",
    ]

    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    if season:
        lines.append(f"🆕 <b>Сезон:</b> {season}")
    if air_date:
        lines.append(f"📅 <b>Дата выхода:</b> <code>{format_date_ru(air_date)}</code>")

    if url:
        lines.append(f"\n🔗 <a href='{url}'>Источник: TMDB</a>")

    return "\n".join(lines)


def format_released_notification(item: Any) -> str:
    """Форматирует уведомление о выходе проекта."""
    title = getattr(item, "title", "Без названия")
    season = getattr(item, "next_season_number", None) or getattr(item, "last_known_season", None)
    media_type = getattr(item, "media_type", "movie")
    url = getattr(item, "tmdb_url", "")
    air_date = getattr(item, "next_air_date", None)

    season_info = f" (сезон {season})" if (media_type == "tv" and season) else ""

    lines = [
        "🍿 <b>Сегодня премьера!</b>\n",
        f"Вышел долгожданный релиз: <b>{title}</b>{season_info}! 🎉",
    ]

    if air_date:
        lines.append(f"📅 <b>Дата:</b> <code>{format_date_ru(air_date)}</code>")

    lines.append("Приятного просмотра!")

    if url:
        lines.append(f"\n🔗 <a href='{url}'>Подробнее на TMDB</a>")

    return "\n".join(lines)


def format_reminder_notification(item: Any, days_left: int = 3) -> str:
    """Форматирует уведомление-напоминание перед датой выхода."""
    title = getattr(item, "title", "Без названия")
    air_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
    url = getattr(item, "tmdb_url", "")
    network = getattr(item, "network", None)

    lines = [
        "⏰ <b>Скоро премьера!</b>\n",
        f"До выхода <b>{title}</b> осталось дней: <b>{days_left}</b>!",
    ]

    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    if air_date:
        lines.append(f"📅 <b>Дата премьеры:</b> <code>{format_date_ru(air_date)}</code>")

    if url:
        lines.append(f"\n🔗 <a href='{url}'>TMDB</a>")

    return "\n".join(lines)


def format_item_list(items: list[Any]) -> str:
    """Форматирует список отслеживаемых проектов с датами в формате ДД.ММ.ГГГГ."""
    if not items:
        return "📭 Ваш список ожидания пуст."

    lines = ["📋 <b>Ваш список ожидания:</b>\n"]

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
        date_info = f" (📅 {format_date_ru(next_date)})" if next_date else " (📅 дата неизвестна)"

        lines.append(f"{i}. {status_badge} {icon} <b>{title}</b>{network_str}{date_info}")

    lines.append("\n<i>Нажмите на кнопку ниже, чтобы открыть карточку проекта:</i>")
    return "\n".join(lines)


def format_welcome_message(first_name: str) -> str:
    """Приветственное сообщение с подсказками по меню."""
    return (
        f"Привет, <b>{first_name}</b>! 👋\n\n"
        "Я бот <b>КиноЖдун</b> 🎬\n\n"
        "Я отслеживаю официальные даты выхода новых сезонов сериалов "
        "и премьеры новых частей фильмов.\n\n"
        "<b>Как пользоваться:</b>\n"
        "• Нажмите <b>«🔍 Найти сериал / фильм»</b> в нижнем меню или просто напишите название в чат\n"
        "• Я покажу платформу (Netflix, HBO и др.), год и описание каждого варианта\n"
        "• Как только появится дата выхода — я пришлю уведомление со ссылкой на источник!\n\n"
        "👇 Используйте кнопки постоянного меню внизу экрана для быстрого доступа:"
    )


def format_help_message() -> str:
    """Подробная справка по боту."""
    return (
        "📖 <b>Справка по боту КиноЖдун</b>\n\n"
        "<b>Кнопки меню внизу:</b>\n"
        "🔍 <b>Найти сериал / фильм</b> — быстрый поиск по каталогу TMDB\n"
        "📋 <b>Мой список</b> — список всех ваших тайтлов в ожидании\n"
        "🔄 <b>Проверить статус</b> — запрос свежих данных с TMDB прямо сейчас\n"
        "📅 <b>Указать дату</b> — установить собственную дату в формате <code>ДД.ММ.ГГГГ</code>\n"
        "🗑 <b>Удалить из списка</b> — убрать сериал/фильм из отслеживания\n"
        "ℹ️ <b>Справка</b> — это сообщение\n\n"
        "💡 <i>Все даты в боте отображаются в удобном формате ДД.ММ.ГГГГ.</i>"
    )
