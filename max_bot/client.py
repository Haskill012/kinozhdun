"""Асинхронный HTTP-клиент для взаимодействия с Bot API платформы MAX (max.ru)."""

import asyncio
import logging
import ssl
from pathlib import Path
from typing import Any, Optional
import aiohttp

logger = logging.getLogger(__name__)


class MaxBotAPIError(Exception):
    """Исключение при ошибках API MAX."""

    def __init__(self, status: int, message: str, code: str | None = None):
        self.status = status
        self.message = message
        self.code = code
        super().__init__(f"MAX API Error {status} [{code}]: {message}")


class MaxBotClient:
    """Клиент для работы с HTTPS API мессенджера Макс."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://platform-api2.max.ru",
        session: Optional[aiohttp.ClientSession] = None,
    ):
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None
        self.bot_info: dict[str, Any] | None = None
        self._image_cache: dict[str, str] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            ssl_ctx = ssl.create_default_context()
            cert_path = Path(__file__).parent / "certs" / "russian_trusted_root_ca.cer"
            if cert_path.exists():
                cert = cert_path.read_bytes()
                pem = cert.decode() if cert.startswith(b"-----") else ssl.DER_cert_to_PEM_cert(cert)
                ssl_ctx.load_verify_locations(cadata=pem)
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            timeout = aiohttp.ClientTimeout(total=45, connect=10)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    "User-Agent": "KinoZhdunMaxBot/1.0",
                },
            )
            self._owns_session = True
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=timeout_seconds) if timeout_seconds else None

        # Очищаем None параметры и приводим boolean к строкам для yarl/aiohttp
        clean_params = None
        if params:
            clean_params = {}
            for k, v in params.items():
                if v is None:
                    continue
                if isinstance(v, bool):
                    clean_params[k] = "true" if v else "false"
                else:
                    clean_params[k] = str(v)

        try:
            async with session.request(
                method=method,
                url=url,
                params=clean_params,
                json=json_data,
                headers={"Authorization": self.token},
                timeout=timeout,
            ) as response:
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    data = await response.json()
                else:
                    text_resp = await response.text()
                    try:
                        import json
                        data = json.loads(text_resp)
                    except Exception:
                        data = {"raw": text_resp}

                if response.status >= 400:
                    err_code = data.get("code") if isinstance(data, dict) else None
                    err_msg = data.get("message") if isinstance(data, dict) else str(data)
                    logger.warning(
                        "MAX API %s %s вернул статус %d: %s",
                        method,
                        path,
                        response.status,
                        err_msg,
                    )
                    raise MaxBotAPIError(response.status, err_msg or "Unknown error", err_code)

                return data
        except asyncio.TimeoutError:
            logger.debug("Таймаут запроса %s %s", method, path)
            raise
        except MaxBotAPIError:
            raise
        except Exception as e:
            logger.error("Сетевая ошибка при запросе к MAX API %s %s: %s", method, path, e)
            raise

    async def get_me(self) -> dict[str, Any]:
        """Получить информацию о текущем боте."""
        data = await self._request("GET", "/me")
        self.bot_info = data
        return data

    async def set_commands(self, commands: list[dict[str, str]]) -> dict[str, Any]:
        """Установить список команд бота."""
        return await self._request(
            "PATCH",
            "/me/commands",
            json_data={"commands": commands},
        )

    async def get_updates(
        self,
        marker: Optional[int] = None,
        limit: int = 100,
        timeout: int = 25,
    ) -> dict[str, Any]:
        """Получить обновления через Long Polling."""
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker is not None:
            params["marker"] = marker

        # Запас по таймауту сокета чуть больше времени long poll
        return await self._request(
            "GET",
            "/updates",
            params=params,
            timeout_seconds=timeout + 10,
        )

    async def send_message(
        self,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        text: str = "",
        format: str = "html",
        attachments: Optional[list[dict[str, Any]]] = None,
        disable_link_preview: bool = True,
    ) -> dict[str, Any]:
        """Отправить сообщение в чат или пользователю."""
        params: dict[str, Any] = {
            "disable_link_preview": disable_link_preview,
        }
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id

        body: dict[str, Any] = {
            "text": text,
            "format": format,
            "notify": True,
        }
        if attachments:
            body["attachments"] = attachments

        return await self._request(
            "POST",
            "/messages",
            params=params,
            json_data=body,
        )

    async def edit_message(
        self,
        message_id: str,
        text: str = "",
        format: str = "html",
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Редактировать существующее сообщение."""
        params = {"message_id": message_id}
        body: dict[str, Any] = {
            "text": text,
            "format": format,
        }
        if attachments is not None:
            body["attachments"] = attachments

        return await self._request(
            "PUT",
            "/messages",
            params=params,
            json_data=body,
        )

    async def delete_message(self, message_id: str) -> dict[str, Any]:
        """Удалить сообщение."""
        return await self._request(
            "DELETE",
            "/messages",
            params={"message_id": message_id},
        )

    async def answer_callback(
        self,
        callback_id: str,
        notification: Optional[str] = None,
        message_text: Optional[str] = None,
        message_format: str = "html",
        message_attachments: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Ответить на нажатие инлайн-кнопки."""
        params = {"callback_id": callback_id}
        body: dict[str, Any] = {}

        if notification:
            body["notification"] = notification

        if message_text is not None:
            msg_body: dict[str, Any] = {
                "text": message_text,
                "format": message_format,
            }
            if message_attachments is not None:
                msg_body["attachments"] = message_attachments
            body["message"] = msg_body

        return await self._request(
            "POST",
            "/answers",
            params=params,
            json_data=body,
        )

    async def upload_image(self, image_bytes: bytes, filename: str = "poster.jpg") -> Optional[str]:
        """Загружает бинарное изображение на сервер MAX и возвращает token."""
        try:
            upload_endpoint = await self._request("POST", "/uploads", params={"type": "image"})
            upload_url = upload_endpoint.get("url")
            if not upload_url:
                return None

            session = await self._get_session()
            form = aiohttp.FormData()
            form.add_field("data", image_bytes, filename=filename, content_type="image/jpeg")

            async with session.post(upload_url, data=form) as response:
                if response.status != 200:
                    logger.warning("Ошибка загрузки изображения на %s: статус %d", upload_url, response.status)
                    return None
                data = await response.json()
                # Формат ответа: {"photos": {"0": {"token": "..."}}}
                photos = data.get("photos", {})
                if photos:
                    first_item = next(iter(photos.values()), {})
                    return first_item.get("token")
        except Exception as e:
            logger.warning("Не удалось загрузить изображение в MAX: %s", e)
        return None

    async def upload_image_from_url(self, url: str) -> Optional[str]:
        """Загружает изображение по внешнему URL (с кэшированием токена в памяти)."""
        if not url:
            return None
        if url in self._image_cache:
            return self._image_cache[url]

        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    image_bytes = await resp.read()
                    token = await self.upload_image(image_bytes)
                    if token:
                        self._image_cache[url] = token
                        return token
        except Exception as e:
            logger.debug("Не удалось скачать картинку для MAX из %s: %s", url, e)
        return None

    async def close(self) -> None:
        """Закрыть клиентскую сессию."""
        if self._session and not self._session.closed and self._owns_session:
            await self._session.close()
            await asyncio.sleep(0.05)
