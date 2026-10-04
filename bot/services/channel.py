"""Сервис автоматической публикации значимых новостей в Telegram-канал «Кинождун»."""

import datetime
import hashlib
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


def generate_content_hash(
    tmdb_id: int,
    media_type: str,
    event_type: str,
    season_number: Optional[int] = None,
    air_date: Optional[datetime.date] = None,
) -> str:
    """Генерирует стабильный хэш для дедупликации публикаций в канале."""
    date_str = air_date.isoformat() if air_date else "nodate"
    season_str = str(season_number) if season_number is not None else "noseason"
    raw = f"{tmdb_id}:{media_type}:{event_type}:{season_str}:{date_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def format_channel_post_text(
    title: str,
    media_type: str,
    event_type: str,
    season_number: Optional[int] = None,
    air_date: Optional[datetime.date] = None,
    network: Optional[str] = None,
    overview: Optional[str] = None,
) -> str:
    """Форматирует красивый и вовлекающий пост для Telegram-канала."""
    type_label = "сериала" if media_type == "tv" else "фильма"
    season_label = f" (сезон {season_number})" if (media_type == "tv" and season_number) else ""

    if event_type == "announced":
        header = f"🔥 <b>Официально объявлена дата выхода {type_label} «{title}»{season_label}!</b>"
    elif event_type == "released":
        header = f"🍿 <b>Сегодня состоялась премьера {type_label} «{title}»{season_label}!</b>"
    elif event_type == "status_change":
        header = f"📢 <b>Важные новости о статусе {type_label} «{title}»!</b>"
    elif event_type == "season_announced":
        header = f"🆕 <b>Анонсирован новый сезон сериала «{title}»!</b>"
    else:
        header = f"🎬 <b>Новости о проекте «{title}»{season_label}</b>"

    lines = [
        header,
        "────────────────────────",
    ]

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


def channel_post_keyboard(post_id: int, bot_username: str, title: str) -> InlineKeyboardMarkup:
    """Создаёт инлайн-кнопку для перехода из публикации канала обратно в бота."""
    clean_title = title if len(title) <= 24 else title[:21] + "..."
    deep_link = f"https://t.me/{bot_username}?start=ch_{post_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔔 Отслеживать «{clean_title}»",
                    url=deep_link,
                )
            ]
        ]
    )


