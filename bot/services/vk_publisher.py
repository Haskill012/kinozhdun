"""Сервис публикации новостей и карточек премьер в сообщество ВКонтакте «КиноЖдун»."""

from datetime import date
import logging
from pathlib import Path
from typing import Any, Optional
import aiohttp
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from bot.config import Settings
from bot.db.repositories import Repository
from bot.services.channel import generate_event_fingerprint
from bot.services.vk_client import VKClient, VKApiError
from bot.db.models import VKPost
from bot.services.vk_spintax import format_vk_post

logger = logging.getLogger(__name__)


class VKPublisher:
    """Сервис формирования и публикации постов в группу ВКонтакте."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings,
        vk_client: Optional[VKClient] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
    ):
        self.session_factory = session_factory
        self.settings = settings
        self.http_session = http_session
        self._owns_http_session = False

        if vk_client is not None:
            self.vk_client = vk_client
        elif settings.VK_ACCESS_TOKEN and settings.VK_GROUP_ID:
            self.vk_client = VKClient(
                access_token=settings.VK_ACCESS_TOKEN,
                group_id=settings.VK_GROUP_ID,
                user_token=settings.VK_USER_TOKEN,
                session=self.http_session,
            )

        else:
            self.vk_client = None

    def is_configured(self) -> bool:
        """Проверяет, заданы ли настройки для публикации в VK."""
        return bool(
            self.settings.VK_POSTING_ENABLED
            and self.settings.VK_ACCESS_TOKEN
            and self.settings.VK_GROUP_ID
            and self.vk_client
            # Message-storage photos were silently dropped from a real wall post.
            # Only a wall upload with a validated user token is supported.
            and (self.settings.VK_ATTACHMENT_MODE in ("text", "link")
                 or (self.settings.VK_ATTACHMENT_MODE == "photo" and self.settings.VK_USER_TOKEN))
        )

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            self._owns_http_session = True
        return self.http_session

    async def close(self) -> None:
        if self._owns_http_session and self.http_session and not self.http_session.closed:
            await self.http_session.close()
        if self.vk_client:
            await self.vk_client.close()

    async def fetch_poster_bytes(self, poster_path_or_url: Optional[str]) -> Optional[bytes]:
        """Загружает бинарные данные постера из TMDB или локальных файлов."""
        if poster_path_or_url:
            url = poster_path_or_url
            if not url.startswith("http://") and not url.startswith("https://"):
                url = f"{self.settings.TMDB_IMAGE_BASE_URL.rstrip('/')}/{poster_path_or_url.lstrip('/')}"

            try:
                session = await self._get_http_session()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    logger.warning(f"Не удалось скачать постер {url}: HTTP {resp.status}")
            except Exception as e:
                logger.warning(f"Ошибка при скачивании постера {url}: {e}")

        # A failed film poster must not silently become an unrelated mascot.
        if poster_path_or_url:
            return None
        # Brand artwork is allowed only when no film artwork was supplied.
        for fallback_path in [
            Path(__file__).parent.parent.parent / "website" / "static" / "mascot.jpg",
            Path(__file__).parent.parent.parent / "avatar.jpg",
        ]:
            if fallback_path.exists():
                try:
                    return fallback_path.read_bytes()
                except Exception:
                    pass

        return None

    async def publish_event(
        self,
        title: str,
        media_type: str = "movie",
        event_type: str = "announced",
        tmdb_id: Optional[int] = None,
        season_number: Optional[int] = None,
        air_date: Optional[date] = None,
        genres: Optional[list[str]] = None,
        network: Optional[str] = None,
        overview: Optional[str] = None,
        poster_path: Optional[str] = None,
        item_id: Optional[int] = None,
        publish_date: Optional[int] = None,
        force: bool = False,
        episode_number: Optional[int] = None,
        source_url: Optional[str] = None,
    ) -> Optional[int]:
        """Формирует и публикует пост в VK.

        Выполняет проверку дедупликации, генерацию вариативного текста (Spintax),
        загрузку постера, прикрепление опроса и (при необходимости) ссылку в комментарии.
        """
        if not self.is_configured():
            logger.info("Публикация в VK пропущена: режим или доступ не настроен")
            return None

        # 1. Дедупликация через fingerprint
        date_str = air_date.isoformat() if air_date else "nodate"
        content_hash = generate_event_fingerprint(
            tmdb_id=tmdb_id,
            media_type=media_type,
            event_type=event_type,
            season_number=season_number,
            extra_key=date_str,
        )

        async with self.session_factory() as session:
            repo = Repository(session)
            if not force and await repo.is_vk_post_exists(content_hash):
                logger.info(f"Событие «{title}» ({content_hash}) уже было опубликовано в VK. Пропуск.")
                return None

        # 2. Форматирование текста через Spintax-генератор
        site_url = self.settings.SITE_BASE_URL
        community_photo = self.settings.VK_ATTACHMENT_MODE == "community_photo"
        text_only = self.settings.VK_ATTACHMENT_MODE in ("text", "link")
        link_card = self.settings.VK_ATTACHMENT_MODE == "link"
        create_poll = self.settings.VK_CREATE_POLL and not community_photo and not text_only
        post_data = format_vk_post(
            title=title,
            media_type=media_type,
            event_type=event_type,
            season_number=season_number,
            air_date=air_date,
            genres=genres,
            network=network,
            overview=overview,
            site_url=site_url,
            item_id=tmdb_id or item_id,
            # Deferred posts cannot receive a comment until they are published.
            link_in_comment=self.settings.VK_LINK_IN_COMMENT and not publish_date and not community_photo and not text_only,
            create_poll=create_poll,
            episode_number=episode_number,
            source_url=source_url,
        )

        # 3. Подготовка вложений (attachments)
        attachments: list[str] = []

        # Photo upload is required: never publish an unnoticed text-only fallback.
        try:
            assert self.vk_client is not None
            if text_only:
                if link_card:
                    attachments.append(post_data["target_url"])
            elif community_photo:
                poster_bytes = await self.fetch_poster_bytes(poster_path)
                if not poster_bytes:
                    raise RuntimeError("Не удалось получить обложку карточки")
                photo_attach = await self.vk_client.upload_community_photo(poster_bytes)
                if not photo_attach:
                    raise RuntimeError("Не удалось сохранить обложку в VK")
                attachments.append(photo_attach)
            else:
                poster_bytes = await self.fetch_poster_bytes(poster_path)
                if not poster_bytes:
                    raise RuntimeError("Не удалось получить постер; публикация отложена")
                photo_attach = await self.vk_client.upload_wall_photo(poster_bytes)
                if not photo_attach:
                    raise RuntimeError("Не удалось загрузить постер в VK; публикация отложена")
                attachments.append(photo_attach)
        except Exception as e:
            logger.warning("Пост «%s» не опубликован: %s", title, e)
            return None

        # Создание интерактивного опроса (для буста охватов)
        if create_poll and post_data.get("poll") and self.vk_client:
            try:
                poll = post_data["poll"]
                poll_attach = await self.vk_client.create_poll(
                    question=poll["question"],
                    answers=poll["answers"],
                )
                if poll_attach:
                    attachments.append(poll_attach)
            except Exception as e:
                logger.info(f"Создание опроса в VK пропущено ({e}).")
                post_data["text"] = post_data["text"].replace(
                    "Будете смотреть? Голосуйте в опросе ниже.",
                    "Будете смотреть? Напишите в комментариях.",
                )
        # 4. Публикация записи на стене
        # Commit a claim before the external write. A lost reply must not cause a duplicate.
        async with self.session_factory() as session:
            previous = await session.scalar(select(VKPost).where(VKPost.content_hash == content_hash))
            if previous:
                claimed = await session.execute(update(VKPost).where(
                    VKPost.id == previous.id, VKPost.status == 'failed').values(status='sending'))
                if claimed.rowcount != 1:
                    return None
            else:
                session.add(VKPost(content_hash=content_hash, title=title, event_type=event_type,
                                   tmdb_id=tmdb_id, media_type=media_type, status='sending'))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
        try:
            assert self.vk_client is not None
            post_id = await self.vk_client.post_to_wall(
                text=post_data["text"],
                attachments=attachments if attachments else None,
                publish_date=publish_date,
            )

            # Persist the successful wall write before optional comment operations.
            # A failed comment must never cause the whole post to be sent again.
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.record_vk_post(
                    content_hash=content_hash, title=title, event_type=event_type,
                    tmdb_id=tmdb_id, media_type=media_type, vk_post_id=post_id,
                    status="scheduled" if publish_date else "published" if text_only else "verification_pending",
                )
                await session.commit()

            if not publish_date and not text_only:
                status = "verification_pending"
                try:
                    status = "published" if await self.vk_client.post_has_photo(post_id, photo_attach) else "image_missing"
                except Exception as error:
                    logger.warning("Не удалось проверить фото записи VK %s: %s", post_id, error)
                async with self.session_factory() as session:
                    await Repository(session).record_vk_post(
                        content_hash=content_hash, title=title, event_type=event_type,
                        tmdb_id=tmdb_id, media_type=media_type, vk_post_id=post_id, status=status,
                    )
                    await session.commit()
                if status != "published":
                    self.settings.VK_AUTO_PUBLISH = False
                    logger.error("Запись VK %s создана, но фото не подтверждено (%s). Автопостинг остановлен; повтор записи запрещён.", post_id, status)
                    return None

            # 5. Если настроена ссылка в комментариях
            if not text_only and self.settings.VK_LINK_IN_COMMENT and post_data.get("comment_text") and post_id:
                try:
                    await self.vk_client.add_comment(
                        post_id=post_id,
                        text=post_data["comment_text"],
                    )
                except Exception as e:
                    logger.warning(f"Не удалось оставить автокомментарий к посту {post_id}: {e}")
                    # Keep the destination accessible if comments are disabled.
                    try:
                        await self.vk_client.edit_post(
                            post_id, post_data["text"] + "\n\n🔗 " + post_data["target_url"], attachments,
                        )
                    except Exception:
                        logger.error("Пост VK %s опубликован, но ссылку нужно добавить вручную", post_id)

            logger.info(f"Успешно опубликован пост в VK: «{title}» (post_id={post_id})")
            return post_id

        except Exception as e:
            logger.error(f"Ошибка при публикации в VK для «{title}»: {e}", exc_info=True)
            async with self.session_factory() as session:
                repo = Repository(session)
                await repo.record_vk_post(
                    content_hash=content_hash,
                    title=title,
                    event_type=event_type,
                    tmdb_id=tmdb_id,
                    media_type=media_type,
                    vk_post_id=None,
                    status="failed" if isinstance(e, VKApiError) else "uncertain",
                )
                await session.commit()
            return None
