"""Движок вариативности текстов (Spintax) и шаблоны публикаций для ВКонтакте без AI."""

import random
import re
import html
from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Optional


def render_spintax(text: str, rng: Optional[random.Random] = None) -> str:
    """Рекурсивно разворачивает шаблоны в синтаксисе {вариант 1|вариант 2|...}

    Поддерживает вложенность любой глубины.
    Если внутри фигурных скобок нет символа '|' (например, одиночные скобки),
    они не затрагиваются.
    """
    if rng is None:
        rng = random.Random()

    # Ищем самые глубокие скобки, содержащие знак '|'
    pattern = re.compile(r"\{([^{}]*\|[^{}]*)\}")

    while True:
        match = pattern.search(text)
        if not match:
            break
        options = match.group(1).split("|")
        choice = rng.choice(options)
        text = text[: match.start()] + choice + text[match.end() :]

    return text


def clean_synopsis(overview: Optional[str], max_len: int = 320) -> str:
    """Очищает и аккуратно обрезает синопсис по границе слов."""
    if not overview:
        return ""
    cleaned = re.sub(r"\s+", " ", html.unescape(overview).strip())
    # Убираем HTML-теги
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    if len(cleaned) <= max_len:
        return cleaned

    truncated = cleaned[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > int(max_len * 0.7):
        truncated = truncated[:last_space]
    return truncated.rstrip(",.-;: ") + "..."


def format_date_ru(d: Optional[date]) -> str:
    """Форматирует дату в привычный русский вид: '15 октября 2026 г.'"""
    if not d:
        return "скоро"
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    return f"{d.day} {months[d.month - 1]} {d.year} г."


def make_hashtag(word: str) -> str:
    """Преобразует слово в валидный хештег без пробелов и спецсимволов."""
    clean = re.sub(r"[^\wа-яА-ЯёЁ]", "", word)
    return f"#{clean.lower()}" if clean else ""


# Шаблоны для различных кино-событий с вариативностью Spintax
VK_SPINTAX_TEMPLATES: dict[str, str] = {
    # 1. Объявление даты премьеры
    "announced": (
        "{🔥 Горячая премьера на горизонте!|📅 Запоминайте дату в календаре!|🎬 Отличные новости для киноманов!|🍿 Новое пополнение в списке ожиданий!}\n\n"
        "{Уже |Совсем скоро |Официально: |Зафиксировано: |}"
        "[DATE_STR] {состоится премьера [TYPE_GEN]|выйдет на экраны [TYPE_NOM]|выйдет в прокат [TYPE_NOM]|готовится к релизу [TYPE_NOM]} "
        "«[TITLE]»[SEASON_LABEL].\n\n"
        "[DETAILS_BLOCK]"
        "[SYNOPSIS_BLOCK]"
        "[CTA_BLOCK]\n\n"
        "[HASHTAGS]"
    ),
    # 2. Продление на новый сезон / анонс продолжения
    "renewed": (
        "{🔥 Официально: продолжению быть!|🎉 Отличные новости для фанатов!|🎬 Проект получил зелёный свет!}\n\n"
        "{Создатели официально подтвердили:|Студия дала добро на съёмки:|Создатели объявили, что} [TYPE_NOM] «[TITLE]» "
        "{продлён на следующий сезон|получит прямое продолжение|возвращается с новым сезоном}!\n\n"
        "[DETAILS_BLOCK]"
        "[SYNOPSIS_BLOCK]"
        "[CTA_BLOCK]\n\n"
        "[HASHTAGS]"
    ),
    # 3. Старт съёмок
    "filming_started": (
        "{🎬 Камера, мотор!|🎥 Съёмочный процесс официально стартовал!|⚡ Производство перешло в активную фазу!}\n\n"
        "{Начались съёмки [SEASON_GEN]|Стартовали съёмки [SEASON_GEN]|Команда приступила к работе над [SEASON_INS]} «[TITLE]».\n\n"
        "[DETAILS_BLOCK]"
        "[SYNOPSIS_BLOCK]"
        "[CTA_BLOCK]\n\n"
        "[HASHTAGS]"
    ),
    # 4. Трейлер
    "trailer": (
        "{▶ Появился свежий трейлер!|🔥 Смотрим первый взгляд на новинку!|🍿 Долгожданный трейлер уже в сети!}\n\n"
        "{Опубликован официальный трейлер к [TYPE_DAT]|Вышел новый видеоролик к [TYPE_DAT]|Появился трейлер [TYPE_GEN]} «[TITLE]»[SEASON_LABEL].\n\n"
        "[DETAILS_BLOCK]"
        "[SYNOPSIS_BLOCK]"
        "[CTA_BLOCK]\n\n"
        "[HASHTAGS]"
    ),
    # 5. Карточка из каталога / рекомендация
    "catalog_feature": (
        "{🍿 Что добавить в свой список ожидания?|✨ Обратите внимание на этот проект:|🎯 Выбор редакции КиноЖдуна:}\n\n"
        "[TYPE_NOM_CAP] «[TITLE]»[SEASON_LABEL][YEAR_STR].\n\n"
        "[DETAILS_BLOCK]"
        "[SYNOPSIS_BLOCK]"
        "[CTA_BLOCK]\n\n"
        "[HASHTAGS]"
    ),
}

# Вариативные блоки деталей
DETAILS_SPINTAX = (
    "{📌 Жанр: [GENRES]\n|🎭 Направление: [GENRES]\n|}"
    "{🏢 Платформа / Студия: [NETWORK]\n|📺 Производство: [NETWORK]\n|}"
    "{🗓 Дата выхода: [DATE_STR]\n|📅 Релиз: [DATE_STR]\n|}"
)

# Вариативные синопсисы
SYNOPSIS_SPINTAX = (
    "\n{📝 О чем история:|📖 Коротко о сюжете:|💡 Главная интрига:}\n«[SYNOPSIS]»\n"
)

# Призывы к действию (CTA)
CTA_SPINTAX = (
    "\n{Будете смотреть? Делитесь мнением в комментариях!|Ждёте новинку? Голосуйте в опросе ниже!|Добавили к себе в заметки?}"
    "\n\n{🔔 Таймер обратного отсчета и подробности — на сайте: [LINK]|"
    "🍿 Полный график премьер и трейлеры смотрите на КиноЖдуне: [LINK]|"
    "🌐 Карточка проекта на КиноЖдуне: [LINK]}"
)


def format_vk_post(
    title: str, media_type: str = "movie", event_type: str = "announced",
    season_number: Optional[int] = None, air_date: Optional[date] = None,
    genres: Optional[list[str]] = None, network: Optional[str] = None,
    overview: Optional[str] = None, site_url: str = "https://kinojdun.ru",
    item_id: Optional[int] = None, link_in_comment: bool = False,
    rng: Optional[random.Random] = None, create_poll: bool = True,
    episode_number: Optional[int] = None, source_url: Optional[str] = None,
) -> dict[str, Any]:
    """Complete factual copy with one destination and at most four navigation tags."""
    from bot.services.social_editorial import event_copy
    paragraphs, past = event_copy(
        title, media_type, event_type, season_number, episode_number, air_date,
        network, overview, genres=genres, tmdb_id=item_id, source_url=source_url,
        date_formatter=format_date_ru,
    )
    target_link = (f"{site_url.rstrip('/')}/title/{media_type}/{item_id}" if item_id
                   else f"{site_url.rstrip('/')}/calendar")
    action = "Сохранить в список просмотра" if past or event_type == "catalog_feature" else "Дата выхода и напоминания"
    destination = f"{action}:\n{target_link}"
    engagement = "Будете смотреть? Голосуйте в опросе ниже." if create_poll else "Что заинтересовало в этом проекте? Обсудим в комментариях."
    tags = ["#кино", "#сериалы" if media_type == "tv" else "#фильмы", "#кинождун"]
    if genres:
        genre_tag = make_hashtag(genres[0])
        if genre_tag and genre_tag not in tags:
            tags.append(genre_tag)
    paragraphs += [engagement, "Карточка проекта — в первом комментарии." if link_in_comment else destination, " ".join(tags)]
    return {"text": "\n\n".join(paragraphs), "comment_text": destination if link_in_comment else "",
            "poll": {"question": f"Будете смотреть «{clean_synopsis(title, 160)}»?",
                     "answers": ["Да, добавлю в список", "Решу после отзывов", "Пропущу"]},
            "hashtags": tags, "target_url": target_link}
