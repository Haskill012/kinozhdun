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
    referral_source: Mapped[Optional[str]] = mapped_column(String, nullable=True) # например: 'share_content:tv:82856', 'share_watchlist:token', 'telegram_channel:12'
    referrer_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True) # telegram_id пригласившего
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связь с отслеживаемыми элементами
    tracked_items: Mapped[List["TrackedItem"]] = relationship("TrackedItem", back_populates="user", cascade="all, delete-orphan")
    shared_watchlists: Mapped[List["SharedWatchlist"]] = relationship("SharedWatchlist", back_populates="user", cascade="all, delete-orphan")

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

class SharedWatchlist(Base):
    """Модель расшаренного списка ожидания (снапшот)."""
    __tablename__ = 'shared_watchlists'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id'), nullable=False)
    title: Mapped[str] = mapped_column(String, default="Список ожидания")
    items_snapshot: Mapped[str] = mapped_column(String, nullable=False) # JSON со списком тайтлов
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи (приватные данные пользователя никогда не отправляются получателям)
    user: Mapped["User"] = relationship("User", back_populates="shared_watchlists")

class ChannelPost(Base):
    """Модель публикации в Telegram-канале Кинождуна."""
    __tablename__ = 'channel_posts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_type: Mapped[str] = mapped_column(String, default='news') # 'news', 'date_announcement', 'filming', 'trailer', 'daily_digest', 'weekly_digest', 'status_change', 'sponsored'
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # nullable для дайджестов
    media_type: Mapped[Optional[str]] = mapped_column(String, nullable=True) # 'tv' или 'movie'
    event_type: Mapped[str] = mapped_column(String, nullable=False) # 'announced', 'released', 'status_change', 'season_announced', 'renewed', 'filming_started', 'filming_finished', 'date_announced', 'date_postponed', 'trailer', 'canceled', 'ended', 'daily_digest', 'weekly_digest'
    title: Mapped[str] = mapped_column(String, nullable=False)
    season_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    air_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    network: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    poster_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default='tmdb') # 'tmdb', 'official', 'admin'
    credibility: Mapped[str] = mapped_column(String, default='confirmed') # 'confirmed', 'likely', 'rumor'
    post_text: Mapped[Optional[str]] = mapped_column(String, nullable=True) # фактический/предлагаемый текст
    trailer_url: Mapped[Optional[str]] = mapped_column(String, nullable=True) # прямая ссылка на YouTube трейлер
    payload: Mapped[Optional[str]] = mapped_column(String, nullable=True) # JSON с доп. метаданными (old_date, items)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False) # задел под будущую монетизацию
    partner_url: Mapped[Optional[str]] = mapped_column(String, nullable=True) # задел под партнёрские ссылки
    sponsored_label: Mapped[Optional[str]] = mapped_column(String, nullable=True) # задел под маркировку рекламы
    status: Mapped[str] = mapped_column(String, default='published') # 'pending', 'approved', 'published', 'rejected', 'failed'
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False) # дедупликация (event fingerprint)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AnalyticsEvent(Base):
    """Минимальная аналитика событий органического роста и переходов."""
    __tablename__ = 'analytics_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True) # 'share_content', 'share_watchlist', 'telegram_channel', etc.
    reference_id: Mapped[Optional[str]] = mapped_column(String, nullable=True) # tmdb_id, watchlist token, post_id
    payload: Mapped[Optional[str]] = mapped_column(String, nullable=True) # JSON с доп. контекстом
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
