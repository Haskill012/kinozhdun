"""Тесты раздела «Мой Кинождун» и механизма расшаривания списка ожидания."""

import json
import unittest
import asyncio
from datetime import date
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.db.models import Base
from bot.db.repositories import Repository


class TestSharedWatchlist(unittest.IsolatedAsyncioTestCase):
    """Тестирование снапшотов, изоляции данных и пакетного отслеживания."""

    async def asyncSetUp(self):
        """Создание тестовой БД в памяти для изоляции тестов."""
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    async def asyncTearDown(self):
        """Очистка ресурсов."""
        await self.engine.dispose()

    async def test_create_and_read_shared_watchlist(self):
        """Проверка создания снапшота и его чтения по токену."""
        async with self.session_factory() as session:
            repo = Repository(session)
            owner = await repo.get_or_create_user(
                telegram_id=111111,
                username="owner_user",
                first_name="Alice",
            )
            # Добавляем элементы владельцу
            item1 = await repo.add_tracked_item(
                user_id=owner.id,
                tmdb_id=82856,
                media_type="tv",
                title="Фоллаут",
                original_title="Fallout",
                poster_path="/poster1.jpg",
                last_known_season=2,
                last_known_air_date=date(2024, 4, 10),
                next_air_date=date(2027, 3, 15),
                tmdb_url="https://tmdb.org/tv/82856",
                network="Prime Video",
            )
            item2 = await repo.add_tracked_item(
                user_id=owner.id,
                tmdb_id=100088,
                media_type="tv",
                title="Одни из нас",
                original_title="The Last of Us",
                poster_path="/poster2.jpg",
                last_known_season=1,
                last_known_air_date=date(2023, 1, 15),
                next_air_date=date(2025, 4, 1),
                tmdb_url="https://tmdb.org/tv/100088",
                network="HBO",
            )

            # Создаём снапшот
            items = [item1, item2]
            shared = await repo.create_shared_watchlist(owner.id, items, title="Мой Кинождун")
            await session.commit()
            token = shared.token

        # Читаем снапшот другим запросом
        async with self.session_factory() as session:
            repo = Repository(session)
            found = await repo.get_shared_watchlist_by_token(token)
            self.assertIsNotNone(found)
            self.assertEqual(found.token, token)
            self.assertEqual(found.title, "Мой Кинождун")
            self.assertEqual(found.views_count, 0)

            # Проверяем JSON-снапшот
            data = json.loads(found.items_snapshot)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["title"], "Фоллаут")
            self.assertEqual(data[0]["network"], "Prime Video")
            self.assertEqual(data[1]["title"], "Одни из нас")

            # Проверяем, что в снапшоте НЕТ приватных данных владельца (telegram_id, username)
            self.assertNotIn("telegram_id", str(data))
            self.assertNotIn("owner_user", str(data))

    async def test_snapshot_immutability(self):
        """Проверка неизменяемости снапшота: удаление тайтла у владельца не ломает расшаренный список."""
        async with self.session_factory() as session:
            repo = Repository(session)
            owner = await repo.get_or_create_user(222222, "bob", "Bob")
            item = await repo.add_tracked_item(
                user_id=owner.id,
                tmdb_id=550,
                media_type="movie",
                title="Бойцовский клуб",
                original_title="Fight Club",
                poster_path=None,
                last_known_season=None,
                last_known_air_date=None,
                next_air_date=None,
                tmdb_url="https://tmdb.org/movie/550",
            )
            shared = await repo.create_shared_watchlist(owner.id, [item])
            await session.commit()
            token = shared.token
            item_id = item.id

        # Владелец удаляет тайтл из своего списка
        async with self.session_factory() as session:
            repo = Repository(session)
            await repo.remove_tracked_item(item_id, telegram_id=222222)
            await session.commit()

        # Снапшот по-прежнему содержит тайтл
        async with self.session_factory() as session:
            repo = Repository(session)
            found = await repo.get_shared_watchlist_by_token(token)
            self.assertIsNotNone(found)
            data = json.loads(found.items_snapshot)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["title"], "Бойцовский клуб")

    async def test_batch_add_tracked_items(self):
        """Проверка пакетного добавления тайтлов получателем из снапшота."""
        items_data = [
            {"media_type": "tv", "tmdb_id": 1, "title": "Сериал 1", "network": "Netflix"},
            {"media_type": "tv", "tmdb_id": 2, "title": "Сериал 2", "network": "HBO"},
            {"media_type": "movie", "tmdb_id": 3, "title": "Фильм 1"},
        ]

        async with self.session_factory() as session:
            repo = Repository(session)
            recipient = await repo.get_or_create_user(333333, "recipient", "Charlie")

            # Добавляем сначала Сериал 1 вручную
            await repo.add_tracked_item(
                user_id=recipient.id,
                tmdb_id=1,
                media_type="tv",
                title="Сериал 1",
                original_title=None,
                poster_path=None,
                last_known_season=None,
                last_known_air_date=None,
                next_air_date=None,
                tmdb_url="",
            )
            await session.commit()

            # Пакетно добавляем все 3 элемента — должен добавиться только 2 и 3
            added_count, added_titles = await repo.batch_add_tracked_items(
                user_id=recipient.id,
                items_data=items_data,
                max_items=10,
            )
            await session.commit()

            self.assertEqual(added_count, 2)
            self.assertIn("Сериал 2", added_titles)
            self.assertIn("Фильм 1", added_titles)

            # Проверяем общее количество у пользователя
            user_items = await repo.get_user_items(333333)
            self.assertEqual(len(user_items), 3)

    async def test_batch_add_respects_limit(self):
        """Проверка соблюдения максимального лимита при пакетном добавлении."""
        items_data = [
            {"media_type": "movie", "tmdb_id": i, "title": f"Фильм {i}"}
            for i in range(1, 10)
        ]

        async with self.session_factory() as session:
            repo = Repository(session)
            user = await repo.get_or_create_user(444444, "limiter", "David")

            # Лимит всего 3 элемента
            added_count, added_titles = await repo.batch_add_tracked_items(
                user_id=user.id,
                items_data=items_data,
                max_items=3,
            )
            await session.commit()

            self.assertEqual(added_count, 3)
            self.assertEqual(len(added_titles), 3)

            # Повторная попытка пакетного добавления должна добавить 0
            added_again, _ = await repo.batch_add_tracked_items(
                user_id=user.id,
                items_data=items_data,
                max_items=3,
            )
            self.assertEqual(added_again, 0)


if __name__ == "__main__":
    unittest.main()
