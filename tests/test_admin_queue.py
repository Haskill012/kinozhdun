"""Тесты администрирования очереди публикаций Telegram-канала «Кинождун 🍿»."""

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, User as TgUser, Chat
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.config import Settings
from bot.db.models import Base, ChannelPost
from bot.db.repositories import Repository
from bot.handlers.admin import (
    cmd_admin_queue,
    process_admin_publish,
    process_admin_reject,
    process_admin_edited_text,
    cmd_channel_test,
    cmd_channel_stats,
    cmd_channel_digest,
    cmd_channel_weekly,
    cmd_channel_check,
    AdminEditPostState,
)


class TestAdminQueue(unittest.IsolatedAsyncioTestCase):
    """Тестирование интерфейса управления очередью публикаций для администраторов."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        self.admin_id = 111222333
        self.non_admin_id = 999888777

        self.settings = Settings(
            TELEGRAM_BOT_TOKEN="mock_token",
            TMDB_API_KEY="mock_key",
            BOT_USERNAME="kinojdun_bot",
            TELEGRAM_CHANNEL_ID="@kinojdun_test_channel",
            CHANNEL_POSTING_ENABLED=True,
            CHANNEL_AUTO_PUBLISH=False,  # SAFE MODE
            ADMIN_USER_IDS=[self.admin_id],
        )

        self.mock_bot = MagicMock()
        self.mock_bot.session_factory = self.session_factory
        self.mock_bot.settings = self.settings
        self.mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=701))
        self.mock_bot.send_photo = AsyncMock(return_value=MagicMock(message_id=702))
        self.mock_bot.get_me = AsyncMock(return_value=MagicMock(username="kinojdun_bot"))
        self.mock_bot.__getitem__ = lambda s, k: getattr(self.mock_bot, k)

        self.storage = MemoryStorage()

    async def asyncTearDown(self):
        await self.engine.dispose()

    def _create_mock_message(self, user_id: int, text: str = "") -> Message:
        msg = MagicMock(spec=Message)
        msg.from_user = TgUser(id=user_id, is_bot=False, first_name="Admin", username="admin_user")
        msg.chat = Chat(id=user_id, type="private")
        msg.text = text
        msg.caption = None
        msg.bot = self.mock_bot
        msg.answer = AsyncMock()
        msg.reply = AsyncMock()
        return msg

    def _create_mock_callback(self, user_id: int, data: str) -> CallbackQuery:
        cb = MagicMock(spec=CallbackQuery)
        cb.from_user = TgUser(id=user_id, is_bot=False, first_name="Admin", username="admin_user")
        cb.data = data
        cb.bot = self.mock_bot
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()
        cb.message.delete = AsyncMock()
        cb.answer = AsyncMock()
        return cb

    async def test_non_admin_access_blocked(self):
        """Проверка того, что обычные пользователи не имеют доступа к админ-панели."""
        msg = self._create_mock_message(user_id=self.non_admin_id, text="/admin")
        state = FSMContext(storage=self.storage, key=MagicMock())
        await cmd_admin_queue(msg, state)

        # Обычный пользователь не получает ответа и не видит очередь
        msg.answer.assert_not_called()

    async def test_admin_queue_empty_response(self):
        """Проверка ответа команды /queue когда очередь пуста."""
        msg = self._create_mock_message(user_id=self.admin_id, text="/queue")
        state = FSMContext(storage=self.storage, key=MagicMock())
        await cmd_admin_queue(msg, state)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        self.assertIn("Очередь публикаций пуста", text)

    async def test_admin_approves_post(self):
        """Проверка одобрения публикации администратором: пост уходит в канал и получает статус published."""
        # 1. Создаём pending публикацию
        async with self.session_factory() as session:
            repo = Repository(session)
            post = await repo.create_channel_post(
                tmdb_id=82856,
                media_type="tv",
                title="Фоллаут",
                content_hash="hash_test_appr",
                event_type="renewed",
                status="pending",
                post_text="Фоллаут продлен на 3 сезон!",
            )
            await session.commit()
            post_id = post.id

        # 2. Администратор нажимает [✅ Опубликовать]
        cb = self._create_mock_callback(user_id=self.admin_id, data=f"admin_pub:{post_id}")
        await process_admin_publish(cb)

        # Сообщение отправлено в канал
        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        cb.message.edit_text.assert_called_once()
        self.assertIn("успешно отправлена в канал", cb.message.edit_text.call_args[0][0])

        # Статус в БД обновился на published
        async with self.session_factory() as session:
            repo = Repository(session)
            updated_post = await repo.get_channel_post(post_id)
            self.assertEqual(updated_post.status, "published")
            self.assertEqual(updated_post.telegram_message_id, 701)

    async def test_admin_rejects_post(self):
        """Проверка отклонения публикации администратором: статус меняется на rejected."""
        async with self.session_factory() as session:
            repo = Repository(session)
            post = await repo.create_channel_post(
                tmdb_id=123,
                media_type="movie",
                title="Случайный Фильм",
                content_hash="hash_test_rej",
                event_type="status_change",
                status="pending",
                post_text="Текст поста",
            )
            await session.commit()
            post_id = post.id

        cb = self._create_mock_callback(user_id=self.admin_id, data=f"admin_rej:{post_id}")
        await process_admin_reject(cb)

        cb.message.edit_text.assert_called_once()
        self.assertIn("отклонена", cb.message.edit_text.call_args[0][0])

        async with self.session_factory() as session:
            repo = Repository(session)
            updated_post = await repo.get_channel_post(post_id)
            self.assertEqual(updated_post.status, "rejected")

    async def test_admin_edits_post_text(self):
        """Проверка редактирования текста публикации администратором."""
        async with self.session_factory() as session:
            repo = Repository(session)
            post = await repo.create_channel_post(
                tmdb_id=555,
                media_type="movie",
                title="Фильм для правки",
                content_hash="hash_test_edt",
                event_type="date_announced",
                status="pending",
                post_text="Старый текст",
            )
            await session.commit()
            post_id = post.id

        msg = self._create_mock_message(user_id=self.admin_id, text="Новый улучшенный текст публикации!")
        state = FSMContext(storage=self.storage, key=MagicMock())
        await state.update_data(editing_post_id=post_id)

        await process_admin_edited_text(msg, state)

        msg.answer.assert_called_once()
        self.assertIn("успешно обновлён", msg.answer.call_args[0][0])

        async with self.session_factory() as session:
            repo = Repository(session)
            updated = await repo.get_channel_post(post_id)
            self.assertEqual(updated.post_text, "Новый улучшенный текст публикации!")

    async def test_channel_test_command(self):
        """Проверка работы команды /channel_test."""
        msg = self._create_mock_message(user_id=self.admin_id, text="/channel_test")
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)

        await cmd_channel_test(msg)

        self.assertEqual(self.mock_bot.send_message.call_count, 1)
        status_msg.edit_text.assert_called_once()
        self.assertIn("успешно опубликовано", status_msg.edit_text.call_args[0][0])

    async def test_channel_stats_command(self):
        """Проверка отображения аналитики /stats."""
        msg = self._create_mock_message(user_id=self.admin_id, text="/stats")
        await cmd_channel_stats(msg)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        self.assertIn("Аналитика Telegram-канала", text)
        self.assertIn("Опубликовано постов", text)
        self.assertIn("Переходов в бота", text)
        self.assertIn("Конверсия воронки", text)

    async def test_cmd_channel_digest_and_weekly(self):
        """Проверка ручного вызова дайджестов администратором."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_airing_today_tv = AsyncMock(return_value=[])
        mock_tmdb.get_upcoming_movies = AsyncMock(return_value=[])
        self.mock_bot.get = lambda k, default=None: mock_tmdb if k == "tmdb_client" else getattr(self.mock_bot, k, default)

        # 1. Попытка создания без релизов
        msg = self._create_mock_message(user_id=self.admin_id, text="/channel_digest")
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)

        await cmd_channel_digest(msg)
        status_msg.edit_text.assert_called_once()
        self.assertIn("не найдено", status_msg.edit_text.call_args[0][0])

        # 2. Не админ получает предупреждение о правах
        non_admin_msg = self._create_mock_message(user_id=self.non_admin_id, text="/channel_digest")
        non_admin_msg.answer = AsyncMock()
        await cmd_channel_digest(non_admin_msg)
        non_admin_msg.answer.assert_called_once()
        self.assertIn("только администраторам", non_admin_msg.answer.call_args[0][0])

    async def test_cmd_channel_check(self):
        """Проверка ручного вызова проверки обновлений /channel_check."""
        msg = self._create_mock_message(user_id=self.admin_id, text="/channel_check")
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)

        mock_tmdb = MagicMock()
        mock_tmdb.close = AsyncMock()
        self.mock_bot.get = lambda k, default=None: mock_tmdb if k == "tmdb_client" else getattr(self.mock_bot, k, default)

        await cmd_channel_check(msg)
        status_msg.edit_text.assert_called_once()
        self.assertIn("Проверка обновлений завершена", status_msg.edit_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
