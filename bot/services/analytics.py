"""Сервис аналитики событий органического роста и переходов."""

import logging
from typing import Any, Optional
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.db.repositories import Repository

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Сервис для логирования и отслеживания ключевых воронок роста."""

    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory

    async def log_event(
        self,
        event_name: str,
        telegram_id: Optional[int] = None,
        source: Optional[str] = None,
        reference_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """Безопасное логирование аналитического события."""
        try:
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.log_analytics_event(
                    event_name=event_name,
                    telegram_id=telegram_id,
                    source=source,
                    reference_id=reference_id,
                    payload=payload,
                )
                await session.commit()
                logger.info(f"Analytics event logged: {event_name} (user: {telegram_id}, ref: {reference_id})")
        except Exception as e:
            logger.error(f"Не удалось залогировать аналитическое событие {event_name}: {e}", exc_info=True)

    # 1. Виральный шеринг контента
    async def log_content_shared(self, telegram_id: int, media_type: str, tmdb_id: int, title: str) -> None:
        await self.log_event(
            event_name="content_shared",
            telegram_id=telegram_id,
            source="share_content",
            reference_id=f"{media_type}:{tmdb_id}",
            payload={"title": title, "media_type": media_type, "tmdb_id": tmdb_id},
        )

    async def log_share_link_opened(self, telegram_id: int, media_type: str, tmdb_id: int, referrer_id: Optional[int] = None) -> None:
        await self.log_event(
            event_name="share_link_opened",
            telegram_id=telegram_id,
            source="share_content",
            reference_id=f"{media_type}:{tmdb_id}",
            payload={"referrer_id": referrer_id, "media_type": media_type, "tmdb_id": tmdb_id},
        )

    async def log_content_followed_from_share(self, telegram_id: int, media_type: str, tmdb_id: int, referrer_id: Optional[int] = None) -> None:
        await self.log_event(
            event_name="content_followed_from_share",
            telegram_id=telegram_id,
            source="share_content",
            reference_id=f"{media_type}:{tmdb_id}",
            payload={"referrer_id": referrer_id, "media_type": media_type, "tmdb_id": tmdb_id},
        )

    # 2. Мой Кинождун (Shared Watchlist)
    async def log_watchlist_shared(self, telegram_id: int, token: str, items_count: int) -> None:
        await self.log_event(
            event_name="watchlist_shared",
            telegram_id=telegram_id,
            source="share_watchlist",
            reference_id=token,
            payload={"items_count": items_count},
        )

    async def log_watchlist_link_opened(self, telegram_id: int, token: str) -> None:
        await self.log_event(
            event_name="watchlist_link_opened",
            telegram_id=telegram_id,
            source="share_watchlist",
            reference_id=token,
        )

    async def log_watchlist_item_followed(self, telegram_id: int, token: str, media_type: str, tmdb_id: int) -> None:
        await self.log_event(
            event_name="watchlist_item_followed",
            telegram_id=telegram_id,
            source="share_watchlist",
            reference_id=f"{token}:{media_type}:{tmdb_id}",
            payload={"token": token, "media_type": media_type, "tmdb_id": tmdb_id},
        )

    async def log_watchlist_follow_all(self, telegram_id: int, token: str, items_added: int) -> None:
        await self.log_event(
            event_name="watchlist_follow_all",
            telegram_id=telegram_id,
            source="share_watchlist",
            reference_id=token,
            payload={"token": token, "items_added": items_added},
        )

    # 3. Telegram-канал
    async def log_channel_link_opened(self, telegram_id: int, post_id: int, tmdb_id: Optional[int] = None) -> None:
        await self.log_event(
            event_name="channel_link_opened",
            telegram_id=telegram_id,
            source="telegram_channel",
            reference_id=str(post_id),
            payload={"post_id": post_id, "tmdb_id": tmdb_id},
        )

    async def log_content_followed_from_channel(self, telegram_id: int, post_id: int, media_type: str, tmdb_id: int) -> None:
        await self.log_event(
            event_name="content_followed_from_channel",
            telegram_id=telegram_id,
            source="telegram_channel",
            reference_id=str(post_id),
            payload={"post_id": post_id, "media_type": media_type, "tmdb_id": tmdb_id},
        )
