from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import BigInteger, ForeignKey, String, Integer, Date, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    """Базовый класс для моделей SQLAlchemy."""
    pass

class User(Base):
    """Модель пользователя."""
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String, default='ru')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связь с отслеживаемыми элементами
    tracked_items: Mapped[List["TrackedItem"]] = relationship("TrackedItem", back_populates="user", cascade="all, delete-orphan")

class TrackedItem(Base):
    """Модель отслеживаемого фильма или сериала."""
    __tablename__ = 'tracked_items'
    __table_args__ = (
        UniqueConstraint('user_id', 'tmdb_id', 'media_type', name='uq_user_tmdb_media'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False) # 'tv' или 'movie'
    title: Mapped[str] = mapped_column(String, nullable=False)
    original_title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    poster_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_known_season: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_known_air_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_season_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    next_air_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    custom_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    network: Mapped[Optional[str]] = mapped_column(String, nullable=True) # например, 'Netflix', 'HBO'
    status: Mapped[str] = mapped_column(String, default='waiting') # 'waiting', 'announced', 'released'
    tmdb_url: Mapped[str] = mapped_column(String, nullable=False)
    notified_announced: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_released: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_reminder: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    user: Mapped["User"] = relationship("User", back_populates="tracked_items")
    notifications: Mapped[List["NotificationLog"]] = relationship("NotificationLog", back_populates="tracked_item", cascade="all, delete-orphan")

class NotificationLog(Base):
    """Модель лога уведомлений."""
    __tablename__ = 'notification_logs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tracked_item_id: Mapped[int] = mapped_column(Integer, ForeignKey('tracked_items.id'), nullable=False)
    notification_type: Mapped[str] = mapped_column(String, nullable=False) # 'announced', 'reminder', 'released'
    message: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи
    tracked_item: Mapped["TrackedItem"] = relationship("TrackedItem", back_populates="notifications")
