"""Интеграционные тесты хендлеров бота для трёх сценариев роста."""

import unittest
from unittest.mock import AsyncMock, MagicMock
from aiogram.filters import CommandObject
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.config import Settings
from bot.db.models import Base
from bot.db.repositories import Repository
from bot.handlers.start import cmd_start


class TestHandlersFlow(unittest.IsolatedAsyncioTestCase):
    """Тестирование полного цикла обработки входящих deep links хендлером cmd_start."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        self.mock_tmdb = MagicMock()
        self.mock_tmdb.get_tv_details = AsyncMock(return_value={
            "id": 82856,
            "title": "Фоллаут",
            "media_type": "tv",
            "overview": "В постапокалиптическом Лос-Анджелесе...",
            "network": "Prime Video",
            "next_episode_to_air": {"air_date": "2027-03-15", "season_number": 2},
        })
        self.mock_tmdb.get_movie_details = AsyncMock(return_value={
            "id": 550,
            "title": "Бойцовский клуб",
            "media_type": "movie",
            "overview": "Сотрудник страховой компании...",
            "release_date": "1999-10-15",
        })

        self.mock_bot = MagicMock()
        self.mock_bot.__getitem__ = lambda b, k: {
            "session_factory": self.session_factory,
            "tmdb_client": self.mock_tmdb,
            "settings": Settings(
                TELEGRAM_BOT_TOKEN="token",
                TMDB_API_KEY="key",
                BOT_USERNAME="kinojdun_bot",
            ),
        }[k]

    async def asyncTearDown(self):
        await self.engine.dispose()

    def _create_mock_message(self, user_id=12345, username="test_user"):
        msg = MagicMock()
        msg.bot = self.mock_bot
        msg.from_user = MagicMock(id=user_id, username=username, first_name="Тестер")
        msg.answer = AsyncMock()
        return msg

    async def test_cmd_start_organic(self):
        """Проверка стандартного запуска /start без параметров."""
        msg = self._create_mock_message()
        cmd = CommandObject(prefix="/", command="start", args=None)

        await cmd_start(msg, cmd)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        self.assertIn("КИНОЖДУН", text)
        self.assertIn("Привет, <b>Тестер</b>!", text)

        # Проверяем запись пользователя в БД
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(12345)
            self.assertEqual(len(items), 0)

    async def test_cmd_start_content_share_flow(self):
        """Проверка перехода по ссылке шеринга фильма/сериала: c_tv_82856."""
        msg = self._create_mock_message(user_id=777)
        cmd = CommandObject(prefix="/", command="start", args="c_tv_82856_u111")

        await cmd_start(msg, cmd)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        reply_markup = msg.answer.call_args[1]["reply_markup"]

        # Проверяем текст карточки получателя
        self.assertIn('Тоже ждёшь «<a href="https://kinojdun.ru/title/tv/82856">Фоллаут</a>»?', text)
        self.assertIn("Prime Video", text)

        # Проверяем инлайн-кнопки
        buttons = [b.text for row in reply_markup.inline_keyboard for b in row]
        self.assertIn("🔔 Отслеживать", buttons)
        self.assertIn("🔎 Посмотреть подробнее", buttons)

        # Проверяем фиксацию реферального источника
        async with self.session_factory() as session:
            repo = Repository(session)
            u = await repo.get_or_create_user(777, "test", "Tester")
            self.assertEqual(u.referral_source, "share_content:tv:82856")
            self.assertEqual(u.referrer_id, 111)

    async def test_cmd_start_watchlist_share_flow(self):
        """Проверка перехода по расшаренному списку «Мой Кинождун»: w_<token>."""
        # 1. Создаём список от имени пользователя 100
        async with self.session_factory() as session:
            repo = Repository(session)
            owner = await repo.get_or_create_user(100, "owner", "Owner")
            item = await repo.add_tracked_item(
                user_id=owner.id,
                tmdb_id=82856,
                media_type="tv",
                title="Фоллаут",
                original_title="Fallout",
                poster_path=None,
                last_known_season=2,
                last_known_air_date=None,
                next_air_date=None,
                tmdb_url="",
            )
            shared = await repo.create_shared_watchlist(owner.id, [item], title="Любимые сериалы")
            await session.commit()
            token = shared.token

        # 2. Получатель переходит по ссылке
        msg = self._create_mock_message(user_id=200, username="recipient")
        cmd = CommandObject(prefix="/", command="start", args=f"w_{token}")

        await cmd_start(msg, cmd)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        reply_markup = msg.answer.call_args[1]["reply_markup"]

        self.assertIn("Любимые сериалы", text)
        self.assertIn("Фоллаут", text)

        buttons = [b.text for row in reply_markup.inline_keyboard for b in row]
        self.assertTrue(any("Отслеживать всё" in b for b in buttons))

    async def test_cmd_start_channel_referral_flow(self):
        """Проверка перехода по кнопке из Telegram-канала: ch_<post_id>."""
        # 1. Создаём публикацию канала
        async with self.session_factory() as session:
            repo = Repository(session)
            post = await repo.create_channel_post(
                tmdb_id=82856,
                media_type="tv",
                event_type="announced",
                title="Фоллаут",
                content_hash="hash123",
                network="Prime Video",
                status="published",
            )
            await session.commit()
            post_id = post.id

        # 2. Пользователь переходит из канала в бота
        msg = self._create_mock_message(user_id=300, username="channel_reader")
        cmd = CommandObject(prefix="/", command="start", args=f"ch_{post_id}")

        await cmd_start(msg, cmd)

        msg.answer.assert_called_once()
        text = msg.answer.call_args[0][0]
        reply_markup = msg.answer.call_args[1]["reply_markup"]

        self.assertIn("Новость из Telegram-канала «Кинождун»", text)
        self.assertIn("Фоллаут", text)

        buttons = [b.text for row in reply_markup.inline_keyboard for b in row]
        self.assertTrue(any("🔔 Отслеживать" in b for b in buttons))


if __name__ == "__main__":
    unittest.main()
