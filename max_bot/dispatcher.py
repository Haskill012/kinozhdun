"""Диспетчер входящих обновлений платформы MAX (Long Polling / Webhook)."""

import logging
from typing import Any
from max_bot.handlers import MaxBotHandlers

logger = logging.getLogger(__name__)


class MaxBotDispatcher:
    """Диспетчер для разбора и маршрутизации входящих событий API MAX."""

    def __init__(self, handlers: MaxBotHandlers):
        self.handlers = handlers

    async def process_update(self, update: dict[str, Any]) -> None:
        """Обработка одного объекта Update из MAX API."""
        update_type = update.get("update_type")
        if not update_type:
            return

        try:
            # 1. Событие нажатия пользователем кнопки «Начать» / Start
            if update_type == "bot_started":
                chat_id = update.get("chat_id")
                user = update.get("user", {})
                user_id = user.get("user_id")
                first_name = user.get("first_name")
                username = user.get("username")
                payload = update.get("payload")

                if chat_id and user_id:
                    await self.handlers.handle_start(
                        user_id=user_id,
                        chat_id=chat_id,
                        first_name=first_name,
                        username=username,
                        payload=payload,
                    )
                return

            # 2. Новое входящее сообщение
            if update_type == "message_created":
                message = update.get("message", {})
                sender = message.get("sender") or {}
                if sender.get("is_bot"):
                    return  # Игнорируем сообщения от ботов

                recipient = message.get("recipient") or {}
                chat_id = recipient.get("chat_id")
                user_id = sender.get("user_id")
                first_name = sender.get("first_name")
                username = sender.get("username")
                body = message.get("body") or {}
                text = body.get("text", "")

                if chat_id and user_id and text:
                    await self.handlers.dispatch_message(
                        user_id=user_id,
                        chat_id=chat_id,
                        first_name=first_name,
                        username=username,
                        text=text,
                    )
                return

            # 3. Нажатие на инлайн-кнопку
            if update_type == "message_callback":
                callback = update.get("callback", {})
                callback_id = callback.get("callback_id")
                payload = callback.get("payload", "")
                user = callback.get("user") or {}
                user_id = user.get("user_id")

                message = update.get("message") or {}
                recipient = message.get("recipient") or {}
                chat_id = recipient.get("chat_id")

                if callback_id and user_id and chat_id:
                    await self.handlers.dispatch_callback(
                        callback_id=callback_id,
                        user_id=user_id,
                        chat_id=chat_id,
                        payload=payload,
                    )
                return

        except Exception as e:
            logger.exception("Ошибка обработки события %s: %s", update_type, e)
