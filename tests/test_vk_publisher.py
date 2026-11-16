"""Тесты модуля автопостинга ВКонтакте (Spintax-генератор, VKClient и VKPublisher)."""

import json
import unittest
import random
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from bot.config import Settings
from bot.db.models import Base, VKPost
from bot.db.repositories import Repository
from bot.services.vk_spintax import render_spintax, format_vk_post, clean_synopsis
from bot.services.vk_client import VKClient, VKApiError
from bot.services.vk_publisher import VKPublisher


class TestVKSpintax(unittest.TestCase):
    """Тестирование Spintax-движка и форматирования постов для VK."""

    def test_render_spintax_basic(self):
        text = "{Привет|Здравствуйте|Хей}"
        results = {render_spintax(text) for _ in range(50)}
        self.assertTrue(results.issubset({"Привет", "Здравствуйте", "Хей"}))
        self.assertGreaterEqual(len(results), 2)

    def test_render_spintax_nested(self):
        text = "{Фильм {1|2}|Сериал {3|4}}"
        results = {render_spintax(text) for _ in range(100)}
        expected = {"Фильм 1", "Фильм 2", "Сериал 3", "Сериал 4"}
        self.assertTrue(results.issubset(expected))

    def test_clean_synopsis(self):
        short_text = "Короткий текст о фильме."
        self.assertEqual(clean_synopsis(short_text), short_text)

        long_text = "Слово " * 100
        truncated = clean_synopsis(long_text, max_len=50)
        self.assertLessEqual(len(truncated), 53)
        self.assertTrue(truncated.endswith("..."))

    def test_format_vk_post_structure(self):
        post = format_vk_post(
            title="Интерстеллар 2",
            media_type="movie",
            event_type="announced",
            air_date=date(2027, 5, 20),
            genres=["фантастика", "драма"],
            network="Paramount",
            overview="Команда исследователей отправляется сквозь червоточину в поисках нового дома.",
            site_url="https://kinojdun.ru",
            item_id=9999,
        )

        self.assertIn("Интерстеллар 2", post["text"])
        self.assertIn("https://kinojdun.ru/title/movie/9999", post["text"])
        self.assertIn("poll", post)
        self.assertIn("question", post["poll"])
        self.assertEqual(len(post["poll"]["answers"]), 3)
        self.assertIn("#кино", post["hashtags"])
        self.assertIn("#фантастика", post["hashtags"])

    def test_facts_are_preserved_for_every_template_variant(self):
        for seed in range(20):
            post = format_vk_post(title="Сериал", media_type="tv", season_number=3,
                                  genres=["драма"], network="Платформа", air_date=date(2030, 5, 20),
                                  rng=random.Random(seed), create_poll=False)
            for fact in ("3 сезон", "драма", "Платформа", "20 мая 2030"):
                self.assertIn(fact, post["text"])
            self.assertNotIn("Голосуйте", post["text"])

    def test_past_date_is_not_announced_as_upcoming(self):
        post = format_vk_post(title="Фильм", air_date=date(2000, 1, 1))
        self.assertIn("Уже вышло", post["text"])
        self.assertNotIn("состоится премьера", post["text"])

    def test_no_date_or_synopsis_keeps_clean_paragraphs(self):
        post = format_vk_post(title="Фильм", item_id=123)
        self.assertIn("Дата выхода пока не объявлена", post["text"])
        self.assertNotIn("[DATE_STR]", post["text"])
        self.assertNotIn("\n\n\n", post["text"])


