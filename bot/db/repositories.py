import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Any, Tuple
from sqlalchemy import select, and_, or_, update, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import User, TrackedItem, NotificationLog, SharedWatchlist, ChannelPost, AnalyticsEvent

class Repository:
    """Репозиторий для работы с базой данных."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str],
        first_name: Optional[str],
        referral_source: Optional[str] = None,
        referrer_id: Optional[int] = None,
    ) -> User:
        """Получить пользователя по telegram_id, если нет - создать."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                referral_source=referral_source,
                referrer_id=referrer_id,
            )
            self.session.add(user)
            await self.session.flush()
        else:
            # Обновляем данные, если они изменились
            changed = False
            if user.username != username or user.first_name != first_name:
                user.username = username
                user.first_name = first_name
                changed = True
            if referral_source and not user.referral_source:
                user.referral_source = referral_source
                changed = True
            if referrer_id and not user.referrer_id:
                user.referrer_id = referrer_id
                changed = True
            if changed:
                await self.session.flush()
        
        return user

    async def add_tracked_item(self, user_id: int, tmdb_id: int, media_type: str, title: str, 
                               original_title: Optional[str], poster_path: Optional[str], 
                               last_known_season: Optional[int], last_known_air_date: Optional[date], 
                               next_air_date: Optional[date], tmdb_url: str,
                               network: Optional[str] = None) -> TrackedItem:
        """Добавить элемент в отслеживание."""
        item = TrackedItem(
            user_id=user_id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            title=title,
            original_title=original_title,
            poster_path=poster_path,
            last_known_season=last_known_season,
            last_known_air_date=last_known_air_date,
            next_air_date=next_air_date,
            tmdb_url=tmdb_url,
            network=network,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def get_user_items(self, telegram_id: int) -> List[TrackedItem]:
        """Получить все отслеживаемые элементы пользователя."""
        stmt = select(TrackedItem).join(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_tracked_item(self, item_id: int) -> Optional[TrackedItem]:
        """Получить отслеживаемый элемент по ID."""
        stmt = select(TrackedItem).options(selectinload(TrackedItem.user)).where(TrackedItem.id == item_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def remove_tracked_item(self, item_id: int, telegram_id: int) -> bool:
        """Удалить элемент из отслеживания."""
        # Сначала проверяем, принадлежит ли элемент пользователю
        stmt = select(TrackedItem).join(User).where(
            and_(TrackedItem.id == item_id, User.telegram_id == telegram_id)
        )
        result = await self.session.execute(stmt)
        item = result.scalar_one_or_none()
        
        if item:
            await self.session.delete(item)
            await self.session.flush()
            return True
        return False

    async def get_all_waiting_items(self) -> List[TrackedItem]:
        """Получить все элементы со статусом waiting или announced с подгруженным пользователем."""
        stmt = (
            select(TrackedItem)
            .options(selectinload(TrackedItem.user))
            .where(TrackedItem.status.in_(['waiting', 'announced']))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_announced_items(self) -> List[TrackedItem]:
        """Получить все элементы со статусом announced."""
        stmt = select(TrackedItem).options(selectinload(TrackedItem.user)).where(TrackedItem.status == 'announced')
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_item_dates(self, item_id: int, next_season_number: Optional[int], 
                                next_air_date: Optional[date], status: str) -> None:
        """Обновить даты выхода и статус элемента."""
        stmt = update(TrackedItem).where(TrackedItem.id == item_id).values(
            next_season_number=next_season_number,
            next_air_date=next_air_date,
            status=status,
            updated_at=datetime.utcnow()
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def set_custom_date(self, item_id: int, custom_date: Optional[date]) -> None:
        """Установить пользовательскую дату выхода."""
        stmt = update(TrackedItem).where(TrackedItem.id == item_id).values(
            custom_date=custom_date,
            updated_at=datetime.utcnow()
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_notified(self, item_id: int, notification_type: str) -> None:
        """Отметить элемент как уведомленный (анонс, напоминание или релиз)."""
        values = {'updated_at': datetime.utcnow()}
        if notification_type == 'announced':
            values['notified_announced'] = True
        elif notification_type == 'reminder':
            values['notified_reminder'] = True
        elif notification_type == 'released':
            values['notified_released'] = True
            
        stmt = update(TrackedItem).where(TrackedItem.id == item_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()

    async def reset_notification_flags(self, item_id: int) -> None:
        """Сбросить флаги уведомлений (например, если дата изменилась)."""
        stmt = update(TrackedItem).where(TrackedItem.id == item_id).values(
            notified_announced=False,
            notified_released=False,
            notified_reminder=False,
            updated_at=datetime.utcnow()
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def is_already_tracking(self, telegram_id: int, tmdb_id: int, media_type: str) -> bool:
        """Проверить, отслеживает ли пользователь уже этот элемент."""
        stmt = select(TrackedItem).join(User).where(
            and_(
                User.telegram_id == telegram_id,
                TrackedItem.tmdb_id == tmdb_id,
                TrackedItem.media_type == media_type
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_items_for_reminder(self, days_before: int = 3) -> List[TrackedItem]:
        """Получить элементы, для которых нужно отправить напоминание (выходят через N дней)."""
        target_date = date.today() + timedelta(days=days_before)
        
        # Проверяем и next_air_date, и custom_date
        stmt = (
            select(TrackedItem)
            .options(selectinload(TrackedItem.user))
            .where(
                and_(
                    TrackedItem.notified_reminder == False,
                    or_(
                        TrackedItem.next_air_date == target_date,
                        TrackedItem.custom_date == target_date
                    )
                )
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def log_notification(self, tracked_item_id: int, notification_type: str, message: str) -> None:
        """Залогировать отправленное уведомление."""
        log = NotificationLog(
            tracked_item_id=tracked_item_id,
            notification_type=notification_type,
            message=message
        )
        self.session.add(log)
        await self.session.flush()

    # --- Методы для работы с расшаренными списками (SharedWatchlist) ---

    async def create_shared_watchlist(
        self,
        user_id: int,
        items: List[Any],
        title: str = "Список ожидания"
    ) -> SharedWatchlist:
        """Создать снапшот списка ожидания пользователя и вернуть объект с уникальным токеном."""
        snapshot_data = []
        for it in items:
            if isinstance(it, dict):
                snapshot_data.append(it)
            else:
                snapshot_data.append({
                    "tmdb_id": it.tmdb_id,
                    "media_type": it.media_type,
                    "title": it.title,
                    "original_title": it.original_title,
                    "poster_path": it.poster_path,
                    "last_known_season": it.last_known_season,
                    "last_known_air_date": it.last_known_air_date.isoformat() if it.last_known_air_date else None,
                    "next_season_number": it.next_season_number,
                    "next_air_date": it.next_air_date.isoformat() if it.next_air_date else None,
                    "network": it.network,
                    "status": it.status,
                    "tmdb_url": it.tmdb_url,
                })

        token = secrets.token_hex(5) # 10 символов, безопасных для Telegram deep link
        watchlist = SharedWatchlist(
            token=token,
            user_id=user_id,
            title=title,
            items_snapshot=json.dumps(snapshot_data, ensure_ascii=False),
        )
        self.session.add(watchlist)
        await self.session.flush()
        return watchlist

    async def get_shared_watchlist_by_token(self, token: str) -> Optional[SharedWatchlist]:
        """Получить снапшот расшаренного списка по токену."""
        stmt = select(SharedWatchlist).where(SharedWatchlist.token == token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_watchlist_views(self, token: str) -> None:
        """Увеличить счетчик просмотров расшаренного списка."""
        stmt = (
            update(SharedWatchlist)
            .where(SharedWatchlist.token == token)
            .values(views_count=SharedWatchlist.views_count + 1)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def batch_add_tracked_items(
        self,
        user_id: int,
        items_data: List[dict],
        max_items: int = 50
    ) -> Tuple[int, List[str]]:
        """Пакетное добавление элементов из снапшота в список пользователя.
        
        Пропускает уже отслеживаемые элементы и соблюдает лимит пользователя.
        Возвращает кортеж: (количество добавленных, список названий добавленных).
        """
        # Получаем текущие отслеживаемые элементы пользователя
        stmt = select(TrackedItem).where(TrackedItem.user_id == user_id)
        result = await self.session.execute(stmt)
        existing_items = list(result.scalars().all())
        existing_keys = {(it.media_type, it.tmdb_id) for it in existing_items}

        available_slots = max(0, max_items - len(existing_items))
        added_count = 0
        added_titles = []

        for item_data in items_data:
            if added_count >= available_slots:
                break

            media_type = item_data.get("media_type", "movie")
            tmdb_id = int(item_data.get("tmdb_id", 0))

            if (media_type, tmdb_id) in existing_keys:
                continue

            last_known_air_date = None
            if item_data.get("last_known_air_date"):
                try:
                    last_known_air_date = date.fromisoformat(item_data["last_known_air_date"])
                except (ValueError, TypeError):
                    pass

            next_air_date = None
            if item_data.get("next_air_date"):
                try:
                    next_air_date = date.fromisoformat(item_data["next_air_date"])
                except (ValueError, TypeError):
                    pass

            new_item = TrackedItem(
                user_id=user_id,
                tmdb_id=tmdb_id,
                media_type=media_type,
                title=item_data.get("title", "Без названия"),
                original_title=item_data.get("original_title"),
                poster_path=item_data.get("poster_path"),
                last_known_season=item_data.get("last_known_season"),
                last_known_air_date=last_known_air_date,
                next_season_number=item_data.get("next_season_number"),
                next_air_date=next_air_date,
                network=item_data.get("network"),
                status=item_data.get("status", "waiting"),
                tmdb_url=item_data.get("tmdb_url", f"https://www.themoviedb.org/{media_type}/{tmdb_id}"),
            )
            self.session.add(new_item)
            existing_keys.add((media_type, tmdb_id))
            added_count += 1
            added_titles.append(new_item.title)

        await self.session.flush()
        return added_count, added_titles

    # --- Методы для работы с публикациями канала (ChannelPost) ---

    async def get_channel_post(self, post_id: int) -> Optional[ChannelPost]:
        """Получить публикацию канала по ID."""
        stmt = select(ChannelPost).where(ChannelPost.id == post_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_channel_post_by_hash(self, content_hash: str) -> Optional[ChannelPost]:
        """Проверить наличие публикации по хэшу дедупликации."""
        stmt = select(ChannelPost).where(ChannelPost.content_hash == content_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_channel_post(
        self,
        tmdb_id: int,
        media_type: str,
        event_type: str,
        title: str,
        content_hash: str,
        season_number: Optional[int] = None,
        air_date: Optional[date] = None,
        network: Optional[str] = None,
        poster_path: Optional[str] = None,
        status: str = "published",
        telegram_message_id: Optional[int] = None,
        published_at: Optional[datetime] = None,
    ) -> ChannelPost:
        """Создать запись публикации канала."""
        post = ChannelPost(
            tmdb_id=tmdb_id,
            media_type=media_type,
            event_type=event_type,
            title=title,
            content_hash=content_hash,
            season_number=season_number,
            air_date=air_date,
            network=network,
            poster_path=poster_path,
            status=status,
            telegram_message_id=telegram_message_id,
            published_at=published_at or (datetime.now(timezone.utc).replace(tzinfo=None) if status == "published" else None),
        )
        self.session.add(post)
        await self.session.flush()
        return post

    async def mark_channel_post_published(self, post_id: int, telegram_message_id: int) -> None:
        """Отметить пост канала как опубликованный."""
        stmt = (
            update(ChannelPost)
            .where(ChannelPost.id == post_id)
            .values(
                status="published",
                telegram_message_id=telegram_message_id,
                published_at=datetime.now(timezone.utc).replace(tzinfo=None)
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_last_published_channel_post(self) -> Optional[ChannelPost]:
        """Получить время последней опубликованной записи в канале."""
        stmt = (
            select(ChannelPost)
            .where(ChannelPost.status == "published")
            .order_by(desc(ChannelPost.published_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_channel_posts(self) -> List[ChannelPost]:
        """Получить отложенные публикации из очереди."""
        stmt = (
            select(ChannelPost)
            .where(ChannelPost.status == "pending")
            .order_by(ChannelPost.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # --- Минимальная аналитика событий (AnalyticsEvent) ---

    async def log_analytics_event(
        self,
        event_name: str,
        telegram_id: Optional[int] = None,
        source: Optional[str] = None,
        reference_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> AnalyticsEvent:
        """Залогировать событие роста/перехода/шеринга."""
        payload_str = json.dumps(payload, ensure_ascii=False) if payload else None
        event = AnalyticsEvent(
            event_name=event_name,
            telegram_id=telegram_id,
            source=source,
            reference_id=reference_id,
            payload=payload_str,
        )
        self.session.add(event)
        await self.session.flush()
        return event
