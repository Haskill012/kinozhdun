import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Any, Tuple
from sqlalchemy import select, and_, or_, update, delete, desc, func, distinct
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
            .where(or_(TrackedItem.status.in_(['waiting', 'announced']),
                       and_(TrackedItem.media_type == 'tv',
                            TrackedItem.status.notin_(['Ended', 'Canceled', 'ended']))))
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

    async def set_custom_date(self, item_id: int, custom_date: Optional[date], telegram_id: int) -> bool:
        """Only the owner may change a date; a new date gets a new reminder."""
        item = await self.get_tracked_item(item_id)
        if not item or not item.user or item.user.telegram_id != telegram_id:
            return False
        if item.custom_date == custom_date:
            return True
        stmt = update(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id.in_(select(User.id).where(User.telegram_id == telegram_id)),
        ).values(custom_date=custom_date, notified_reminder=False, updated_at=datetime.utcnow())
        await self.session.execute(stmt)
        await self.session.flush()
        return True

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

    async def get_tracked_series(self) -> List[TrackedItem]:
        result = await self.session.execute(
            select(TrackedItem).options(selectinload(TrackedItem.user))
            .where(TrackedItem.media_type == "tv")
        )
        return list(result.scalars().all())

    async def delete_user_data(self, telegram_id: int) -> None:
        """Erase the requesting user's active profile and its dependent data."""
        users = select(User.id).where(User.telegram_id == telegram_id)
        items = select(TrackedItem.id).where(TrackedItem.user_id.in_(users))
        await self.session.execute(delete(NotificationLog).where(NotificationLog.tracked_item_id.in_(items)))
        await self.session.execute(delete(SharedWatchlist).where(SharedWatchlist.user_id.in_(users)))
        await self.session.execute(delete(TrackedItem).where(TrackedItem.user_id.in_(users)))
        await self.session.execute(delete(AnalyticsEvent).where(AnalyticsEvent.telegram_id == telegram_id))
        await self.session.execute(update(User).where(User.referrer_id == telegram_id).values(referrer_id=None))
        await self.session.execute(delete(User).where(User.telegram_id == telegram_id))

    async def has_notification(self, item_id: int, notification_type: str) -> bool:
        result = await self.session.execute(
            select(NotificationLog.id).where(
                NotificationLog.tracked_item_id == item_id,
                NotificationLog.notification_type == notification_type,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_items_for_reminder(self, days_before: int = 3) -> List[TrackedItem]:
        """Получить элементы, для которых нужно отправить напоминание (выходят через N дней)."""
        target_date = date.today() + timedelta(days=days_before)
        
        # Пользовательская дата имеет приоритет над общей датой премьеры.
        stmt = (
            select(TrackedItem)
            .options(selectinload(TrackedItem.user))
            .where(
                and_(
                    TrackedItem.notified_reminder == False,
                    func.coalesce(TrackedItem.custom_date, TrackedItem.next_air_date) == target_date
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

    get_channel_post_by_id = get_channel_post

    async def claim_channel_post(self, post_id: int) -> bool:
        """Atomic persisted claim prevents duplicate sends across publisher instances."""
        result = await self.session.execute(update(ChannelPost).where(
            ChannelPost.id == post_id, ChannelPost.status.in_(['pending', 'approved']),
        ).values(status='publishing'))
        return result.rowcount == 1

    async def get_channel_post_by_hash(self, content_hash: str) -> Optional[ChannelPost]:
        """Проверить наличие публикации по хэшу дедупликации."""
        stmt = select(ChannelPost).where(ChannelPost.content_hash == content_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_channel_post(
        self,
        title: str,
        content_hash: str,
        event_type: str,
        tmdb_id: Optional[int] = None,
        media_type: Optional[str] = None,
        post_type: str = "news",
        season_number: Optional[int] = None,
        air_date: Optional[date] = None,
        network: Optional[str] = None,
        poster_path: Optional[str] = None,
        source: str = "tmdb",
        credibility: str = "confirmed",
        post_text: Optional[str] = None,
        trailer_url: Optional[str] = None,
        payload: Optional[str] = None,
        is_sponsored: bool = False,
        partner_url: Optional[str] = None,
        sponsored_label: Optional[str] = None,
        status: str = "published",
        telegram_message_id: Optional[int] = None,
        published_at: Optional[datetime] = None,
    ) -> ChannelPost:
        """Создать запись публикации канала."""
        post = ChannelPost(
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
            payload=payload,
            is_sponsored=is_sponsored,
            partner_url=partner_url,
            sponsored_label=sponsored_label,
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

    async def update_channel_post_status(
        self,
        post_id: int,
        status: str,
        telegram_message_id: Optional[int] = None,
        post_text: Optional[str] = None,
    ) -> Optional[ChannelPost]:
        """Обновить статус и данные публикации (approve, reject, edit)."""
        values: dict[str, Any] = {"status": status}
        if telegram_message_id is not None:
            values["telegram_message_id"] = telegram_message_id
        if status == "published":
            values["published_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
        if post_text is not None:
            values["post_text"] = post_text

        stmt = update(ChannelPost).where(ChannelPost.id == post_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()
        return await self.get_channel_post(post_id)

    async def update_channel_post_text(self, post_id: int, post_text: str) -> None:
        """Обновить предложенный текст поста."""
        stmt = update(ChannelPost).where(ChannelPost.id == post_id).values(post_text=post_text)
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_last_published_channel_post(self) -> Optional[ChannelPost]:
        """Получить последнюю опубликованную запись в канале."""
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

    async def get_pending_channel_posts_count(self) -> int:
        """Получить количество публикаций, ожидающих модерации."""
        stmt = select(func.count(ChannelPost.id)).where(ChannelPost.status == "pending")
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_pending_channel_post_by_index(self, offset: int = 0) -> Optional[ChannelPost]:
        """Получить публикацию из очереди pending с заданным смещением."""
        stmt = (
            select(ChannelPost)
            .where(ChannelPost.status == "pending")
            .order_by(ChannelPost.created_at)
            .offset(offset)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # --- Запросы релизов для дайджестов («Что выходит сегодня» и «Главные премьеры недели») ---

    async def get_items_releasing_on_date(self, target_date: date) -> List[TrackedItem]:
        """Получить уникальные элементы из базы, релиз которых назначен на указанную дату."""
        stmt = (
            select(TrackedItem)
            .where(
                or_(
                    TrackedItem.next_air_date == target_date,
                    TrackedItem.custom_date == target_date,
                )
            )
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        # Дедуплицируем по (media_type, tmdb_id)
        seen = set()
        unique_items = []
        for it in items:
            key = (it.media_type, it.tmdb_id)
            if key not in seen:
                seen.add(key)
                unique_items.append(it)
        return unique_items

    async def get_items_releasing_between(self, start_date: date, end_date: date) -> List[TrackedItem]:
        """Получить уникальные элементы из базы, релиз которых назначен в диапазоне дат."""
        stmt = (
            select(TrackedItem)
            .where(
                or_(
                    and_(TrackedItem.next_air_date >= start_date, TrackedItem.next_air_date <= end_date),
                    and_(TrackedItem.custom_date >= start_date, TrackedItem.custom_date <= end_date),
                )
            )
        )
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        seen = set()
        unique_items = []
        for it in items:
            key = (it.media_type, it.tmdb_id)
            if key not in seen:
                seen.add(key)
                unique_items.append(it)
        return unique_items

    # --- Аналитика воронки Telegram-канала ---

    async def get_channel_analytics_summary(self) -> dict[str, Any]:
        """Формирует агрегированную сводку аналитики по Telegram-каналу."""
        # Количество опубликованных постов
        stmt_posts = select(func.count(ChannelPost.id)).where(ChannelPost.status == "published")
        posts_count = (await self.session.execute(stmt_posts)).scalar() or 0

        # Количество переходов из канала в бота (открытий ссылок ch_*)
        stmt_opens = select(func.count(AnalyticsEvent.id)).where(AnalyticsEvent.event_name == "channel_link_opened")
        opens_count = (await self.session.execute(stmt_opens)).scalar() or 0

        # Количество уникальных пользователей, пришедших из канала
        stmt_users = select(func.count(distinct(AnalyticsEvent.telegram_id))).where(
            and_(AnalyticsEvent.event_name == "channel_link_opened", AnalyticsEvent.telegram_id.isnot(None))
        )
        unique_users = (await self.session.execute(stmt_users)).scalar() or 0

        # Количество тайтлов, добавленных в отслеживание после перехода из канала
        stmt_follows = select(func.count(AnalyticsEvent.id)).where(
            AnalyticsEvent.event_name == "content_followed_from_channel"
        )
        follows_count = (await self.session.execute(stmt_follows)).scalar() or 0

        conversion = (follows_count / opens_count * 100.0) if opens_count > 0 else 0.0

        return {
            "posts_count": posts_count,
            "opens_count": opens_count,
            "unique_users": unique_users,
            "follows_count": follows_count,
            "conversion_rate": round(conversion, 1),
        }


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