class TestVKClient(unittest.IsolatedAsyncioTestCase):
    """Тестирование методов клиента VK API."""

    async def test_photo_requires_user_token(self):
        client = VKClient("community", 123)
        with self.assertRaisesRegex(ValueError, "VK_USER_TOKEN"):
            await client.upload_wall_photo(b'\xff\xd8\xffposter')

    async def test_photo_upload_and_save_with_user_token(self):
        for payload in (b'\xff\xd8\xffjpeg', b'\x89PNG\r\n\x1a\npng'):
            client = VKClient("community", 123, user_token="user")
            client.api_call = AsyncMock(side_effect=[
                {"upload_url": "https://upload.example/photo"},
                [{"owner_id": -123, "id": 321, "access_key": "key"}],
            ])
            resp = MagicMock()
            resp.json = AsyncMock(return_value={"photo": "[photo]", "server": 10, "hash": "hash"})
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=resp)
            context.__aexit__ = AsyncMock(return_value=None)
            session = MagicMock()
            session.post.return_value = context
            client._get_session = AsyncMock(return_value=session)
            attachment = await client.upload_wall_photo(payload)
            self.assertEqual(attachment, "photo-123_321_key")
            calls = client.api_call.await_args_list
            self.assertEqual([c.args[0] for c in calls], ["photos.getWallUploadServer", "photos.saveWallPhoto"])
            self.assertTrue(all(c.kwargs["token"] == "user" for c in calls))

    async def test_wall_missing_id_is_failure(self):
        client = VKClient("community", 123)
        client.api_call = AsyncMock(return_value={})
        with self.assertRaises(RuntimeError):
            await client.post_to_wall("text")

    async def test_wall_photo_readback_uses_user_and_checks_actual_photo(self):
        client = VKClient('community', 123, user_token='user')
        client.api_call = AsyncMock(return_value={'items':[
            {'id':10,'owner_id':-123,'attachments':[{'type':'photo','photo':{'owner_id':-123,'id':321}}]},
        ]})
        self.assertTrue(await client.post_has_photo(10,'photo-123_321_key'))
        self.assertEqual(client.api_call.await_args.kwargs['token'], 'user')
        self.assertFalse(await client.post_has_photo(10,'photo-123_999_key'))
        client.api_call.return_value = [{'id':10,'owner_id':-123,'attachments':[]}]
        self.assertFalse(await client.post_has_photo(10,'photo-123_321_key'))

    async def test_community_photo_uses_file1_without_user_token_or_message_send(self):
        client = VKClient("community", 123)
        client.api_call = AsyncMock(side_effect=[
            {"upload_url": "https://upload.example/photo"},
            [{"owner_id": -123, "id": 321, "access_key": "key"}],
        ])
        resp = MagicMock()
        resp.json = AsyncMock(return_value={"photo": "[photo]", "server": 10, "hash": "hash"})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=resp)
        context.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post.return_value = context
        client._get_session = AsyncMock(return_value=session)
        with patch('bot.services.vk_client.aiohttp.FormData') as form:
            self.assertEqual(await client.upload_community_photo(b'\xff\xd8\xffjpeg'), 'photo-123_321_key')
            self.assertEqual(form.return_value.add_field.call_args.args[0], 'file1')
        calls = client.api_call.await_args_list
        self.assertEqual([c.args[0] for c in calls], ['photos.getMessagesUploadServer','photos.saveMessagesPhoto'])
        self.assertTrue(all(c.kwargs['token'] == 'community' for c in calls))
        self.assertNotIn('group_id', calls[1].args[1])

    async def test_api_call_success(self):
        client = VKClient(access_token="test_token", group_id=123456)
        mock_response = {"post_id": 789}

        with patch.object(client, "_get_session") as mock_session_getter:
            mock_session = MagicMock()
            mock_post_ctx = MagicMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = AsyncMock(return_value={"response": mock_response})
            mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_session.post.return_value = mock_post_ctx
            mock_session_getter.return_value = mock_session

            res = await client.api_call("wall.post", {"message": "hello"})
            self.assertEqual(res, mock_response)

    async def test_api_call_error(self):
        client = VKClient(access_token="test_token", group_id=123456)

        with patch.object(client, "_get_session") as mock_session_getter:
            mock_session = MagicMock()
            mock_post_ctx = MagicMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = AsyncMock(return_value={"error": {"error_code": 5, "error_msg": "User authorization failed"}})
            mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_session.post.return_value = mock_post_ctx
            mock_session_getter.return_value = mock_session

            with self.assertRaises(VKApiError):
                await client.api_call("wall.post")


