"""Инлайн-обработчик для красивого вирального шеринга карточек фильмов и сериалов."""

import json
import logging
from typing import Optional
from aiogram import Router, F
from aiogram.types import (
    InlineQuery,
    InlineQueryResultPhoto,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode

from bot.config import Settings
from bot.services.tmdb import TMDBClient
from bot.utils.formatting import safe_html, linked_title, site_title_url, format_date_ru, format_shared_watchlist_message
from bot.db.repositories import Repository
from bot.handlers.start import parse_content_deep_link, parse_watchlist_deep_link

logger = logging.getLogger(__name__)

router = Router(name="inline_router")


@router.inline_query()
async def process_inline_query(inline_query: InlineQuery) -> None:
    """Обрабатывает инлайн-запросы для шеринга карточек фильмов, списков и поиска."""
    raw_query = (inline_query.query or "").strip()
    session_factory = inline_query.bot["session_factory"]
    tmdb_client: TMDBClient = inline_query.bot["tmdb_client"]
    settings: Settings = inline_query.bot["settings"]
    bot_username = getattr(settings, "BOT_USERNAME", "kinojdun_bot") or "kinojdun_bot"

    # --- 1. Шеринг конкретного фильма/сериала: share_<media_type>_<tmdb_id>[_u<referrer_id>] ---
    parsed_content = parse_content_deep_link(raw_query)
    if parsed_content:
        media_type, tmdb_id, referrer_id = parsed_content
        if not referrer_id and inline_query.from_user:
            referrer_id = inline_query.from_user.id

        try:
            if media_type == "tv":
                details = await tmdb_client.get_tv_details(tmdb_id)
            else:
                details = await tmdb_client.get_movie_details(tmdb_id)
        except Exception as e:
            logger.error(f"Ошибка получения данных из TMDB для инлайн-шеринга: {e}")
            details = {}

        if details and (details.get("title") or details.get("name")):
            title = details.get("title") or details.get("name") or "Без названия"
            safe_title = linked_title(title, {"media_type": media_type, "tmdb_id": tmdb_id})
            poster_path = details.get("poster_path")
            network = safe_html(details.get("network"))
            net_str = f" • {network}" if network else ""
            type_icon = "📺" if media_type == "tv" else "🎬"
            type_str = "сериал" if media_type == "tv" else "фильм"
            type_label = "Сериал" if media_type == "tv" else "Фильм"

            if media_type == "tv":
                next_ep = details.get("next_episode_to_air")
                if next_ep and isinstance(next_ep, dict) and next_ep.get("air_date"):
                    date_val = next_ep["air_date"]
                    season_num = next_ep.get("season_number")
                    ep_num = next_ep.get("episode_number")
                    ep_str = f" ({season_num} сезон, {ep_num} серия)" if season_num else ""
                    date_str = f"\n📅 <b>Следующая серия:</b> <b>{format_date_ru(date_val)}</b>{ep_str}"
                else:
                    first_air = details.get("first_air_date")
                    date_str = f"\n📅 <b>Дата премьеры:</b> <b>{format_date_ru(first_air)}</b>" if first_air else "\n📅 <b>Дата выхода:</b> <i>уточняется</i>"
            else:
                rel_date = details.get("release_date")
                date_str = f"\n📅 <b>Дата премьеры:</b> <b>{format_date_ru(rel_date)}</b>" if rel_date else "\n📅 <b>Дата премьеры:</b> <i>пока не объявлена</i>"

            overview = safe_html(details.get("overview", "")).strip()
            if len(overview) > 200:
                overview = overview[:197] + "..."
            overview_str = f"\n\n📝 <i>«{overview}»</i>" if overview else ""

            caption = (
                f"🍿 <b>Я жду {type_str} «{safe_title}»!</b>\n\n"
                f"{type_icon} <b>{type_label}</b>{net_str}{date_str}{overview_str}\n\n"
                f"Кинождун сообщит, когда появятся новости и объявят дату выхода 🎬"
            )

            ref_part = f"_u{referrer_id}" if referrer_id else ""
            deep_link = f"https://t.me/{bot_username}?start=c_{media_type}_{tmdb_id}{ref_part}"
            clean_btn = title if len(title) <= 24 else title[:21] + "..."

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🔔 Отслеживать «{clean_btn}»",
                        url=deep_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🍿 Открыть Кинождун",
                        url=f"https://t.me/{bot_username}?start=ref_{referrer_id}" if referrer_id else f"https://t.me/{bot_username}",
                    )
                ]
            ])

            keyboard.inline_keyboard.append([InlineKeyboardButton(text="🌐 Карточка и новости на сайте", url=site_title_url(media_type, tmdb_id))])
            results = []
            if poster_path:
                photo_url = f"https://image.tmdb.org/t/p/w780{poster_path}"
                thumb_url = f"https://image.tmdb.org/t/p/w185{poster_path}"
                results.append(
                    InlineQueryResultPhoto(
                        id=f"p_{media_type}_{tmdb_id}",
                        photo_url=photo_url,
                        thumbnail_url=thumb_url,
                        title=f"🍿 «{title}» (с постером)",
                        description=f"Отправить красивую карточку с постером и кнопкой",
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                )

            # Текстовый вариант как резерв/альтернатива
            results.append(
                InlineQueryResultArticle(
                    id=f"a_{media_type}_{tmdb_id}",
                    title=f"🍿 «{title}» (текст)",
                    description=f"Отправить текстовую карточку с кнопкой",
                    thumbnail_url=f"https://image.tmdb.org/t/p/w185{poster_path}" if poster_path else None,
                    input_message_content=InputTextMessageContent(
                        message_text=caption,
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=keyboard,
                )
            )

            await inline_query.answer(results, cache_time=120, is_personal=True)
            return

    # --- 2. Шеринг списка ожидания: list_<token> или w_<token> ---
    watchlist_token = parse_watchlist_deep_link(raw_query)
    if not watchlist_token and raw_query.startswith("list_"):
        watchlist_token = raw_query[5:]

    if watchlist_token:
        try:
            async with session_factory() as session:
                repo = Repository(session)
                shared = await repo.get_shared_watchlist_by_token(watchlist_token)
        except Exception as e:
            logger.error(f"Ошибка получения списка ожидания по токену {watchlist_token}: {e}")
            shared = None

        if shared:
            items = json.loads(shared.items_json) if shared.items_json else []
            title = shared.title or "Мой Кинождун"
            text = format_shared_watchlist_message(items, title)
            deep_link = f"https://t.me/{bot_username}?start=w_{watchlist_token}"

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🍿 Открыть этот список ожидания",
                        url=deep_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="➕ Отслеживать всё",
                        url=deep_link,
                    )
                ]
            ])

            results = [
                InlineQueryResultArticle(
                    id=f"list_{watchlist_token}",
                    title=f"🍿 {title} ({len(items)} тайтлов)",
                    description="Отправить список ожидания в чат",
                    input_message_content=InputTextMessageContent(
                        message_text=text,
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=keyboard,
                )
            ]
            await inline_query.answer(results, cache_time=120, is_personal=True)
            return

    # --- 3. Поиск фильмов/сериалов на лету: @kinojdun_bot <название> ---
    if len(raw_query) >= 2:
        try:
            search_results = await tmdb_client.search_multi(raw_query)
        except Exception as e:
            logger.error(f"Ошибка инлайн-поиска TMDB по '{raw_query}': {e}")
            search_results = []

        referrer_id = inline_query.from_user.id if inline_query.from_user else None
        results = []

        for item in search_results[:6]:
            m_type = item.get("media_type", "movie")
            t_id = item.get("tmdb_id") or item.get("id")
            t_title = item.get("title") or "Без названия"
            safe_t = linked_title(t_title, item)
            p_path = item.get("poster_path")
            network = safe_html(item.get("network"))
            net_str = f" • {network}" if network else ""
            t_label = "Сериал" if m_type == "tv" else "Фильм"
            t_icon = "📺" if m_type == "tv" else "🎬"
            d_val = item.get("release_date")
            d_str = f"\n📅 <b>Дата выхода:</b> <b>{format_date_ru(d_val)}</b>" if d_val else ""

            overview = safe_html(item.get("overview", "")).strip()
            if len(overview) > 160:
                overview = overview[:157] + "..."
            overview_str = f"\n\n📝 <i>«{overview}»</i>" if overview else ""

            c_text = (
                f"🍿 <b>Я жду {t_label.lower()} «{safe_t}»!</b>\n\n"
                f"{t_icon} <b>{t_label}</b>{net_str}{d_str}{overview_str}\n\n"
                f"Кинождун сообщит, когда появятся новости и объявят дату выхода 🎬"
            )

            ref_part = f"_u{referrer_id}" if referrer_id else ""
            d_link = f"https://t.me/{bot_username}?start=c_{m_type}_{t_id}{ref_part}"
            clean_btn = t_title if len(t_title) <= 24 else t_title[:21] + "..."

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔔 Отслеживать «{clean_btn}»", url=d_link)],
                [InlineKeyboardButton(text="🍿 Открыть Кинождун", url=f"https://t.me/{bot_username}")],
            ])

            kb.inline_keyboard.append([InlineKeyboardButton(text="🌐 Карточка и новости на сайте", url=site_title_url(m_type, t_id))])
            if p_path:
                results.append(
                    InlineQueryResultPhoto(
                        id=f"s_p_{m_type}_{t_id}",
                        photo_url=f"https://image.tmdb.org/t/p/w780{p_path}",
                        thumbnail_url=f"https://image.tmdb.org/t/p/w185{p_path}",
                        title=f"{t_icon} {t_title}",
                        description=f"{t_label}{net_str}",
                        caption=c_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb,
                    )
                )
            else:
                results.append(
                    InlineQueryResultArticle(
                        id=f"s_a_{m_type}_{t_id}",
                        title=f"{t_icon} {t_title}",
                        description=f"{t_label}{net_str}",
                        input_message_content=InputTextMessageContent(
                            message_text=c_text,
                            parse_mode=ParseMode.HTML,
                        ),
                        reply_markup=kb,
                    )
                )

        if results:
            await inline_query.answer(results, cache_time=60, is_personal=True)
            return

    # --- 4. Пустой запрос или подсказка ---
    hint_result = [
        InlineQueryResultArticle(
            id="hint",
            title="🔍 Поиск фильмов и сериалов",
            description="Введите название фильма или сериала, чтобы поделиться им с другом",
            input_message_content=InputTextMessageContent(
                message_text=(
                    "🍿 <b>Кинождун</b> — бот для отслеживания дат выхода фильмов и сериалов.\n\n"
                    "Введите название фильма или сериала после @kinojdun_bot, чтобы отправить карточку в чат!"
                ),
                parse_mode=ParseMode.HTML,
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🍿 Открыть Кинождун", url=f"https://t.me/{bot_username}")],
            ]),
        )
    ]
    await inline_query.answer(hint_result, cache_time=300, is_personal=True)
