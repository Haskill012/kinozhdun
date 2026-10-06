"""Утилиты для форматирования сообщений бота КиноЖдун (эстетичная HTML-разметка)."""

import datetime
import html
import os
from typing import Any
from bot.services.season_dates import upcoming_season, season_premieres


def safe_html(text: Any) -> str:
    """Безопасное экранирование специальных символов HTML (&, <, >) для динамических текстов."""
    if text is None:
        return ""
    return html.escape(str(text).strip(), quote=False)


def site_title_url(media_type: str, tmdb_id: Any, site_url: str | None = None) -> str | None:
    if media_type not in ("movie", "tv") or not isinstance(tmdb_id, (int, str)):
        return None
    if not str(tmdb_id).isdigit() or int(tmdb_id) <= 0:
        return None
    base = (site_url or os.getenv("SITE_BASE_URL") or "https://kinojdun.ru").rstrip("/")
    return f"{base}/title/{media_type}/{int(tmdb_id)}"


def linked_title(title: Any, item: Any, media_type: str | None = None) -> str:
    if isinstance(item, dict):
        media = media_type or item.get("media_type", "movie")
        ident = item.get("tmdb_id") or item.get("id")
    else:
        media = media_type or getattr(item, "media_type", "movie")
        ident = getattr(item, "tmdb_id", None)
    url = site_title_url(media, ident)
    label = safe_html(title)
    return f'<a href="{html.escape(url, quote=True)}">{label}</a>' if url else label


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
        return "⏳ В ожидании анонса"

    status_map = {
        "Returning Series": "🔄 Продлён на новый сезон",
        "Ended": "🏁 Завершён (все сезоны вышли)",
        "Canceled": "❌ Закрыт / Отменён",
        "Released": "✅ Премьера состоялась",
        "Post Production": "🛠 Пост-продакшн (монтаж)",
        "In Production": "🎥 Идут съёмки / В производстве",
        "Planned": "📅 Запланирован",
        "Rumored": "🗣 По слухам",
        "waiting": "⏳ В ожидании анонса",
        "announced": "📢 Анонсирована дата выхода",
    }
    return status_map.get(status, f"ℹ️ {status}")


def format_search_results_message(query: str, results: list[dict[str, Any]]) -> str:
    """Красиво форматирует структурированное сообщение с результатами поиска."""
    safe_q = safe_html(query)
    if not results:
        return (
            f"🔍 <b>Поиск:</b> <i>«{safe_q}»</i>\n\n"
            "По вашему запросу ничего не найдено.\n"
            "Попробуйте написать название иначе или проверить опечатки."
        )

    lines = [
        f"🔎 <b>Результаты поиска по запросу «{safe_q}»</b>\n",
    ]
    numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]

    for i, res in enumerate(results[:6]):
        num_icon = numbers[i] if i < len(numbers) else f"{i + 1}."
        media_type = res.get("media_type", "movie")
        icon = "📺" if media_type == "tv" else "🎬"
        type_str = "Сериал" if media_type == "tv" else "Фильм"
        title = linked_title(res.get("title") or res.get("name") or "Без названия", res)

        raw_date = res.get("release_date")
        date_str = format_date_ru(raw_date)
        date_label = f" ({date_str})" if date_str else ""

        network = safe_html(res.get("network"))
        rating = res.get("vote_average") or 0.0

        details_parts = [type_str]
        if network:
            details_parts.append(network)
        if media_type == "tv" and res.get("number_of_seasons"):
            details_parts.append(f"{res['number_of_seasons']} сезон(а)")
        if rating > 0:
            details_parts.append(f"⭐ {rating:.1f}")

        details_str = " • ".join(details_parts)

        overview = safe_html(res.get("overview", "")).strip()
        if len(overview) > 130:
            overview = overview[:127] + "..."
        overview_str = f"\n   <i>«{overview}»</i>" if overview else ""

        lines.append(
            f"{num_icon} {icon} <b>{title}</b>{date_label}\n"
            f"   └ <i>{details_str}</i>"
            f"{overview_str}\n"
        )

    lines.append("👇 <i>Нажмите кнопку ниже, чтобы открыть карточку проекта:</i>")
    return "\n".join(lines)


