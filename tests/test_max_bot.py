"""Тесты функционала бота КиноЖдун в MAX Messenger."""

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import unittest

from bot.db.engine import create_db_engine, get_session_factory, init_db
from bot.db.models import TrackedItem, User
from bot.db.repositories import Repository
from max_bot.client import MaxBotAPIError, MaxBotClient
from max_bot.config import MaxBotSettings
from max_bot.dispatcher import MaxBotDispatcher
from max_bot.handlers import MaxBotHandlers
from max_bot.keyboards import (
    confirm_remove_keyboard,
    item_details_keyboard,
    main_menu_keyboard,
    preview_item_keyboard,
    search_results_keyboard,
    track_success_keyboard,
    user_items_keyboard,
)
from max_bot.state import (
    STATE_DATE_INPUT,
    STATE_SEARCH_INPUT,
    StateManager,
)


class TestMaxBotClient(unittest.IsolatedAsyncioTestCase):
    """Тестирование HTTP-клиента MAX Bot API."""

    def setUp(self):
        self.token = "test_token_123"
        self.client = MaxBotClient(token=self.token)

    async def asyncTearDown(self):
        await self.client.close()

    async def test_send_message_payload(self):
        """Проверка формирования payload при отправке сообщения."""
        self.client._request = AsyncMock(return_value={"message": {"body": {"mid": "123"}}})

        res = await self.client.send_message(
            chat_id=1001,
            text="<b>Привет!</b>",
            format="html",
            attachments=[{"type": "inline_keyboard", "payload": {"buttons": []}}],
            disable_link_preview=True,
        )

        self.client._request.assert_awaited_once_with(
            "POST",
            "/messages",
            params={"disable_link_preview": True, "chat_id": 1001},
            json_data={
                "text": "<b>Привет!</b>",
                "format": "html",
                "notify": True,
                "attachments": [{"type": "inline_keyboard", "payload": {"buttons": []}}],
            },
        )
        self.assertEqual(res["message"]["body"]["mid"], "123")

    async def test_edit_message_payload(self):
        """Проверка формирования payload при редактировании сообщения."""
        self.client._request = AsyncMock(return_value={"message": {"body": {"mid": "123"}}})

        await self.client.edit_message(
            message_id="mid_999",
            text="Обновлённый текст",
            format="html",
        )

        self.client._request.assert_awaited_once_with(
            "PUT",
            "/messages",
            params={"message_id": "mid_999"},
            json_data={
                "text": "Обновлённый текст",
                "format": "html",
            },
        )

    async def test_answer_callback_payload(self):
        """Проверка ответа на нажатие кнопки."""
        self.client._request = AsyncMock(return_value={"success": True})

        await self.client.answer_callback(
            callback_id="cb_42",
            notification="Готово!",
        )

        self.client._request.assert_awaited_once_with(
            "POST",
            "/answers",
            params={"callback_id": "cb_42"},
            json_data={"notification": "Готово!"},
        )


class TestMaxBotKeyboards(unittest.TestCase):
    """Тестирование клавиатур для MAX Messenger."""

    def test_main_menu_keyboard(self):
        kb = main_menu_keyboard()
        self.assertEqual(len(kb), 1)
        self.assertEqual(kb[0]["type"], "inline_keyboard")
        buttons = kb[0]["payload"]["buttons"]
        self.assertEqual(len(buttons), 3)  # 3 ряда кнопок
        all_payloads = [btn["payload"] for row in buttons for btn in row]
        self.assertIn("menu:search", all_payloads)
        self.assertIn("menu:list", all_payloads)
        self.assertIn("menu:status", all_payloads)
        self.assertIn("menu:setdate", all_payloads)
        self.assertIn("menu:remove", all_payloads)
        self.assertIn("menu:help", all_payloads)

    def test_search_results_keyboard(self):
        results = [
            {"media_type": "movie", "title": "Дюна", "release_date": "2021-09-15", "id": 438631},
            {"media_type": "tv", "name": "Пацаны", "first_air_date": "2019-07-26", "id": 76479},
        ]
        kb = search_results_keyboard(results)
        buttons = kb[0]["payload"]["buttons"]
        self.assertEqual(len(buttons), 3)  # 2 результата + 1 кнопка отмены
        self.assertEqual(buttons[0][0]["payload"], "preview:movie:438631")
        self.assertEqual(buttons[1][0]["payload"], "preview:tv:76479")
        self.assertEqual(buttons[2][0]["payload"], "cancel_search")

    def test_preview_item_keyboard_untracked(self):
        kb = preview_item_keyboard("movie", 438631, is_already_tracked=False)
        buttons = kb[0]["payload"]["buttons"]
        all_payloads = [btn["payload"] for row in buttons for btn in row if "payload" in btn]
        self.assertIn("confirm_track:movie:438631", all_payloads)
        self.assertIn("back_to_search", all_payloads)

    def test_preview_item_keyboard_already_tracked(self):
        kb = preview_item_keyboard("tv", 76479, is_already_tracked=True, tracked_item_id=10)
        buttons = kb[0]["payload"]["buttons"]
        all_payloads = [btn["payload"] for row in buttons for btn in row if "payload" in btn]
        self.assertIn("already_tracked", all_payloads)
        self.assertIn("remove:10", all_payloads)