class TestVKPublisher(unittest.IsolatedAsyncioTestCase):
    """Тестирование сервиса публикации в VK с интеграцией с БД и дедупликацией."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        self.settings = Settings(
            TELEGRAM_BOT_TOKEN="mock_token",
            TMDB_API_KEY="mock_key",
            VK_ACCESS_TOKEN="mock_vk_token",
            VK_USER_TOKEN="mock_user_token",
            VK_GROUP_ID=11223344,
            VK_POSTING_ENABLED=True,
            VK_AUTO_PUBLISH=True,
            VK_ATTACHMENT_MODE="photo",
            VK_CREATE_POLL=True,
            SITE_BASE_URL="https://kinojdun.ru",
        )

        self.mock_vk_client = MagicMock()
        self.mock_vk_client.post_to_wall = AsyncMock(return_value=101)
        self.mock_vk_client.upload_wall_photo = AsyncMock(return_value="photo-11223344_555")
        self.mock_vk_client.upload_community_photo = AsyncMock(return_value="photo-11223344_556_key")
        self.mock_vk_client.create_poll = AsyncMock(return_value="poll-11223344_666")
        self.mock_vk_client.add_comment = AsyncMock(return_value=777)
        self.mock_vk_client.edit_post = AsyncMock()
        self.mock_vk_client.post_has_photo = AsyncMock(return_value=True)
        self.mock_vk_client.close = AsyncMock()

        self.publisher = VKPublisher(
            session_factory=self.session_factory,
            settings=self.settings,
            vk_client=self.mock_vk_client,
        )
        self.publisher.fetch_poster_bytes = AsyncMock(return_value=b'\xff\xd8\xffposter')

    async def asyncTearDown(self):
        await self.publisher.close()
        await self.engine.dispose()

    async def test_no_photo_does_not_publish_and_can_retry(self):
        self.mock_vk_client.upload_wall_photo.side_effect = ValueError("wrong token")
        args = dict(title="Постер", tmdb_id=456, poster_path="/poster.jpg")
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.mock_vk_client.post_to_wall.assert_not_awaited()
        self.mock_vk_client.upload_wall_photo.side_effect = None
        self.assertEqual(await self.publisher.publish_event(**args), 101)

    async def test_message_storage_is_not_accepted_as_wall_photo(self):
        self.settings.VK_ATTACHMENT_MODE = "community_photo"
        args = dict(title="Карточка", tmdb_id=2734, media_type="tv")
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.mock_vk_client.post_to_wall.assert_not_awaited()

    async def test_missing_wall_user_token_blocks_publication(self):
        self.settings.VK_USER_TOKEN = None
        self.assertIsNone(await self.publisher.publish_event(title='Недостаточно прав',tmdb_id=2734))
        self.mock_vk_client.post_to_wall.assert_not_awaited()

    async def test_silently_dropped_photo_stops_auto_and_does_not_duplicate(self):
        self.mock_vk_client.post_has_photo.return_value = False
        args = dict(title='Фото исчезло', tmdb_id=800)
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.assertFalse(self.settings.VK_AUTO_PUBLISH)
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.assertEqual(self.mock_vk_client.post_to_wall.await_count, 1)
        async with self.session_factory() as session:
            from sqlalchemy import select
            post = (await session.scalars(select(VKPost))).one()
            self.assertEqual((post.vk_post_id, post.status), (101, 'image_missing'))

    async def test_readback_failure_preserves_post_id_without_retry(self):
        self.mock_vk_client.post_has_photo.side_effect = RuntimeError('read unavailable')
        args = dict(title='Проверка недоступна', tmdb_id=801)
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.assertEqual(self.mock_vk_client.post_to_wall.await_count, 1)
        async with self.session_factory() as session:
            from sqlalchemy import select
            post = (await session.scalars(select(VKPost))).one()
            self.assertEqual((post.vk_post_id, post.status), (101, 'verification_pending'))

    async def test_text_mode_without_user_token_or_any_photo_calls(self):
        self.settings.VK_ATTACHMENT_MODE = 'text'
        self.settings.VK_USER_TOKEN = ''
        self.settings.VK_LINK_IN_COMMENT = True
        self.settings.VK_CREATE_POLL = True
        self.assertTrue(self.publisher.is_configured())
        args = dict(title='Текстовый пост', tmdb_id=888, overview='Описание', poster_path='/poster.jpg')
        self.assertEqual(await self.publisher.publish_event(**args), 101)
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.publisher.fetch_poster_bytes.assert_not_awaited()
        self.mock_vk_client.upload_wall_photo.assert_not_awaited()
        self.mock_vk_client.post_has_photo.assert_not_awaited()
        self.mock_vk_client.create_poll.assert_not_awaited()
        self.mock_vk_client.add_comment.assert_not_awaited()
        call = self.mock_vk_client.post_to_wall.await_args.kwargs
        self.assertIsNone(call['attachments'])
        self.assertIn('/title/movie/888', call['text'])
        self.assertTrue(self.settings.VK_AUTO_PUBLISH)
        async with self.session_factory() as session:
            from sqlalchemy import select
            post = (await session.scalars(select(VKPost))).one()
            self.assertEqual(post.status, 'published')

    async def test_link_mode_attaches_page_without_photo_permissions(self):
        self.settings.VK_ATTACHMENT_MODE = 'link'
        self.settings.VK_USER_TOKEN = ''
        self.settings.VK_LINK_IN_COMMENT = True
        self.settings.VK_CREATE_POLL = True
        self.assertTrue(self.publisher.is_configured())
        args = dict(title='Карточка ссылки', tmdb_id=889, media_type='tv', poster_path='/poster.jpg')
        self.assertEqual(await self.publisher.publish_event(**args), 101)
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.publisher.fetch_poster_bytes.assert_not_awaited()
        self.mock_vk_client.upload_wall_photo.assert_not_awaited()
        self.mock_vk_client.post_has_photo.assert_not_awaited()
        self.mock_vk_client.create_poll.assert_not_awaited()
        self.mock_vk_client.add_comment.assert_not_awaited()
        call = self.mock_vk_client.post_to_wall.await_args.kwargs
        self.assertEqual(call['attachments'], ['https://kinojdun.ru/title/tv/889'])
        self.assertIn('/title/tv/889', call['text'])

    async def test_ambiguous_wall_failure_does_not_retry(self):
        self.mock_vk_client.post_to_wall.side_effect = RuntimeError("wall unavailable")
        args = dict(title="Повтор", tmdb_id=457)
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.mock_vk_client.post_to_wall.side_effect = None
        self.assertIsNone(await self.publisher.publish_event(**args))
        self.assertEqual(self.mock_vk_client.post_to_wall.await_count, 1)

    async def test_comment_failure_keeps_link_and_attachments(self):
        self.settings.VK_LINK_IN_COMMENT = True
        self.mock_vk_client.add_comment.side_effect = RuntimeError("comments disabled")
        await self.publisher.publish_event(title="Ссылка", tmdb_id=458)
        call = self.mock_vk_client.edit_post.await_args
        self.assertIn("https://kinojdun.ru/title/movie/458", call.args[1])
        self.assertIn("photo-11223344_555", call.args[2])
        self.assertIsNone(await self.publisher.publish_event(title="Ссылка", tmdb_id=458))
        self.assertEqual(self.mock_vk_client.post_to_wall.await_count, 1)

    async def test_scheduled_post_keeps_link_in_text(self):
        self.settings.VK_LINK_IN_COMMENT = True
        await self.publisher.publish_event(title="Позже", tmdb_id=459, publish_date=1900000000)
        self.assertIn("/title/movie/459", self.mock_vk_client.post_to_wall.await_args.kwargs['text'])
        self.mock_vk_client.add_comment.assert_not_awaited()
        async with self.session_factory() as session:
            from sqlalchemy import select
            post = (await session.scalars(select(VKPost))).one()
            self.assertEqual(post.status, "scheduled")

    async def test_poll_disabled_changes_engagement(self):
        self.settings.VK_CREATE_POLL = False
        await self.publisher.publish_event(title="Без опроса", tmdb_id=460)
        text = self.mock_vk_client.post_to_wall.await_args.kwargs['text']
        self.assertNotIn("Голосуйте", text)
        self.mock_vk_client.create_poll.assert_not_awaited()

    async def test_publish_event_success_and_deduplication(self):
        # 1. Первая публикация должна пройти успешно
        post_id = await self.publisher.publish_event(
            title="Матрица 5",
            media_type="movie",
            event_type="announced",
            tmdb_id=603,
            air_date=date(2027, 10, 15),
            genres=["фантастика"],
            overview="Нео возвращается в новой версии виртуальной реальности.",
        )
        self.assertEqual(post_id, 101)
        self.mock_vk_client.post_to_wall.assert_called_once()

        # Проверяем, что запись появилась в БД
        async with self.session_factory() as session:
            repo = Repository(session)
            from bot.services.channel import generate_event_fingerprint
            h = generate_event_fingerprint(603, "movie", "announced", None, "2027-10-15")
            self.assertTrue(await repo.is_vk_post_exists(h))

        # 2. Повторная публикация того же события должна быть пропущена дедупликацией
        self.mock_vk_client.post_to_wall.reset_mock()
        second_post_id = await self.publisher.publish_event(
            title="Матрица 5",
            media_type="movie",
            event_type="announced",
            tmdb_id=603,
            air_date=date(2027, 10, 15),
            genres=["фантастика"],
            overview="Нео возвращается в новой версии виртуальной реальности.",
        )
        self.assertIsNone(second_post_id)
        self.mock_vk_client.post_to_wall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