def format_item_details(item: Any, media_type_hint: str | None = None) -> str:
    """Форматирует детальную карточку проекта в стильном дизайне."""
    if isinstance(item, dict):
        media_type = media_type_hint or item.get("media_type", "movie")
        raw_title = item.get("title") or item.get("name") or "Без названия"
        title = linked_title(raw_title, item, media_type)
        orig_title = safe_html(item.get("original_title") or item.get("original_name"))
        status_raw = item.get("status", "")
        network = safe_html(item.get("network"))
        seasons_count = item.get("number_of_seasons")
        next_ep = item.get("next_episode_to_air")
        next_date = upcoming_season(item)[1] if media_type == "tv" else item.get("release_date")
        custom_date = None
        first_date = item.get("first_air_date")
        overview = safe_html(item.get("overview", ""))
        rating = item.get("vote_average")
    else:
        media_type = getattr(item, "media_type", media_type_hint or "movie")
        raw_title = getattr(item, "title", "Без названия")
        title = linked_title(raw_title, item)
        orig_title = safe_html(getattr(item, "original_title", None))
        status_raw = getattr(item, "status", "")
        network = safe_html(getattr(item, "network", None))
        seasons_count = getattr(item, "last_known_season", None)
        next_date = getattr(item, "next_air_date", None)
        custom_date = getattr(item, "custom_date", None)
        first_date = None  # Last aired episode is not the first release.
        overview = safe_html(getattr(item, "overview", ""))
        rating = getattr(item, "vote_average", None)

    icon = "📺" if media_type == "tv" else "🎬"
    type_label = "Сериал" if media_type == "tv" else "Фильм"

    lines = [
        f"{icon} <b>{title}</b>",
    ]
    if orig_title and orig_title != safe_html(raw_title):
        lines.append(f"<i>({linked_title(html.unescape(orig_title), item, media_type)})</i>")

    lines.append("")
    lines.append(f"🏷 <b>Категория:</b> {type_label}")

    if network:
        lines.append(f"🏢 <b>Платформа / Студия:</b> {network}")

    lines.append(f"📊 <b>Статус проекта:</b> {format_status_emoji(status_raw)}")

    if media_type == "tv" and seasons_count:
        lines.append(f"🎞 <b>Сезонов в каталоге:</b> {seasons_count}")

    if rating and float(rating) > 0:
        lines.append(f"⭐ <b>Рейтинг TMDB:</b> {float(rating):.1f} / 10")

    if next_date:
        label = "Дата премьеры нового сезона" if media_type == "tv" else "Дата премьеры фильма"
        lines.append(f"📅 <b>{label}:</b> <b>{format_date_ru(next_date)}</b>")
    else:
        label = "Дата премьеры нового сезона" if media_type == "tv" else "Дата премьеры фильма"
        lines.append(f"📅 <b>{label}:</b> <i>пока не объявлена</i> 🔍")

    if media_type == "tv" and isinstance(item, dict):
        aired = [(n, d) for n, d in season_premieres(item) if d < datetime.date.today()]
        if aired:
            number, premiered = aired[-1]
            lines.append(f"✅ <b>Премьера {number}-го сезона состоялась:</b> {format_date_ru(premiered)}")
        episode = item.get("next_episode_to_air") or {}
        if episode.get("air_date") and episode.get("episode_number"):
            lines.append(f"📺 <b>Следующая серия:</b> {format_date_ru(episode['air_date'])} ({episode.get('season_number', '?')} сезон, {episode['episode_number']} серия)")

    if custom_date:
        lines.append(f"⏰ <b>Ваше личное напоминание:</b> <b>{format_date_ru(custom_date)}</b>")

    if first_date:
        lines.append(f"🗓 <b>Первый релиз:</b> {format_date_ru(first_date)}")

    if overview and len(overview.strip()) > 0:
        lines.append("")
        ov = overview.strip()
        if len(ov) > 280:
            ov = ov[:277] + "..."
        lines.append(f"📝 <b>Сюжет:</b>\n<i>«{ov}»</i>")

    return "\n".join(lines)