class TestMaxBotStateManager(unittest.TestCase):
    """Тестирование FSM StateManager."""

    def test_state_flow(self):
        sm = StateManager()
        self.assertIsNone(sm.get_user_state(123))

        sm.set_state(123, STATE_DATE_INPUT, item_id=45)
        self.assertEqual(sm.get_user_state(123), STATE_DATE_INPUT)
        self.assertEqual(sm.get_data(123)["item_id"], 45)

        sm.update_data(123, last_search={"query": "test"})
        self.assertEqual(sm.get_data(123)["last_search"]["query"], "test")

        sm.clear_state(123)
        self.assertIsNone(sm.get_user_state(123))
        # last_search сохраняется даже после сброса состояния ввода
        self.assertEqual(sm.get_data(123)["last_search"]["query"], "test")


class TestMaxBotHandlersFlow(unittest.IsolatedAsyncioTestCase):
    """Интеграционное тестирование обработчиков с базой данных в памяти."""

    async def asyncSetUp(self):
        self.engine = create_db_engine("sqlite+aiosqlite:///:memory:")
        await init_db(self.engine)
        self.session_factory = get_session_factory(self.engine)

        self.client = MagicMock(spec=MaxBotClient)
        self.client.send_message = AsyncMock(return_value={"message": {"body": {"mid": "1"}}})
        self.client.answer_callback = AsyncMock(return_value={"success": True})

        self.tmdb = MagicMock()
        self.tmdb.search_multi = AsyncMock()
        self.tmdb.get_movie_details = AsyncMock()
        self.tmdb.get_tv_details = AsyncMock()

        self.settings = MaxBotSettings(
            MAX_BOT_TOKEN="mock_token",
            TMDB_API_KEY="mock_key",
            MAX_DATABASE_URL="sqlite+aiosqlite:///:memory:",
            MAX_ITEMS_PER_USER=10,
        )
        self.state_manager = StateManager()

        self.handlers = MaxBotHandlers(
            client=self.client,
            session_factory=self.session_factory,
            tmdb=self.tmdb,
            settings=self.settings,
            state_manager=self.state_manager,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_start_creates_user_and_sends_menu(self):
        """Проверка /start: создание пользователя в БД и показ приветствия."""
        await self.handlers.handle_start(
            user_id=555,
            chat_id=1005,
            first_name="Алексей",
            username="alex",
        )

        # Проверяем, что пользователь создан в БД
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=555)
            self.assertEqual(items, [])

        self.client.send_message.assert_awaited_once()
        call_kwargs = self.client.send_message.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], 1005)
        self.assertIn("Алексей", call_kwargs["text"])
        self.assertIsNotNone(call_kwargs["attachments"])

    async def test_start_with_deep_link_opens_preview(self):
        """Проверка /start с параметром c_movie_157336: сразу открывает карточку фильма."""
        self.tmdb.get_movie_details.return_value = {
            "title": "Интерстеллар",
            "original_title": "Interstellar",
            "release_date": "2014-11-05",
            "poster_path": None,
            "tmdb_url": "https://www.themoviedb.org/movie/157336",
        }
        await self.handlers.handle_start(
            user_id=555,
            chat_id=1005,
            first_name="Алексей",
            username="alex",
            payload="c_movie_157336",
        )
        self.client.send_message.assert_awaited_once()
        call_kwargs = self.client.send_message.call_args.kwargs
        self.assertEqual(call_kwargs["chat_id"], 1005)
        self.assertIn("Интерстеллар", call_kwargs["text"])

    async def test_confirm_track_movie(self):
        """Проверка добавления фильма в отслеживание."""
        self.tmdb.get_movie_details.return_value = {
            "title": "Интерстеллар",
            "original_title": "Interstellar",
            "release_date": "2014-11-05",
            "poster_path": "/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
            "tmdb_url": "https://www.themoviedb.org/movie/157336",
        }

        # Сначала регистрируем пользователя
        await self.handlers.handle_start(555, 1005, "Алексей", "alex")

        # Добавляем в отслеживание
        await self.handlers.handle_confirm_track(555, 1005, "movie", 157336)

        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=555)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].title, "Интерстеллар")
            self.assertEqual(items[0].tmdb_id, 157336)

        # Повторное добавление тайтла должно вернуть предупреждение о дубликате
        self.client.send_message.reset_mock()
        await self.handlers.handle_confirm_track(555, 1005, "movie", 157336)
        call_kwargs = self.client.send_message.call_args.kwargs
        self.assertIn("уже находится в вашем списке", call_kwargs["text"])

    async def test_list_and_remove(self):
        """Проверка просмотра списка ожидания и удаления проекта."""
        self.tmdb.get_movie_details.return_value = {
            "title": "Дюна",
            "release_date": "2021-09-15",
            "tmdb_url": "https://www.themoviedb.org/movie/438631",
        }
        await self.handlers.handle_start(555, 1005, "Алексей", "alex")
        await self.handlers.handle_confirm_track(555, 1005, "movie", 438631)

        # Просмотр списка
        self.client.send_message.reset_mock()
        await self.handlers.handle_list(555, 1005)
        call_kwargs = self.client.send_message.call_args.kwargs
        self.assertIn("Дюна", call_kwargs["text"])

        # Получаем ID добавленного тайтла
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=555)
            item_id = items[0].id

        # Удаление тайтла
        self.client.send_message.reset_mock()
        await self.handlers.handle_confirm_remove(555, 1005, item_id)
        call_kwargs = self.client.send_message.call_args.kwargs
        self.assertIn("удалён из вашего списка", call_kwargs["text"])

        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=555)
            self.assertEqual(len(items), 0)

    async def test_set_custom_date(self):
        """Проверка ручной установки даты премьеры."""
        self.tmdb.get_movie_details.return_value = {
            "title": "Аватар 3",
            "tmdb_url": "https://www.themoviedb.org/movie/83533",
        }
        await self.handlers.handle_start(555, 1005, "Алексей", "alex")
        await self.handlers.handle_confirm_track(555, 1005, "movie", 83533)

        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=555)
            item_id = items[0].id

        # Начинаем процесс установки даты
        await self.handlers.handle_setdate_prompt(555, 1005, item_id)
        self.assertEqual(self.state_manager.get_user_state(555), STATE_DATE_INPUT)

        # Вводим корректную дату
        await self.handlers.handle_date_input(555, 1005, "19.12.2025")
        self.assertIsNone(self.state_manager.get_user_state(555))

        async with self.session_factory() as session:
            repo = Repository(session)
            item = await repo.get_tracked_item(item_id)
            self.assertEqual(item.custom_date, datetime.date(2025, 12, 19))


