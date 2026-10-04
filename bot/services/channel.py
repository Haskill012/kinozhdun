"""Сервис автоматической публикации значимых новостей в Telegram-канал «Кинождун 🍿»."""

import datetime
import hashlib
import json
import logging
from typing import Any, Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import Settings
from bot.db.models import ChannelPost
from bot.db.repositories import Repository
from bot.utils.formatting import format_date_ru

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
) -> str:
    """Форматирует красивый, лаконичный и вовлекающий пост для Telegram-канала в стиле Кинождуна."""
    type_label = "сериала" if media_type == "tv" else "фильма"
    type_word = "сериал" if media_type == "tv" else "фильм"
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

        date_line = f"\n📅 Премьера ожидается: <b>{format_date_ru(air_date)}</b>" if air_date else "\nТочная дата выхода пока не объявлена."
        cta_line = "\n🍿 Кинождун сообщит, когда появятся новости о съёмках и дате премьеры."
        return "\n\n".join([header, studio_str + date_line, cta_line])

    # --- 2. Объявление даты выхода ---
    elif event_type in ("date_announced", "announced"):
        if air_date:
            date_formatted = format_date_ru(air_date)
            header = f"📅 <b>Объявлена дата выхода {season_label or type_label} «{title}»</b>"
            info_line = f"Премьера состоится <b>{date_formatted}</b>."
            if network:
                info_line += f"\n🏢 <b>Платформа:</b> {network}"
            cta_line = f"🍿 Добавь {type_word} в Кинождун — напомним о премьере."
            return "\n\n".join([header, info_line, cta_line])
        else:
            header = f"📢 <b>Новости о проекте «{title}»{season_label}</b>"
            cta_line = "🍿 Следите за обновлениями в Кинождуне."
            return f"{header}\n\n{cta_line}"

    # --- 3. Перенос даты выхода ---
    elif event_type == "date_postponed":
        new_date_str = format_date_ru(air_date) if air_date else "не объявлена"
        old_date_str = format_date_ru(old_air_date) if old_air_date else "ранее"
        header = f"📅 <b>Премьеру «{title}»{season_label} перенесли</b>"
        body = f"Новая дата выхода — <b>{new_date_str}</b>.\nРанее премьера ожидалась <i>{old_date_str}</i>."
        cta = "🍿 Добавь проект в Кинождун — сообщим обо всех дальнейших изменениях."
        return f"{header}\n\n{body}\n\n{cta}"

    # --- 4. Начало съёмок ---
    elif event_type == "filming_started":
        target = f"{season_word}а сериала" if media_type == "tv" else "фильма"
        header = f"🎬 <b>Начались съёмки {target} «{title}»</b>"
        body = "Производство официально стартовало."
        date_line = f"\n📅 Релиз запланирован на: <b>{format_date_ru(air_date)}</b>" if air_date else "\nДата премьеры пока не объявлена."
        cta = "🍿 Кинождун сообщит, когда объявят точную дату премьеры."
        return f"{header}\n\n{body}{date_line}\n\n{cta}"

    # --- 5. Завершение съёмок ---
    elif event_type == "filming_finished":
        target = f"{season_word}а сериала" if media_type == "tv" else "фильма"
        header = f"🎬 <b>Завершились съёмки {target} «{title}»</b>"
        body = "Съёмочный процесс завершён, проект переходит на стадию пост-продакшна."
        date_line = f"\n📅 Премьера: <b>{format_date_ru(air_date)}</b>" if air_date else "\nДата премьеры пока не объявлена."
        cta = "🍿 Кинождун сообщит о премьере и первом официальном трейлере."
        return f"{header}\n\n{body}{date_line}\n\n{cta}"

    # --- 6. Официальный трейлер ---
    elif event_type == "trailer":
        target = f"нового сезона «{title}»" if (media_type == "tv" and season_number) else f"фильма «{title}»"
        header = f"🔥 <b>Вышел официальный трейлер {target}</b>"
        date_info = f"Премьера состоится <b>{format_date_ru(air_date)}</b>." if air_date else "Дата премьеры пока не объявлена."
        if network:
            date_info += f"\n🏢 <b>Платформа:</b> {network}"
        cta = "🍿 Кинождун напомнит о премьере за 3 дня и в день выхода."
        return f"{header}\n\n{date_info}\n\n{cta}"

    # --- 7. Премьера состоялась ---
    elif event_type == "released":
        header = f"🍿 <b>Сегодня состоялась премьера {type_label} «{title}»{season_label}!</b>"
        body = "Релиз уже доступен для просмотра."
        if network:
            body += f"\n🏢 <b>Платформа:</b> {network}"
        cta = "🎬 Добавьте проект в личный список, чтобы не потерять."
        return f"{header}\n\n{body}\n\n{cta}"

    # --- 8. Закрытие / завершение ---
    elif event_type in ("canceled", "ended"):
        status_label = "официально закрыт" if event_type == "canceled" else "завершён"
        header = f"📢 <b>Сериал «{title}» {status_label}</b>"
        body = f"{network} принял решение не продолжать проект." if network else "Производство сериала завершено, новых сезонов не планируется."
        cta = "🍿 В Кинождуне всегда можно найти другие интересные премьеры."
        return f"{header}\n\n{body}\n\n{cta}"

    # --- 9. «Что выходит сегодня» (Daily Digest) ---
    elif event_type == "daily_digest":
        date_str = date_label or format_date_ru(datetime.date.today())
        lines = [
            f"🍿 <b>Что выходит сегодня — {date_str}</b>",
            "────────────────────────",
        ]
        if items:
            for item in items:
                m_type = item.get("media_type", "movie")
                t_name = item.get("title", "Без названия")
                tag = item.get("tag", "премьера")
                icon = "🎬" if m_type == "movie" else "🔥"
                lines.append(f"{icon} <b>{t_name}</b> — {tag}")
        lines.append("────────────────────────")
        lines.append("🍿 <i>Не хотите пропускать важные даты? Добавьте проекты в Кинождун — бот вовремя пришлёт напоминание.</i>")
        return "\n".join(lines)

    # --- 10. «Главные премьеры недели» (Weekly Digest) ---
    elif event_type == "weekly_digest":
        lines = [
            f"🔥 <b>Главные премьеры недели ({date_label or ''})</b>",
            "────────────────────────",
        ]
        if items:
            for item in items:
                m_type = item.get("media_type", "movie")
                t_name = item.get("title", "Без названия")
                d_str = item.get("date_str", "")
                tag = item.get("tag", "")
                icon = "🎬" if m_type == "movie" else "🍿"
                tag_part = f" ({tag})" if tag else ""
                lines.append(f"{icon} {d_str} — <b>{t_name}</b>{tag_part}")
        lines.append("────────────────────────")
        lines.append("<b>Не хочешь следить за датами самостоятельно?</b>")
        lines.append("Добавь интересующие фильмы и сериалы в Кинождун — бот сообщит о важных изменениях.")
        return "\n".join(lines)

    # --- Дефолтный формат новостного поста ---
    header = f"🎬 <b>Новости о проекте «{title}»{season_label}</b>"
    lines = [header, "────────────────────────"]
    if network:
        lines.append(f"🏢 <b>Платформа / Студия:</b> {network}")
    if air_date:
        lines.append(f"📅 <b>Дата премьеры:</b> <code>{format_date_ru(air_date)}</code>")
    if overview and len(overview.strip()) > 0:
        ov = overview.strip()
        if len(ov) > 240:
            ov = ov[:237] + "..."
        lines.append(f"\n📝 <i>«{ov}»</i>")
    lines.append("\n👉 <i>Хотите получать личные уведомления о датах выхода и трейлерах? Добавьте проект в Кинождун:</i>")
    return "\n".join(lines)


