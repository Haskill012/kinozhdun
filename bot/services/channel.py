"""Сервис автоматической публикации значимых новостей в Telegram-канал «Кинождун 🍿»."""

import datetime
import hashlib
import json
import logging
import re
from typing import Any, Optional
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.services.digest_style import render_digest, telegram_text_length
from bot.services.episode_reminders import episodes_on_date
from bot.services.season_dates import season_premieres
from bot.config import Settings
from bot.db.models import ChannelPost
from bot.db.repositories import Repository
from bot.utils.formatting import format_date_ru, safe_html, linked_title
from shared.audience import audience_metadata, exclusion_reason

logger = logging.getLogger(__name__)


def generate_event_fingerprint(
    tmdb_id: Optional[int],
    media_type: Optional[str],
    event_type: str,
    season_number: Optional[int] = None,
    extra_key: Optional[str] = None,
) -> str:
    """Генерирует стабильный хэш дедупликации (event fingerprint) для любых типов событий."""
    tmdb_str = str(tmdb_id) if tmdb_id is not None else "notmdb"
    media_str = str(media_type) if media_type else "nomedia"
    season_str = str(season_number) if season_number is not None else "noseason"
    extra_str = str(extra_key) if extra_key else "noextra"
    raw = f"{tmdb_str}:{media_str}:{event_type}:{season_str}:{extra_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def generate_content_hash(
    tmdb_id: int,
    media_type: str,
    event_type: str,
    season_number: Optional[int] = None,
    air_date: Optional[datetime.date] = None,
) -> str:
    """Обратная совместимость: хэш дедупликации по дате выхода."""
    date_str = air_date.isoformat() if air_date else "nodate"
    return generate_event_fingerprint(
        tmdb_id=tmdb_id,
        media_type=media_type,
        event_type=event_type,
        season_number=season_number,
        extra_key=date_str,
    )


GENRES_RU: dict[int, str] = {
    28: "боевик",
    12: "приключения",
    16: "мультфильм",
    35: "комедия",
    80: "криминал",
    99: "документальный",
    18: "драма",
    10751: "семейный",
    14: "фэнтези",
    36: "история",
    27: "ужасы",
    10402: "музыка",
    9648: "детектив",
    10749: "мелодрама",
    878: "фантастика",
    10770: "телефильм",
    53: "триллер",
    10752: "военный",
    37: "вестерн",
    10759: "боевик, приключения",
    10762: "детский",
    10765: "фантастика, фэнтези",
    10768: "политика",
}
EXCLUDED_GENRES = {10763, 10764, 10767}  # Новости, реалити-шоу, ток-шоу