class TestMaxBotDispatcher(unittest.IsolatedAsyncioTestCase):
    """Тестирование диспетчера событий MAX."""

    async def test_dispatch_bot_started(self):
        handlers = MagicMock(spec=MaxBotHandlers)
        handlers.handle_start = AsyncMock()
        dispatcher = MaxBotDispatcher(handlers)

        update = {
            "update_type": "bot_started",
            "chat_id": 999,
            "user": {"user_id": 123, "first_name": "Иван", "username": "ivan"},
            "payload": "start_test",
        }
        await dispatcher.process_update(update)

        handlers.handle_start.assert_awaited_once_with(
            user_id=123,
            chat_id=999,
            first_name="Иван",
            username="ivan",
            payload="start_test",
        )

    async def test_dispatch_message_created(self):
        handlers = MagicMock(spec=MaxBotHandlers)
        handlers.dispatch_message = AsyncMock()
        dispatcher = MaxBotDispatcher(handlers)

        update = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 123, "first_name": "Иван", "username": "ivan", "is_bot": False},
                "recipient": {"chat_id": 999},
                "body": {"text": "Дюна"},
            },
        }
        await dispatcher.process_update(update)

        handlers.dispatch_message.assert_awaited_once_with(
            user_id=123,
            chat_id=999,
            first_name="Иван",
            username="ivan",
            text="Дюна",
        )

    async def test_dispatch_callback(self):
        handlers = MagicMock(spec=MaxBotHandlers)
        handlers.dispatch_callback = AsyncMock()
        dispatcher = MaxBotDispatcher(handlers)

        update = {
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb_001",
                "payload": "menu:list",
                "user": {"user_id": 123},
            },
            "message": {
                "recipient": {"chat_id": 999},
            },
        }
        await dispatcher.process_update(update)

        handlers.dispatch_callback.assert_awaited_once_with(
            callback_id="cb_001",
            user_id=123,
            chat_id=999,
            payload="menu:list",
        )


if __name__ == "__main__":
    unittest.main()