def format_status_change_notification(item: Any, info: dict[str, Any]) -> str:
    """Форматирует красивое персональное уведомление об изменении статуса проекта."""
    title = linked_title(getattr(item, "title", "Без названия"), item)
    media_type = getattr(item, "media_type", "movie")
    type_label = "сериала" if media_type == "tv" else "фильма"
    raw_status = info.get("status") or getattr(item, "status", "")
    status_ru = format_status_emoji(raw_status)
    network = safe_html(getattr(item, "network", None))

    lines = [
        f"🔔 <b>Статус {type_label} изменился!</b>\n",
        f"🎬 <b>«{title}»</b>",
    ]
    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    lines.append(f"📊 <b>Текущий статус:</b> {status_ru}")

    if raw_status == "Ended":
        lines.append("\n🏁 <i>Сериал официально завершён, все вышедшие серии являются финальными.</i>")
    elif raw_status == "Returning Series":
        lines.append("\n🔄 <i>Сериал продлён! Бот сообщит, как только станет известна дата нового сезона.</i>")
    elif raw_status == "Canceled":
        lines.append("\n❌ <i>Производство проекта остановлено. Мы сообщим, если статус изменится.</i>")

    return "\n".join(lines)


def format_announced_notification(item: Any, update: dict[str, Any]) -> str:
    """Форматирует персональное уведомление о появлении официальной даты выхода."""
    title = linked_title(getattr(item, "title", "Без названия"), item)
    season = update.get("next_season")
    air_date = update.get("next_air_date")
    network = safe_html(getattr(item, "network", None))
    media_type = getattr(item, "media_type", "movie")

    season_str = f" • {season} сезон" if (media_type == "tv" and season) else ""

    lines = [
        "🎉 <b>Объявлена дата премьеры!</b>\n",
        f"🎬 <b>«{title}»</b>{season_str}",
    ]

    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    if air_date:
        lines.append(f"📅 <b>Дата выхода:</b> <b>{format_date_ru(air_date)}</b>")

    lines.append("\n🍿 <i>Кинождун напомнит вам о релизе за 3 дня и в день премьеры!</i>")
    return "\n".join(lines)


def format_released_notification(item: Any) -> str:
    """Форматирует персональное уведомление о премьере."""
    title = linked_title(getattr(item, "title", "Без названия"), item)
    season = getattr(item, "next_season_number", None) or getattr(item, "last_known_season", None)
    media_type = getattr(item, "media_type", "movie")
    air_date = getattr(item, "next_air_date", None)
    network = safe_html(getattr(item, "network", None))

    season_info = f" (сезон {season})" if (media_type == "tv" and season) else ""
    net_info = f" на {network}" if network else ""

    lines = [
        "🍿 <b>Премьера состоялась!</b>\n",
        f"🎬 <b>«{title}»</b>{season_info}{net_info}! 🎉",
    ]

    if air_date:
        lines.append(f"📅 <b>Дата релиза:</b> <b>{format_date_ru(air_date)}</b>")

    lines.append("\n✨ <i>Релиз уже доступен для просмотра. Приятного отдыха!</i>")
    return "\n".join(lines)


def format_episode_tomorrow_notification(item: Any, episode: dict) -> str:
    title = linked_title(getattr(item, "title", "Без названия"), item)
    lines = ["📺 <b>Уже завтра выходит новая серия!</b>\n",
             f"🎬 <b>«{title}»</b>",
             f"🎞 <b>{episode['season_number']} сезон, {episode['episode_number']} серия</b>",
             f"📅 <b>Дата выхода:</b> {format_date_ru(episode['air_date'])}"]
    network = safe_html(getattr(item, "network", None))
    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    lines.append("\n🍿 <i>По данным TMDB. Доступность зависит от региона и платформы.</i>")
    return "\n".join(lines)


def format_reminder_notification(item: Any, days_left: int = 3) -> str:
    """Форматирует персональное напоминание за несколько дней до даты."""
    title = linked_title(getattr(item, "title", "Без названия"), item)
    air_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
    network = safe_html(getattr(item, "network", None))
    season = getattr(item, "next_season_number", None)
    media_type = getattr(item, "media_type", "movie")

    season_str = f" (сезон {season})" if (media_type == "tv" and season) else ""
    days_word = "дня" if days_left in (2, 3, 4) else "дней"
    if days_left == 1:
        days_word = "день"

    lines = [
        f"⏰ <b>Скоро премьера — осталось {days_left} {days_word}!</b>\n",
        f"🎬 <b>«{title}»</b>{season_str}",
    ]

    if network:
        lines.append(f"🏢 <b>Платформа:</b> {network}")
    if air_date:
        lines.append(f"📅 <b>Дата выхода:</b> <b>{format_date_ru(air_date)}</b>")

    lines.append("\n🍿 <i>Не забудьте подготовить попкорн к премьере!</i>")
    return "\n".join(lines)


