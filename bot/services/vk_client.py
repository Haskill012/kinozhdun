"""Асинхронный клиент для работы с VK API (ВКонтакте) без внешних зависимостей кроме aiohttp."""

import json
import logging
from typing import Any, Optional
import aiohttp

logger = logging.getLogger(__name__)


class VKApiError(Exception):
    """Исключение при ошибке вызова VK API."""

    def __init__(self, error_code: int, error_msg: str, response: Optional[dict] = None):
        super().__init__(f"VK API Error {error_code}: {error_msg}")
        self.error_code = error_code
        self.error_msg = error_msg
        self.response = response or {}


class VKClient:
    """Асинхронный клиент для публикации постов, опросов и фото на стену сообщества ВКонтакте."""

    API_VERSION = "5.199"
    BASE_URL = "https://api.vk.com/method"

    def __init__(
        self,
        access_token: str,
        group_id: int,
        user_token: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """
        :param access_token: Токен сообщества
        :param group_id: Числовой ID сообщества (положительное число)
        :param user_token: Пользовательский токен администратора для загрузки фото на стену
        :param session: Опциональная сессия aiohttp
        """
        self.access_token = access_token
        self.user_token = user_token
        self.group_id = abs(int(group_id))
        self._session = session
        self._owns_session = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Закрывает HTTP-сессию, если она создавалась клиентом."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def api_call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        token: Optional[str] = None,
    ) -> Any:
        """Выполняет вызов метода VK API."""
        use_token = token or self.access_token
        if not use_token:
            raise ValueError("VK token не задан")

        call_params = {
            "v": self.API_VERSION,
            "access_token": use_token,
        }
        if params:
            call_params.update(params)

        session = await self._get_session()
        url = f"{self.BASE_URL}/{method}"

        async with session.post(url, data=call_params) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            if "error" in data:
                err = data["error"]
                log_fn = logger.debug if err.get("error_code") == 27 else logger.error
                log_fn(f"VK API ошибка при вызове {method}: {err.get('error_code')} - {err.get('error_msg')}")
                raise VKApiError(
                    error_code=err.get("error_code", 0),
                    error_msg=err.get("error_msg", "Unknown error"),
                    response=data,
                )
            if "response" not in data:
                raise RuntimeError(f"VK: пустой ответ метода {method}")
            return data["response"]

    async def upload_wall_photo(self, photo_bytes: bytes, filename: str = "poster.jpg") -> str:
        return await self._upload_photo(photo_bytes, filename, for_link=False)

    async def upload_community_photo(self, photo_bytes: bytes) -> str:
        """Store a visible post image with the community token, without sending a message."""
        return await self._upload_photo(photo_bytes, "cover.jpg", for_link=True)

    async def _upload_photo(self, photo_bytes: bytes, filename: str, for_link: bool) -> str:
        """Загружает фотографию на стену ВКонтакте для отображения в посте.

        Для публикации видимых фото на стене группы VK API требует пользовательский
        токен администратора (user_token), так как токен сообщества не имеет доступа
        к photos.getWallUploadServer (ошибка 27).
        """
        token_for_photo = self.access_token if for_link else self.user_token
        if not token_for_photo:
            raise ValueError("Для загрузки фото нужен пользовательский токен администратора VK_USER_TOKEN")
        if not photo_bytes:
            raise ValueError("Пустое изображение")
        if photo_bytes.startswith(b'\xff\xd8\xff'):
            filename, content_type = "poster.jpg", "image/jpeg"
        elif photo_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            filename, content_type = "poster.png", "image/png"
        else:
            raise ValueError("Постер должен быть JPEG или PNG")

        session = await self._get_session()

        # 1. Запрашиваем сервер загрузки фото на стену сообщества
        upload_server = await self.api_call(
            "photos.getMessagesUploadServer" if for_link else "photos.getWallUploadServer",
            {} if for_link else {"group_id": self.group_id},
            token=token_for_photo,
        )
        upload_url = upload_server.get("upload_url")

        if not upload_url:
            raise RuntimeError("VK не вернул сервер загрузки фото")

        # 2. Загружаем бинарные данные фото на полученный адрес
        data = aiohttp.FormData()
        data.add_field(
            "file1" if for_link else "photo",
            photo_bytes,
            filename=filename,
            content_type=content_type,
        )

        async with session.post(upload_url, data=data) as resp:
            resp.raise_for_status()
            upload_result = await resp.json(content_type=None)

        if not upload_result or not upload_result.get("photo") or upload_result.get("photo") == "[]":
            raise RuntimeError("VK не принял изображение (поля ответа: " + ", ".join(upload_result or {}) + ")")

        # 3. Сохраняем фото на стене группы
        saved = await self.api_call(
            "photos.saveMessagesPhoto" if for_link else "photos.saveWallPhoto",
            {
                **({} if for_link else {"group_id": self.group_id}),
                "photo": upload_result["photo"],
                "server": upload_result["server"],
                "hash": upload_result["hash"],
            },
            token=token_for_photo,
        )

        if not saved or not isinstance(saved, list) or len(saved) == 0:
            raise RuntimeError("VK не сохранил изображение")

        photo_info = saved[0]
        attachment = f"photo{photo_info['owner_id']}_{photo_info['id']}"
        if photo_info.get("access_key"):
            attachment += f"_{photo_info['access_key']}"
        logger.info("Фото сохранено в VK: owner_id=%s, id=%s", photo_info['owner_id'], photo_info['id'])
        return attachment



    async def create_poll(self, question: str, answers: list[str]) -> str:
        """Создает опрос в группе для прикрепления к посту.

        Возвращает идентификатор вложения вида 'poll{owner_id}_{id}'.
        """
        clean_answers = [a.strip() for a in answers if a.strip()]
        if not clean_answers:
            raise ValueError("Опрос должен содержать хотя бы один вариант ответа")

        resp = await self.api_call(
            "polls.create",
            {
                "owner_id": -self.group_id,
                "question": question,
                "add_answers": json.dumps(clean_answers, ensure_ascii=False),
                "is_anonymous": 1,
            },
        )

        owner_id = resp.get("owner_id")
        poll_id = resp.get("id")
        if not poll_id:
            raise RuntimeError(f"Не удалось создать опрос в VK: {resp}")

        attachment = f"poll{owner_id}_{poll_id}"
        logger.info(f"Опрос успешно создан в VK: {attachment}")
        return attachment

    async def post_to_wall(
        self,
        text: str,
        attachments: Optional[list[str]] = None,
        publish_date: Optional[int] = None,
        from_group: int = 1,
    ) -> int:
        """Публикует запись на стене сообщества.

        :param text: Текст публикации
        :param attachments: Список идентификаторов вложений ('photo-123_456', 'poll-123_789', ссылки)
        :param publish_date: Unix timestamp для отложенной публикации
        :param from_group: 1 — от имени сообщества
        :return: ID созданного поста (post_id)
        """
        params: dict[str, Any] = {
            "owner_id": -self.group_id,
            "from_group": from_group,
            "message": text,
        }

        if attachments:
            params["attachments"] = ",".join(attachments)

        if publish_date:
            params["publish_date"] = publish_date


        resp = await self.api_call("wall.post", params)
        post_id = resp.get("post_id")
        if not isinstance(post_id, int) or post_id <= 0:
            raise RuntimeError("VK не подтвердил создание записи")
        logger.info(f"Запись успешно опубликована на стене VK: post_id={post_id}")
        return post_id

    async def edit_post(self, post_id: int, text: str, attachments: list[str]) -> None:
        """Обновить запись, сохранив переданные вложения."""
        await self.api_call("wall.edit", {"owner_id": -self.group_id,
                                          "post_id": post_id, "message": text,
                                          "attachments": ",".join(attachments)}, token=self.user_token)

    async def post_has_photo(self, post_id: int, attachment: str) -> bool:
        """Read the actual wall attachment, using the administrator user token."""
        if not self.user_token:
            raise ValueError("Для проверки вложения нужен VK_USER_TOKEN")
        result = await self.api_call(
            "wall.getById", {"posts": f"-{self.group_id}_{post_id}"}, token=self.user_token,
        )
        posts = result if isinstance(result, list) else result.get("items", [])
        parts = attachment.removeprefix("photo").split("_")
        owner_id, photo_id = int(parts[0]), int(parts[1])
        return any(
            post.get("id") == post_id and post.get("owner_id") == -self.group_id
            and any(a.get("type") == "photo" and a.get("photo", {}).get("owner_id") == owner_id
                    and a.get("photo", {}).get("id") == photo_id for a in post.get("attachments", []))
            for post in posts
        )

    async def add_comment(self, post_id: int, text: str) -> int:
        """Добавляет комментарий к посту от имени сообщества (например, ссылку на сайт)."""
        resp = await self.api_call(
            "wall.createComment",
            {
                "owner_id": -self.group_id,
                "post_id": post_id,
                "from_group": 1,
                "message": text,
            },
        )
        comment_id = resp.get("comment_id")
        logger.info(f"Комментарий успешно оставлен к посту {post_id}: comment_id={comment_id}")
        return comment_id