def channel_post_keyboard(
    post_id: int,
    bot_username: str,
    title: str,
    event_type: str = "announced",
    season_number: Optional[int] = None,
    trailer_url: Optional[str] = None,
    post_type: str = "news",
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

    buttons.append([InlineKeyboardButton(text=btn_text, url=deep_link)])
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
            f"🎬 <b>{post.title}</b>\n"
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
        if poster_path:
            photo_url = poster_path if poster_path.startswith("http") else f"{self.settings.TMDB_IMAGE_BASE_URL}{poster_path}"
            msg = await self.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=post_text,
                reply_markup=reply_markup,
            )
            return msg.message_id
        else:
            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=post_text,
                reply_markup=reply_markup,
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

            # Отправка в канал
            reply_markup = channel_post_keyboard(
                post_id=post.id,
                bot_username=self.settings.BOT_USERNAME,
                title=title,
                event_type=event_type,
                season_number=season_number,
                trailer_url=trailer_url,
                post_type=post_type,
            )

            try:
                message_id = await self._send_post_to_telegram(
                    chat_id=channel_id,
                    post_text=post_text,
                    poster_path=poster_path,
                    reply_markup=reply_markup,
                )
                await repo.mark_channel_post_published(post.id, message_id)
                await session.commit()
                logger.info(f"AUTO MODE: Успешно опубликован пост в {channel_id}: «{title}» (ID: {post.id})")
            except Exception as e:
                logger.error(f"Не удалось отправить пост в канал {channel_id}: {e}", exc_info=True)

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

            post = pending_posts[0]
            success = await self.publish_post_by_id(post.id)
            if success:
                published_count += 1

        return published_count

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
                })
                seen_ids.add((it.media_type, it.tmdb_id))

            # Если релизов в локальной БД мало, дополняем из TMDB (airing_today)
            if len(items_payload) < 3 and self.tmdb_client:
                try:
                    airing = await self.tmdb_client.get_airing_today_tv()
                    for tv in airing:
                        tv_id = tv.get("id")
                        tv_name = tv.get("name")
                        if ("tv", tv_id) not in seen_ids and tv_name:
                            items_payload.append({
                                "title": tv_name,
                                "media_type": "tv",
                                "tmdb_id": tv_id,
                                "tag": "сериал",
                            })
                            seen_ids.add(("tv", tv_id))
                            if len(items_payload) >= 5:
                                break
                except Exception as e:
                    logger.warning(f"Ошибка получения airing today tv из TMDB: {e}")

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
            )

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
                })
                seen_ids.add((it.media_type, it.tmdb_id))

            # Если релизов в локальной БД мало, дополняем ожидаемыми фильмами из TMDB
            if len(items_payload) < 2 and self.tmdb_client:
                try:
                    upcoming = await self.tmdb_client.get_upcoming_movies()
                    for m in upcoming:
                        m_id = m.get("id")
                        r_date_str = m.get("release_date")
                        m_title = m.get("title")
                        if ("movie", m_id) not in seen_ids and m_title and r_date_str:
                            try:
                                r_date = datetime.date.fromisoformat(r_date_str)
                                formatted_r_date = format_date_ru(r_date)
                            except Exception:
                                formatted_r_date = r_date_str
                            items_payload.append({
                                "title": m_title,
                                "media_type": "movie",
                                "tmdb_id": m_id,
                                "date_str": formatted_r_date,
                                "tag": "премьера фильма",
                            })
                            seen_ids.add(("movie", m_id))
                            if len(items_payload) >= 6:
                                break
                except Exception as e:
                    logger.warning(f"Ошибка получения upcoming movies из TMDB: {e}")

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
            )

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
            "Теперь здесь будут появляться проверенные новости о датах премьер, продолжениях и официальные трейлеры."
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
                        )
                    ]
                ]
            )
            msg = await self.bot.send_message(chat_id=channel_id, text=test_text, reply_markup=kb)
            return {"success": True, "message_id": msg.message_id, "channel": channel_id}
        except Exception as e:
            logger.error(f"Ошибка тестовой публикации в канал {channel_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "channel": channel_id}