def format_item_list(items: list[Any]) -> str:
    """Форматирует список отслеживаемых тайтлов."""
    if not items:
        return (
            "🍿 <b>МОЙ КИНОЖДУН</b>\n\n"
            "📭 Ваш список ожидания пока пуст.\n\n"
            "Нажмите <b>«🔍 Найти фильм / сериал»</b> ниже или просто отправьте название тайтла в чат!"
        )

    lines = [
        "🍿 <b>МОЙ КИНОЖДУН</b>",
        f"Вы отслеживаете проектов: <b>{len(items)}</b>\n",
    ]

    for i, item in enumerate(items, 1):
        status = getattr(item, "status", "waiting")
        icon = "📺" if getattr(item, "media_type", "") == "tv" else "🎬"

        status_badge = "⏳"
        if status == "announced":
            status_badge = "📢"
        elif status == "released":
            status_badge = "✅"
        elif status == "ended":
            status_badge = "🏁"

        title = linked_title(getattr(item, "title", "Без названия"), item)
        network = safe_html(getattr(item, "network", None))
        network_str = f" • {network}" if network else ""

        next_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
        date_info = f" — <b>{format_date_ru(next_date)}</b>" if next_date else " — <i>дата не объявлена</i>"

        lines.append(f"{i}. {status_badge} {icon} <b>{title}</b>{network_str}{date_info}")

    lines.append("\n📤 <i>Нажмите <b>«📤 Поделиться моим Кинождуном»</b> вверху, чтобы отправить подборку друзьям!</i>")
    return "\n".join(lines)


def format_welcome_message(first_name: str) -> str:
    """Приветственное сообщение."""
    safe_name = safe_html(first_name)
    return (
        "🎬 <b>КИНОЖДУН</b> • Личный трекер премьер\n\n"
        f"Привет, <b>{safe_name}</b>! 👋\n\n"
        "Я слежу за выходом новых сезонов сериалов и продолжений фильмов в официальных каталогах "
        "(TMDB, Netflix, HBO, Disney+, Apple TV+ и др.).\n\n"
        "✨ <b>Возможности бота:</b>\n"
        "• 🔍 <b>Поиск и отслеживание</b>: напишите название любого фильма или сериала\n"
        "• 🍿 <b>«Мой Кинождун»</b>: ваш личный список ожидания + кнопка «📤 Поделиться списком»\n"
        "• 📤 <b>Виральный шеринг</b>: делитесь фильмами с друзьями в 1 клик через ссылку\n"
        "• 🔔 <b>Уведомления</b>: даты премьер и обновления только по вашему списку ожидания\n\n"
        "👇 <b>Быстрый доступ через меню внизу:</b>"
    )


def format_help_message() -> str:
    """Справка по возможностям бота."""
    return (
        "📖 <b>СПРАВКА ПО БОТУ КИНОЖДУН</b>\n\n"
        "<b>Кнопки меню внизу экрана:</b>\n"
        "🔍 <b>Найти фильм / сериал</b> — поиск любого кино и выбор из списка\n"
        "🍿 <b>Мой Кинождун</b> — ваш список ожидания + кнопка «📤 Поделиться списком»\n"
        "🔄 <b>Проверить статус</b> — запрос свежих дат с TMDB прямо сейчас\n"
        "📅 <b>Своя дата</b> — установка личной даты напоминания (ДД.ММ.ГГГГ)\n"
        "🗑 <b>Удалить из списка</b> — удаление проекта из отслеживания\n"
        "ℹ️ <b>Справка и помощь</b> — это справочное руководство\n\n"
        "🔔 <b>В боте</b> — личные уведомления по вашему списку ожидания.\n"
        "🍿 <b>В публичном канале</b> — подборки и дайджесты премьер.\n\n"
        "💡 <i>Подсказка: Вы можете поделиться любым фильмом или всем своим списком ожидания с друзьями!</i>"
    )


