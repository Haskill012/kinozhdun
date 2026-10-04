from datetime import date, datetime, timedelta
from typing import List, Optional
from sqlalchemy import select, and_, or_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import User, TrackedItem, NotificationLog

class Repository:
    """Репозиторий для работы с базой данных."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(self, telegram_id: int, username: Optional[str], first_name: Optional[str]) -> User:
        """Получить пользователя по telegram_id, если нет - создать."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            self.session.add(user)
            await self.session.flush()
        else:
            # Обновляем данные, если они изменились
            if user.username != username or user.first_name != first_name:
                user.username = username
                user.first_name = first_name
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