def format_channel_post_text(
    title: str,
    media_type: Optional[str] = "tv",
    event_type: str = "announced",
    season_number: Optional[int] = None,
    air_date: Optional[datetime.date] = None,
    network: Optional[str] = None,
    overview: Optional[str] = None,
    old_air_date: Optional[datetime.date] = None,
    trailer_url: Optional[str] = None,
    items: Optional[list[dict[str, Any]]] = None,
    date_label: Optional[str] = None,
    site_url: str = "https://kinojdun.ru",
) -> str:
    """Форматирует красивый, лаконичный и вовлекающий пост для Telegram-канала в стиле Кинождуна."""
    title = safe_html(title)
    network = safe_html(network) if network else None
    overview = safe_html(overview) if overview else None
    type_label = "сериала" if media_type == "tv" else "фильма"
    type_word = "сериал" if media_type == "tv" else "фильм"
    type_word_ru = "Сериал" if media_type == "tv" else "Фильм"
    season_label = f" (сезон {season_number})" if (media_type == "tv" and season_number) else ""
    season_word = f"{season_number} сезон" if season_number else "новый сезон"

    # --- 1. Продление на новый сезон / анонс сиквела ---
    if event_type in ("renewed", "season_renewed"):
        if media_type == "tv":
            header = f"🔥 <b>«{title}» официально продлён на {season_word}</b>"
            studio_str = f"{network} подтвердил продолжение сериала." if network else "Официально подтверждено продолжение сериала."
        else:
            header = f"🔥 <b>Анонсировано продолжение фильма «{title}»</b>"
            studio_str = f"Студия {network} подтвердила разработку сиквела." if network else "Официально подтверждена разработка сиквела."

        date_line = f"\n📅 <b>Премьера:</b> <code>{format_date_ru(air_date)}</code>" if air_date else "\nТочная дата выхода пока не объявлена."

        body_parts = [studio_str + date_line]
        if overview and len(overview.strip()) > 0:
            ov = overview.strip()
            if len(ov) > 280:
                ov = ov[:277] + "..."
            body_parts.append(f"\n📝 <i>«{ov}»</i>")

        body_parts.append("\n🍿 <i>Кинождун сообщит, когда появятся новости о съёмках и дате премьеры.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 2. Объявление даты выхода ---
    elif event_type in ("date_announced", "announced"):
        season_prefix = f" ({season_word})" if (media_type == "tv" and season_number) else ""
        header = f"📅 <b>Объявлена дата выхода {season_label or type_label} «{title}»</b>"

        body_parts = []
        if air_date:
            body_parts.append(f"🗓 <b>Релиз:</b> <b>{format_date_ru(air_date)}</b>")
        if network:
            body_parts.append(f"🏢 <b>Платформа:</b> {network}")

        if overview and len(overview.strip()) > 0:
            ov = overview.strip()
            if len(ov) > 280:
                ov = ov[:277] + "..."
            body_parts.append(f"\n📝 <i>«{ov}»</i>")

        body_parts.append(f"\n🍿 <i>Добавь {type_word} в Кинождун — напомним о премьере.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 3. Перенос даты выхода ---
    elif event_type == "date_postponed":
        new_date_str = format_date_ru(air_date) if air_date else "не объявлена"
        old_date_str = format_date_ru(old_air_date) if old_air_date else "ранее"
        header = f"📅 <b>Премьеру «{title}»{season_label} перенесли</b>"

        body_parts = [
            f"🗓 <b>Новая дата выхода:</b> <b>{new_date_str}</b>",
            f"❌ <i>Ранее премьера ожидалась {old_date_str}</i>",
        ]
        if network:
            body_parts.append(f"🏢 <b>Студия:</b> {network}")

        body_parts.append("\n🍿 <i>Добавь проект в Кинождун — сообщим обо всех дальнейших изменениях.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 4. Начало съёмок ---
    elif event_type == "filming_started":
        target = f"{season_word}а сериала" if media_type == "tv" else "фильма"
        header = f"🎬 <b>Начались съёмки {target} «{title}»</b>"

        body_parts = ["Производство официально стартовало."]
        if network:
            body_parts.append(f"📺 <b>Платформа:</b> {network}")
        if air_date:
            body_parts.append(f"📅 <b>Релиз запланирован на:</b> <code>{format_date_ru(air_date)}</code>")

        if overview and len(overview.strip()) > 0:
            ov = overview.strip()
            if len(ov) > 280:
                ov = ov[:277] + "..."
            body_parts.append(f"\n📝 <i>«{ov}»</i>")

        body_parts.append("\n🍿 <i>Кинождун сообщит, когда объявят точную дату премьеры.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 5. Завершение съёмок ---
    elif event_type == "filming_finished":
        target = f"{season_word}а сериала" if media_type == "tv" else "фильма"
        header = f"🎬 <b>Завершились съёмки {target} «{title}»</b>"

        body_parts = ["Съёмочный процесс завершён, проект переходит на стадию пост-продакшна."]
        if network:
            body_parts.append(f"📺 <b>Платформа:</b> {network}")
        if air_date:
            body_parts.append(f"📅 <b>Премьера:</b> <code>{format_date_ru(air_date)}</code>")

        body_parts.append("\n🍿 <i>Кинождун сообщит о премьере и первом официальном трейлере.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 6. Официальный трейлер ---
    elif event_type == "trailer":
        target = f"нового сезона «{title}»" if (media_type == "tv" and season_number) else f"фильма «{title}»"
        header = f"🔥 <b>Вышел официальный трейлер {target}</b>"

        body_parts = []
        if air_date:
            body_parts.append(f"🗓 <b>Премьера состоится:</b> <b>{format_date_ru(air_date)}</b>")
        if network:
            body_parts.append(f"🏢 <b>Платформа:</b> {network}")

        if overview and len(overview.strip()) > 0:
            ov = overview.strip()
            if len(ov) > 240:
                ov = ov[:237] + "..."
            body_parts.append(f"\n📝 <i>«{ov}»</i>")

        body_parts.append("\n🍿 <i>Кинождун напомнит о премьере за 3 дня и в день выхода.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 7. Премьера состоялась ---
    elif event_type == "released":
        header = f"🍿 <b>Сегодня состоялась премьера {type_label} «{title}»{season_label}!</b>"
        body_parts = ["Релиз уже доступен для просмотра."]
        if network:
            body_parts.append(f"🏢 <b>Платформа:</b> {network}")
        body_parts.append("\n🎬 <i>Добавьте проект в личный список, чтобы не потерять.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    # --- 8. Закрытие / завершение ---
    elif event_type in ("canceled", "ended"):
        status_label = "официально закрыт" if event_type == "canceled" else "завершён"
        header = f"📢 <b>Сериал «{title}» {status_label}</b>"
        body_parts = []
        if network:
            body_parts.append(f"{network} принял решение не продолжать проект.")
        else:
            body_parts.append("Производство сериала завершено, новых сезонов не планируется.")
        body_parts.append("\n🍿 <i>В Кинождуне всегда можно найти другие интересные премьеры.</i>")
        return f"{header}\n\n" + "\n".join(body_parts)

    elif event_type in ("daily_digest", "weekly_digest"):
        return render_digest(items, date_label or format_date_ru(datetime.date.today()),
                             weekly=event_type == "weekly_digest", site_url=site_url)

    # --- Дефолтный формат новостного поста ---
    header = f"🎬 <b>«{title}»{season_label}</b>"
    lines = [header]
    if network:
        lines.append(f"🏢 <b>Студия / Платформа:</b> {network}")
    if air_date:
        lines.append(f"📅 <b>Дата премьеры:</b> <code>{format_date_ru(air_date)}</code>")
    if overview and len(overview.strip()) > 0:
        ov = overview.strip()
        if len(ov) > 240:
            ov = ov[:237] + "..."
        lines.append(f"\n📝 <i>«{ov}»</i>")
    lines.append("\n👉 <i>Хотите получать личные уведомления о премьере? Добавьте проект в Кинождун:</i>")
    return "\n\n".join(lines)


def channel_post_keyboard(
    post_id: int,
    bot_username: str,
    title: str,
    event_type: str = "announced",
    season_number: Optional[int] = None,
    trailer_url: Optional[str] = None,
    post_type: str = "news",
    site_url: Optional[str] = None,
) -> InlineKeyboardMarkup:
    """Создаёт контекстные кнопки для перехода из публикации канала обратно в бота."""
    clean_title = title if len(title) <= 20 else title[:17] + "..."
    deep_link = f"https://t.me/{bot_username}?start=ch_{post_id}"

    # Контекстный текст кнопки
    if event_type in ("renewed", "season_renewed"):
        btn_text = f"🔔 Ждать {season_number} сезон" if season_number else "🔔 Ждать продолжение"
    elif event_type in ("filming_started", "filming_finished"):
        btn_text = f"🎬 Ждать {season_number} сезон" if season_number else "🎬 Ждать премьеру"
    elif event_type == "trailer":
        btn_text = "🔔 Отслеживать премьеру"
    elif event_type in ("date_announced", "date_postponed", "announced"):
        btn_text = f"🔔 Отслеживать «{clean_title}»"
    elif post_type in ("daily_digest", "weekly_digest") or event_type in ("daily_digest", "weekly_digest"):
        btn_text = "🍿 Открыть Кинождуна"
    else:
        btn_text = f"🔔 Отслеживать «{clean_title}»"

    buttons: list[list[InlineKeyboardButton]] = []

    # Если есть официальная ссылка на трейлер, добавляем кнопку просмотра первой
    if trailer_url:
        buttons.append([InlineKeyboardButton(text="▶️ Смотреть трейлер", url=trailer_url)])

    if post_type in ("daily_digest", "weekly_digest") or event_type in ("daily_digest", "weekly_digest"):
        if site_url:
            buttons.append([InlineKeyboardButton(text="Все релизы на KinoЖдун ↗", url=site_url.rstrip('/') + '/calendar')])
        buttons.append([InlineKeyboardButton(text="🔔 Настроить напоминания", url=deep_link)])
    else:
        action_row = [InlineKeyboardButton(text=btn_text, url=deep_link)]
        if site_url:
            action_row.append(InlineKeyboardButton(text="🌐 На сайт", url=site_url))
        buttons.append(action_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


class ChannelPublisher:
    """Сервис публикации новостей в Telegram-канал «Кинождун 🍿»."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings,
        bot: Bot,
        tmdb_client: Optional[Any] = None,
    ):
        self.session_factory = session_factory
        self.settings = settings
        self.bot = bot
        self.tmdb_client = tmdb_client

    def is_significant_news(
        self,
        event_type: str,
        next_air_date: Optional[datetime.date] = None,
        status: Optional[str] = None,
        credibility: str = "confirmed",
        trailer_url: Optional[str] = None,
        items_count: int = 0,
    ) -> bool:
        """Критерии существенности и достоверности новости для публичного канала."""
        # 1. Достоверность: в канал допускаются только confirmed
        if credibility != "confirmed":
            return False

        # 2. Объявлена конкретная дата премьеры
        if event_type in ("announced", "date_announced") and next_air_date is not None:
            return True

        # 3. Перенос даты премьеры
        if event_type == "date_postponed" and next_air_date is not None:
            return True

        # 4. Официальное продление или анонс нового сезона / сиквела
        if event_type in ("renewed", "season_renewed", "season_announced", "sequel_announced"):
            return True

        # 5. Начало или завершение съёмок
        if event_type in ("filming_started", "filming_finished"):
            return True

        # 6. Официальный трейлер
        if event_type == "trailer" and trailer_url is not None:
            return True

        # 7. Состоялась премьера
        if event_type == "released":
            return True

        # 8. Официальное изменение статуса на продолжение или закрытие
        if event_type == "status_change" and status in ("Returning Series", "Ended", "Canceled"):
            return True

        if event_type in ("canceled", "ended"):
            return True

        # 9. Дайджесты
        if event_type == "daily_digest" and items_count >= 1:
            return True
        if event_type == "weekly_digest" and items_count >= 2:
            return True

        return False

    async def can_publish_now(self, repo: Repository) -> bool:
        """Проверка антиспам-интервала: не публиковать слишком часто."""
        last_post = await repo.get_last_published_channel_post()
        if not last_post or not last_post.published_at:
            return True

        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        elapsed_minutes = (now - last_post.published_at).total_seconds() / 60.0
        return elapsed_minutes >= self.settings.CHANNEL_MIN_POST_INTERVAL_MINUTES

    async def notify_admins_pending(self, post: ChannelPost) -> None:
        """Уведомляет администраторов о новом посте, ожидающем подтверждения в SAFE MODE."""
        if not self.settings.ADMIN_USER_IDS:
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"admin_pub:{post.id}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_rej:{post.id}"),
                ],
                [
                    InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"admin_edt:{post.id}"),
                ],
            ]
        )

        msg_text = (
            f"🔔 <b>Новая публикация ожидает модерации (#{post.id})</b>\n\n"
            f"🎬 <b>{linked_title(post.title, post)}</b>\n"
            f"🏷 <b>Событие:</b> <code>{post.event_type}</code>\n"
            f"🌐 <b>Источник:</b> {post.source} (статус: <i>{post.credibility}</i>)\n"
            "────────────────────────\n"
            f"{post.post_text or ''}"
        )

        for admin_id in self.settings.ADMIN_USER_IDS:
            try:
                await self.bot.send_message(chat_id=admin_id, text=msg_text, reply_markup=kb)
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление администратору {admin_id}: {e}")

    async def _send_post_to_telegram(
        self,
        chat_id: str | int,
        post_text: str,
        poster_path: Optional[str],
        reply_markup: InlineKeyboardMarkup,
    ) -> int:
        """Отправляет пост в Telegram с фото (если есть постер) или текстом."""
        if poster_path and telegram_text_length(post_text) <= 1024:
            photo_url = poster_path if poster_path.startswith("http") else f"{self.settings.TMDB_IMAGE_BASE_URL}{poster_path}"
            caption_text = post_text
            try:
                msg = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url,
                    caption=caption_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
                return msg.message_id
            except Exception as e:
                logger.warning(f"Не удалось отправить фото {photo_url}, fallback на текст: {e}")

        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=post_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return msg.message_id

    async def process_update_for_channel(
        self,
        tmdb_id: int,
        media_type: str,
        event_type: str,
        title: str,
        season_number: Optional[int] = None,
        air_date: Optional[datetime.date] = None,
        network: Optional[str] = None,
        poster_path: Optional[str] = None,
        overview: Optional[str] = None,
        old_air_date: Optional[datetime.date] = None,
        trailer_url: Optional[str] = None,
        source: str = "tmdb",
        credibility: str = "confirmed",
        post_type: str = "news",
    ) -> Optional[ChannelPost]:
        """Универсальная обработка события для публикации в Telegram-канал с дедупликацией."""
        # 1. Проверка существенности
        if not self.is_significant_news(
            event_type=event_type,
            next_air_date=air_date,
            credibility=credibility,
            trailer_url=trailer_url,
        ):
            logger.debug(f"Событие {title} ({event_type}) отфильтровано как несущественное или непроверенное.")
            return None

        # 2. Вычисление отпечатка дедупликации (Event Fingerprint)
        extra_key = None
        if event_type == "date_postponed":
            old_str = old_air_date.isoformat() if old_air_date else "nodate"
            new_str = air_date.isoformat() if air_date else "nodate"
            extra_key = f"{old_str}->{new_str}"
        elif event_type in ("announced", "date_announced"):
            extra_key = air_date.isoformat() if air_date else "nodate"
        elif event_type == "trailer" and trailer_url:
            extra_key = hashlib.md5(trailer_url.encode()).hexdigest()[:12]

        content_hash = generate_event_fingerprint(
            tmdb_id=tmdb_id,
            media_type=media_type,
            event_type=event_type,
            season_number=season_number,
            extra_key=extra_key,
        )

        async with self.session_factory() as session:
            repo = Repository(session)
            existing_post = await repo.get_channel_post_by_hash(content_hash)
            if existing_post:
                logger.info(f"Пост {title} ({event_type}) уже существует с хэшем {content_hash} (статус: {existing_post.status}). Дедуплицирован.")
                return existing_post

            # Формируем текст публикации
            post_text = format_channel_post_text(
                title=title,
                media_type=media_type,
                event_type=event_type,
                season_number=season_number,
                air_date=air_date,
                network=network,
                overview=overview,
                old_air_date=old_air_date,
                trailer_url=trailer_url,
            )

            channel_id = self.settings.TELEGRAM_CHANNEL_ID
            posting_enabled = self.settings.CHANNEL_POSTING_ENABLED

            # Если постинг в канал отключён или ID канала не задан -> сохраняем как pending
            if not channel_id or not posting_enabled:
                post = await repo.create_channel_post(
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    post_type=post_type,
                    event_type=event_type,
                    title=title,
                    content_hash=content_hash,
                    season_number=season_number,
                    air_date=air_date,
                    network=network,
                    poster_path=poster_path,
                    source=source,
                    credibility=credibility,
                    post_text=post_text,
                    trailer_url=trailer_url,
                    status="pending",
                )
                await session.commit()
                logger.info(f"Пост {title} сохранён со статусом pending (канал не подключён или посты выключены).")
                return post

            # SAFE MODE: если автопостинг отключён, сохраняем в pending и уведомляем админов
            if not self.settings.CHANNEL_AUTO_PUBLISH:
                post = await repo.create_channel_post(
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    post_type=post_type,
                    event_type=event_type,
                    title=title,
                    content_hash=content_hash,
                    season_number=season_number,
                    air_date=air_date,
                    network=network,
                    poster_path=poster_path,
                    source=source,
                    credibility=credibility,
                    post_text=post_text,
                    trailer_url=trailer_url,
                    status="pending",
                )
                await session.commit()
                logger.info(f"SAFE MODE: пост {title} помещён в очередь pending для модерации админом.")
                await self.notify_admins_pending(post)
                return post

            # AUTO MODE: проверка частоты публикаций (антиспам)
            can_post = await self.can_publish_now(repo)
            if not can_post:
                post = await repo.create_channel_post(
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    post_type=post_type,
                    event_type=event_type,
                    title=title,
                    content_hash=content_hash,
                    season_number=season_number,
                    air_date=air_date,
                    network=network,
                    poster_path=poster_path,
                    source=source,
                    credibility=credibility,
                    post_text=post_text,
                    trailer_url=trailer_url,
                    status="pending",
                )
                await session.commit()
                logger.info(f"AUTO MODE: пост {title} отложен в pending из-за минимального интервала публикаций.")
                return post

            # Создаём запись со статусом pending перед отправкой
            post = await repo.create_channel_post(
                tmdb_id=tmdb_id,
                media_type=media_type,
                post_type=post_type,
                event_type=event_type,
                title=title,
                content_hash=content_hash,
                season_number=season_number,
                air_date=air_date,
                network=network,
                poster_path=poster_path,
                source=source,
                credibility=credibility,
                post_text=post_text,
                trailer_url=trailer_url,
                status="pending",
            )
            await session.commit()

            await self.publish_post_by_id(post.id)
            await session.refresh(post)
            return post

    async def publish_post_by_id(self, post_id: int) -> bool:
        """Публикует конкретный пост из очереди (используется админ-панелью при подтверждении)."""
        if not self.settings.TELEGRAM_CHANNEL_ID:
            logger.error("TELEGRAM_CHANNEL_ID не задан!")
            return False

        async with self.session_factory() as session:
            repo = Repository(session)
            post = await repo.get_channel_post(post_id)
            if not post:
                return False
            if post.status == 'published':
                return True
            if not await repo.claim_channel_post(post_id):
                return False
            await session.commit()

            post_text = post.post_text or format_channel_post_text(
                title=post.title,
                media_type=post.media_type,
                event_type=post.event_type,
                season_number=post.season_number,
                air_date=post.air_date,
                network=post.network,
                trailer_url=post.trailer_url,
            )

            reply_markup = channel_post_keyboard(
                post_id=post.id,
                bot_username=self.settings.BOT_USERNAME,
                title=post.title,
                event_type=post.event_type,
                season_number=post.season_number,
                trailer_url=post.trailer_url,
                post_type=post.post_type,
                site_url=getattr(self.settings, "SITE_BASE_URL", None),
            )

            try:
                message_id = await self._send_post_to_telegram(
                    chat_id=self.settings.TELEGRAM_CHANNEL_ID,
                    post_text=post_text,
                    poster_path=post.poster_path,
                    reply_markup=reply_markup,
                )
                await repo.mark_channel_post_published(post.id, message_id)
                await session.commit()
                logger.info(f"Админ одобрил и опубликовал пост «{post.title}» (#{post.id}) в канал.")
                return True
            except Exception as e:
                # Transport failures may occur after delivery; do not auto-retry.
                await session.rollback()
                await repo.update_channel_post_status(post_id, 'failed')
                await session.commit()
                logger.error(f"Ошибка публикации одобренного поста #{post_id}: {e}", exc_info=True)
                return False

    async def publish_pending_queue(self) -> int:
        """Периодическая досылка отложенных постов с соблюдением интервала антиспама."""
        if not self.settings.TELEGRAM_CHANNEL_ID or not self.settings.CHANNEL_POSTING_ENABLED:
            return 0

        # В SAFE MODE без подтверждения админа не отправляем автоматически!
        if not self.settings.CHANNEL_AUTO_PUBLISH:
            return 0

        published_count = 0
        async with self.session_factory() as session:
            repo = Repository(session)
            can_post = await self.can_publish_now(repo)
            if not can_post:
                return 0

            pending_posts = await repo.get_pending_channel_posts()
            if not pending_posts:
                return 0

            # Одиночные новости из прежнего трекера остаются для ручной модерации.
            # Автоматический поток канала состоит только из общих подборок.
            post = next(
                (p for p in pending_posts if p.post_type in ("daily_digest", "weekly_digest")),
                None,
            )
            if post is None:
                return 0
            success = await self.publish_post_by_id(post.id)
            if success:
                published_count += 1

        return published_count

    async def enrich_digest_items(self, items, start, end, require_details=False):
        enriched = []
        seen = set()
        for source in items:
            item = dict(source)
            media, ident = item["media_type"], item["tmdb_id"]
            if (media, ident) in seen:
                continue
            seen.add((media, ident))
            details = {}
            if self.tmdb_client:
                details = (await self.tmdb_client.get_tv_details(ident) if media == "tv"
                           else await self.tmdb_client.get_movie_details(ident))
            if not details and (require_details or self.tmdb_client):
                continue
            if details:
                audience = {**details, **audience_metadata(media, details),
                            'key': f'{media}:{ident}', 'media_type': media}
                policy = dict(asian_min_votes=self.settings.SITE_ASIAN_MIN_VOTES,
                              asian_min_popularity=self.settings.SITE_ASIAN_MIN_POPULARITY,
                              audience_allow_keys=self.settings.SITE_AUDIENCE_ALLOW_KEYS)
                if exclusion_reason(audience, policy):
                    continue
                if media == "tv" and (details.get("type") in ("Reality", "Talk Show", "News", "Video")
                        or any(g.get("id") in EXCLUDED_GENRES for g in details.get("genres", []))):
                    continue
                votes = int(details.get("vote_count") or 0)
                rating = float(details.get("vote_average") or 0)
                if votes >= 10 and rating < 6:
                    continue
                item.update({k: details.get(k) for k in ("network", "backdrop_path", "vote_average", "vote_count")})
                name = (details.get("name") if media == "tv" else details.get("title")) or details.get("title") or item.get("title")
                orig = (details.get("original_name") if media == "tv" else details.get("original_title")) or details.get("original_title") or item.get("original_title")
                if name and not re.search(r"[а-яА-ЯёЁa-zA-Z]", name):
                    name = orig
                if not name or not re.search(r"[а-яА-ЯёЁa-zA-Z]", name):
                    continue
                item["title"] = name
                if media == "tv":
                    # Local tracked series represent season premieres; discovery
                    # candidates must have an episode confirmed for the actual day.
                    if start == end:
                        episodes = await episodes_on_date(self.tmdb_client, ident, details, start)
                        if not episodes:
                            continue
                        season = episodes[0]["season_number"]
                        numbers = [ep["episode_number"] for ep in episodes]
                        item["tag"] = ("новый сериал" if season == 1 else f"старт {season} сезона") if numbers == [1] else f"{season} сезон · " + ", ".join(map(str, numbers)) + (" серия" if len(numbers) == 1 else " серии")
                    else:
                        premieres = [(n, d) for n, d in season_premieres(details) if start <= d <= end]
                        if not premieres:
                            continue
                        season, released = premieres[0]
                        item["tag"] = "новый сериал" if season == 1 else f"старт {season} сезона"
                        item["date_str"] = format_date_ru(released)
                else:
                    try:
                        released = datetime.date.fromisoformat(details.get("release_date"))
                    except (ValueError, TypeError):
                        continue
                    if not start <= released <= end:
                        continue
                    item["date_str"] = format_date_ru(released)
            enriched.append(item)
            if len(enriched) >= 5:
                break
        return enriched

    async def create_daily_digest(self, target_date: Optional[datetime.date] = None) -> Optional[ChannelPost]:
        """Формирует и публикует/ставит в очередь утренний дайджест «Что выходит сегодня»."""
        target_date = target_date or datetime.date.today()

        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_items_releasing_on_date(target_date)

            # Приоритет: премьеры фильмов, новые сериалы, старты сезонов
            items_payload = []
            seen_ids = set()
            for it in items[:6]:
                tag = "премьера"
                if it.media_type == "tv":
                    if it.next_season_number and it.next_season_number > 1:
                        tag = f"старт {it.next_season_number} сезона"
                    else:
                        tag = "новый сериал"
                else:
                    tag = "премьера фильма"

                items_payload.append({
                    "title": it.title,
                    "media_type": it.media_type,
                    "tmdb_id": it.tmdb_id,
                    "tag": tag,
                    "network": it.network,
                    "poster_path": it.poster_path,
                })
                seen_ids.add((it.media_type, it.tmdb_id))

            items_payload = await self.enrich_digest_items(items_payload, target_date, target_date)
            seen_ids = {(i["media_type"], i["tmdb_id"]) for i in items_payload}
            if len(items_payload) < 3 and self.tmdb_client:
                try:
                    airing = await self.tmdb_client.get_airing_today_tv()
                    airing.sort(key=lambda x: (x.get("vote_count", 0) * 2 + x.get("popularity", 0)), reverse=True)
                    for tv in airing:
                        if len(items_payload) >= 5:
                            break
                        ident = tv.get("id")
                        if not ident or ("tv", ident) in seen_ids:
                            continue
                        name = tv.get("name") or ""
                        if not re.search(r"[а-яА-ЯёЁa-zA-Z]", name):
                            continue
                        if any(bad in name.lower() for bad in ("мифическим утром", "good mythical morning", "daily show", "jimmy fallon", "jimmy kimmel")):
                            continue
                        if any(g in EXCLUDED_GENRES for g in tv.get("genre_ids", [])):
                            continue
                        if tv.get("vote_count", 0) < 5 and tv.get("popularity", 0) < 15:
                            continue
                        candidate = {"title": tv.get("name"), "media_type": "tv", "tmdb_id": ident}
                        enriched = await self.enrich_digest_items([candidate], target_date, target_date, require_details=True)
                        items_payload.extend(enriched)
                        if enriched:
                            seen_ids.add(("tv", ident))
                except Exception:
                    logger.warning("Не удалось дополнить дневную подборку из TMDB.")

            if not items_payload:
                logger.info(f"На дату {target_date} нет запланированных релизов. Пропуск дайджеста.")
                return None

            date_label = format_date_ru(target_date)
            items_digest = hashlib.md5("".join(f"{it['media_type']}:{it['tmdb_id']}" for it in items_payload).encode()).hexdigest()[:8]
            fingerprint = generate_event_fingerprint(
                tmdb_id=None,
                media_type=None,
                event_type="daily_digest",
                extra_key=f"{target_date.isoformat()}:{items_digest}",
            )

            existing = await repo.get_channel_post_by_hash(fingerprint)
            if existing:
                return existing

            post_text = format_channel_post_text(
                title=f"Что выходит сегодня — {date_label}",
                event_type="daily_digest",
                items=items_payload,
                date_label=date_label,
                site_url=self.settings.SITE_BASE_URL,
            )

            lead_poster = next((it.get("backdrop_path") for it in items_payload if it.get("backdrop_path")), None)

            post = await repo.create_channel_post(
                title=f"Что выходит сегодня — {date_label}",
                content_hash=fingerprint,
                post_type="daily_digest",
                event_type="daily_digest",
                source="tmdb",
                credibility="confirmed",
                post_text=post_text,
                payload=json.dumps(items_payload, ensure_ascii=False),
                status="pending",
                poster_path=lead_poster,
            )
            await session.commit()

            # Если включен AUTO MODE и канал настроен -> публикуем
            if self.settings.CHANNEL_AUTO_PUBLISH and self.settings.TELEGRAM_CHANNEL_ID and self.settings.CHANNEL_POSTING_ENABLED:
                if await self.can_publish_now(repo):
                    await self.publish_post_by_id(post.id)
            elif not self.settings.CHANNEL_AUTO_PUBLISH:
                await self.notify_admins_pending(post)

            return post

    async def create_weekly_digest(self, start_date: Optional[datetime.date] = None) -> Optional[ChannelPost]:
        """Формирует и публикует/ставит в очередь понедельничный дайджест «Главные премьеры недели»."""
        start_date = start_date or datetime.date.today()
        end_date = start_date + datetime.timedelta(days=6)

        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_items_releasing_between(start_date, end_date)

            items_payload = []
            seen_ids = set()
            for it in items[:8]:
                tag = "премьера фильма" if it.media_type == "movie" else f"старт {it.next_season_number} сезона" if (it.next_season_number and it.next_season_number > 1) else "новый сериал"
                r_date = it.next_air_date or it.custom_date
                items_payload.append({
                    "title": it.title,
                    "media_type": it.media_type,
                    "tmdb_id": it.tmdb_id,
                    "date_str": format_date_ru(r_date),
                    "tag": tag,
                    "network": it.network,
                    "poster_path": it.poster_path,
                })
                seen_ids.add((it.media_type, it.tmdb_id))

            items_payload = await self.enrich_digest_items(items_payload, start_date, end_date)
            seen_ids = {(i["media_type"], i["tmdb_id"]) for i in items_payload}
            if len(items_payload) < 2 and self.tmdb_client:
                try:
                    upcoming = await self.tmdb_client.get_upcoming_movies()
                    upcoming.sort(key=lambda x: x.get("popularity", 0), reverse=True)
                    for movie in upcoming:
                        if len(items_payload) >= 5:
                            break
                        ident = movie.get("id")
                        if not ident or ("movie", ident) in seen_ids:
                            continue
                        try:
                            released = datetime.date.fromisoformat(movie.get("release_date"))
                        except (ValueError, TypeError):
                            continue
                        if not start_date <= released <= end_date:
                            continue
                        candidate = {"title": movie.get("title"), "media_type": "movie", "tmdb_id": ident,
                                     "date_str": format_date_ru(released), "tag": "премьера фильма"}
                        enriched = await self.enrich_digest_items([candidate], start_date, end_date, require_details=True)
                        items_payload.extend(enriched)
                        if enriched:
                            seen_ids.add(("movie", ident))
                except Exception:
                    logger.warning("Не удалось дополнить недельную подборку из TMDB.")

            # Если релизов все еще меньше 2, пропускаем
            if len(items_payload) < 2:
                logger.info(f"На неделю {start_date}..{end_date} менее 2 релизов. Пропуск еженедельного дайджеста.")
                return None

            range_label = f"{format_date_ru(start_date)} – {format_date_ru(end_date)}"
            items_digest = hashlib.md5("".join(f"{it['media_type']}:{it['tmdb_id']}" for it in items_payload).encode()).hexdigest()[:8]
            fingerprint = generate_event_fingerprint(
                tmdb_id=None,
                media_type=None,
                event_type="weekly_digest",
                extra_key=f"{start_date.isoformat()}:{items_digest}",
            )

            existing = await repo.get_channel_post_by_hash(fingerprint)
            if existing:
                return existing

            post_text = format_channel_post_text(
                title=f"Главные премьеры недели ({range_label})",
                event_type="weekly_digest",
                items=items_payload,
                date_label=range_label,
                site_url=self.settings.SITE_BASE_URL,
            )

            lead_poster = next((it.get("backdrop_path") for it in items_payload if it.get("backdrop_path")), None)

            post = await repo.create_channel_post(
                title=f"Главные премьеры недели ({range_label})",
                content_hash=fingerprint,
                post_type="weekly_digest",
                event_type="weekly_digest",
                source="tmdb",
                credibility="confirmed",
                post_text=post_text,
                payload=json.dumps(items_payload, ensure_ascii=False),
                status="pending",
                poster_path=lead_poster,
            )
            await session.commit()

            if self.settings.CHANNEL_AUTO_PUBLISH and self.settings.TELEGRAM_CHANNEL_ID and self.settings.CHANNEL_POSTING_ENABLED:
                if await self.can_publish_now(repo):
                    await self.publish_post_by_id(post.id)
            elif not self.settings.CHANNEL_AUTO_PUBLISH:
                await self.notify_admins_pending(post)

            return post

    async def publish_test_post(self) -> dict[str, Any]:
        """Отправляет тестовую публикацию в Telegram-канал для проверки настроек и прав администратора."""
        channel_id = self.settings.TELEGRAM_CHANNEL_ID
        if not channel_id:
            return {"success": False, "error": "TELEGRAM_CHANNEL_ID не задан в .env файле."}

        test_text = (
            "🍿 <b>Тестовое подключение канала «Кинождун»</b>\n"
            "────────────────────────\n"
            "Бот успешно подключён к каналу и имеет права на публикацию сообщений! 🎉\n\n"
            "Здесь будут появляться подборки и дайджесты премьер. Личные уведомления по отслеживаемым фильмам и сериалам приходят в бота."
        )

        try:
            bot_info = await self.bot.get_me()
            username = bot_info.username or "kinojdun_bot"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🍿 Открыть Кинождуна",
                            url=f"https://t.me/{username}?start=channel_test",
                        ),
                        InlineKeyboardButton(
                            text="🌐 На сайт",
                            url=getattr(self.settings, "SITE_BASE_URL", "https://kinojdun.ru"),
                        ),
                    ]
                ]
            )
            msg = await self.bot.send_message(chat_id=channel_id, text=test_text, reply_markup=kb)
            return {"success": True, "message_id": msg.message_id, "channel": channel_id}
        except Exception as e:
            logger.error(f"Ошибка тестовой публикации в канал {channel_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "channel": channel_id}