def format_shared_item_prompt(title: str, details: dict[str, Any], media_type: str) -> str:
    """Форматирует карточку проекта для получателя ссылки шеринга."""
    safe_title = linked_title(title, details, media_type)
    icon = "📺" if media_type == "tv" else "🎬"
    type_str = "сериал" if media_type == "tv" else "фильм"
    network = safe_html(details.get("network"))
    net_str = f"\n🏢 <b>Платформа:</b> {network}" if network else ""

    next_date = None
    if media_type == "tv":
        next_ep = details.get("next_episode_to_air")
        if next_ep and next_ep.get("air_date"):
            next_date = next_ep["air_date"]
    else:
        next_date = details.get("release_date")

    date_str = f"\n📅 <b>Дата выхода:</b> <b>{format_date_ru(next_date)}</b>" if next_date else "\n📅 <b>Дата выхода:</b> <i>пока не объявлена</i>"

    overview = safe_html(details.get("overview", "")).strip()
    if len(overview) > 200:
        overview = overview[:197] + "..."
    overview_str = f"\n\n📝 <i>«{overview}»</i>" if overview else ""

    return (
        f"🍿 <b>Тоже ждёшь «{safe_title}»?</b>\n\n"
        f"Друг поделился с вами {type_str}ом {icon} <b>«{safe_title}»</b>.{net_str}{date_str}{overview_str}\n\n"
        "Кинождун пришлёт вам уведомление, как только появится официальная дата премьеры, трейлер или новый сезон 🍿\n\n"
        "👇 <i>Нажмите <b>«🔔 Отслеживать»</b> ниже, чтобы добавить в свой список в 1 клик:</i>"
    )


def format_shared_watchlist_message(items: list[dict[str, Any]], title: str = "Список ожидания") -> str:
    """Форматирует карточку расшаренного списка для получателя."""
    safe_title = safe_html(title)
    if not items:
        return (
            f"🍿 <b>{safe_title}</b>\n\n"
            "Этот список ожидания пуст."
        )

    lines = [
        f"🍿 <b>{safe_title}</b>",
        f"Всего тайтлов: <b>{len(items)}</b>\n",
        "Вот какие фильмы и сериалы сейчас ждёт автор списка:\n",
    ]

    for i, it in enumerate(items, 1):
        m_type = it.get("media_type", "movie")
        icon = "📺" if m_type == "tv" else "🎬"
        item_title = linked_title(it.get("title", "Без названия"), it)
        network = safe_html(it.get("network"))
        net_str = f" • {network}" if network else ""

        next_date = it.get("next_air_date")
        date_str = f" — <b>{format_date_ru(next_date)}</b>" if next_date else " — <i>дата не объявлена</i>"

        lines.append(f"{i}. {icon} <b>{item_title}</b>{net_str}{date_str}")

    lines.append("\n👇 <i>Выберите позиции для добавления или нажмите «➕ Отслеживать всё»:</i>")
    return "\n".join(lines)


def format_channel_referral_prompt(post: Any) -> str:
    """Форматирует карточку для пользователя, перешедшего из Telegram-канала."""
    post_type = getattr(post, "post_type", "news")
    if post_type in ("daily_digest", "weekly_digest"):
        title = safe_html(getattr(post, "title", "Премьеры"))
        return (
            f"🍿 <b>{title}</b>\n\n"
            "Вы перешли по подборке премьер из нашего Telegram-канала!\n\n"
            "Воспользуйтесь поиском в меню ниже, чтобы добавить интересующие фильмы и сериалы в свой Кинождун 🍿"
        )

    media_type = getattr(post, "media_type", "")
    icon = "📺" if media_type == "tv" else "🎬"
    title = linked_title(getattr(post, "title", "Без названия"), post)
    season_number = getattr(post, "season_number", None)

    season_suffix = f" — сезон {season_number}" if (media_type == "tv" and season_number) else ""
    headline = f"🍿 <b>Тоже ждёшь «{title}{season_suffix}»?</b>"

    network = safe_html(getattr(post, "network", None))
    net_str = f"\n🏢 <b>Платформа / Студия:</b> {network}" if network else ""

    air_date = getattr(post, "air_date", None)
    date_str = f"\n📅 <b>Дата премьеры:</b> <b>{format_date_ru(air_date)}</b>" if air_date else "\n📅 <b>Дата премьеры:</b> <i>уточняется</i>"

    return (
        f"🔥 <b>Новость из Telegram-канала «Кинождун»</b>\n\n"
        f"{headline}\n"
        f"{icon} <b>{title}</b>{season_suffix}{net_str}{date_str}\n\n"
        "Кинождун сообщит вам, как только появятся важные новости, трейлеры или выйдет премьера 🍿\n\n"
        "👇 <i>Нажмите кнопку ниже, чтобы начать отслеживание в 1 клик:</i>"
    )