class ChannelPublisher:
    """Сервис публикации новостей в Telegram-канал с дедупликацией и защитой от спама."""

    def __init__(self, session_factory: async_sessionmaker, settings: Settings, bot: Bot):
        self.session_factory = session_factory
        self.settings = settings
        self.bot = bot

    def is_significant_news(self, event_type: str, next_air_date: Optional[datetime.date], status: Optional[str] = None) -> bool:
        """Критерии существенности новости (исключение информационного шума)."""
        # 1. Объявлена конкретная дата премьеры
        if event_type == "announced" and next_air_date is not None:
            return True
        # 2. Состоялась премьера долгожданного тайтла
        if event_type == "released":
            return True
        # 3. Официальное изменение статуса на продолжение или отмену
        if event_type == "status_change" and status in ("Returning Series", "Ended", "Canceled", "Planned"):
            return True
        # 4. Анонс нового сезона
        if event_type == "season_announced":
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
    ) -> Optional[ChannelPost]:
        """Обрабатывает потенциальную новость для публикации в Telegram-канал."""
        # 1. Фильтр существенности
        if not self.is_significant_news(event_type, air_date):
            logger.debug(f"Новость для {title} ({event_type}) признана несущественной для канала.")
            return None

        # 2. Проверка дедупликации по хэшу
        content_hash = generate_content_hash(
            tmdb_id=tmdb_id,
            media_type=media_type,
            event_type=event_type,
            season_number=season_number,
            air_date=air_date,
        )

        async with self.session_factory() as session:
            repo = Repository(session)
            existing_post = await repo.get_channel_post_by_hash(content_hash)
            if existing_post:
                logger.info(f"Пост для {title} с хэшем {content_hash} уже существует (статус: {existing_post.status}). Пропуск.")
                return existing_post

            # 3. Проверка канала и настроек
            channel_id = self.settings.TELEGRAM_CHANNEL_ID
            posting_enabled = self.settings.CHANNEL_POSTING_ENABLED

            # Если канал не настроен или постинг выключен, сохраняем в очередь как pending
            if not channel_id or not posting_enabled:
                post = await repo.create_channel_post(
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    event_type=event_type,
                    title=title,
                    content_hash=content_hash,
                    season_number=season_number,
                    air_date=air_date,
                    network=network,
                    poster_path=poster_path,
                    status="pending",
                )
                await session.commit()
                logger.info(f"Пост {title} сохранён со статусом pending (канал не подключён или автопостинг отключён).")
                return post

            # 4. Проверка частоты публикаций (антиспам)
            can_post = await self.can_publish_now(repo)
            if not can_post and not self.settings.CHANNEL_AUTO_PUBLISH:
                post = await repo.create_channel_post(
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    event_type=event_type,
                    title=title,
                    content_hash=content_hash,
                    season_number=season_number,
                    air_date=air_date,
                    network=network,
                    poster_path=poster_path,
                    status="pending",
                )
                await session.commit()
                logger.info(f"Пост {title} отложен в очередь pending из-за лимита частоты публикаций.")
                return post

            # 5. Создаём запись со статусом pending перед фактической отправкой
            post = await repo.create_channel_post(
                tmdb_id=tmdb_id,
                media_type=media_type,
                event_type=event_type,
                title=title,
                content_hash=content_hash,
                season_number=season_number,
                air_date=air_date,
                network=network,
                poster_path=poster_path,
                status="pending",
            )
            await session.commit()

            # 6. Отправка в Telegram-канал
            post_text = format_channel_post_text(
                title=title,
                media_type=media_type,
                event_type=event_type,
                season_number=season_number,
                air_date=air_date,
                network=network,
                overview=overview,
            )
            reply_markup = channel_post_keyboard(post.id, self.settings.BOT_USERNAME, title)

            message_id = None
            try:
                if poster_path:
                    photo_url = f"{self.settings.TMDB_IMAGE_BASE_URL}{poster_path}"
                    msg = await self.bot.send_photo(
                        chat_id=channel_id,
                        photo=photo_url,
                        caption=post_text,
                        reply_markup=reply_markup,
                    )
                    message_id = msg.message_id
                else:
                    msg = await self.bot.send_message(
                        chat_id=channel_id,
                        text=post_text,
                        reply_markup=reply_markup,
                    )
                    message_id = msg.message_id

                await repo.mark_channel_post_published(post.id, message_id)
                await session.commit()
                logger.info(f"Успешно опубликован пост в канал {channel_id}: {title} (post_id: {post.id})")
            except Exception as send_err:
                logger.error(f"Не удалось отправить пост в канал {channel_id}: {send_err}", exc_info=True)
                # Пост остаётся в статусе pending для повторной отправки

            return post

    async def publish_pending_queue(self) -> int:
        """Публикует посты из очереди pending с соблюдением интервалов."""
        if not self.settings.TELEGRAM_CHANNEL_ID or not self.settings.CHANNEL_POSTING_ENABLED:
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

            # Берём первый пост из очереди
            post = pending_posts[0]
            post_text = format_channel_post_text(
                title=post.title,
                media_type=post.media_type,
                event_type=post.event_type,
                season_number=post.season_number,
                air_date=post.air_date,
                network=post.network,
            )
            reply_markup = channel_post_keyboard(post.id, self.settings.BOT_USERNAME, post.title)

            try:
                if post.poster_path:
                    photo_url = f"{self.settings.TMDB_IMAGE_BASE_URL}{post.poster_path}"
                    msg = await self.bot.send_photo(
                        chat_id=self.settings.TELEGRAM_CHANNEL_ID,
                        photo=photo_url,
                        caption=post_text,
                        reply_markup=reply_markup,
                    )
                    message_id = msg.message_id
                else:
                    msg = await self.bot.send_message(
                        chat_id=self.settings.TELEGRAM_CHANNEL_ID,
                        text=post_text,
                        reply_markup=reply_markup,
                    )
                    message_id = msg.message_id

                await repo.mark_channel_post_published(post.id, message_id)
                await session.commit()
                published_count += 1
                logger.info(f"Опубликован отложенный пост {post.title} (ID: {post.id})")
            except Exception as e:
                logger.error(f"Ошибка публикации отложенного поста {post.id}: {e}", exc_info=True)

        return published_count
