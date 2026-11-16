"""Утилита командной строки для тестирования и управления автопостингом в ВКонтакте.

Примеры использования:
  # Просмотр 3 вариантов случайных постов (без отправки в VK):
  python scripts/vk_tool.py --preview

  # Проверка подключения к VK API:
  python scripts/vk_tool.py --check

  # Тестовая публикация пробного поста в группу:
  python scripts/vk_tool.py --test-post
"""

import argparse
import asyncio
from datetime import date, timedelta
import logging
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))



from bot.config import Settings
from bot.services.vk_client import VKClient
from bot.services.vk_publisher import VKPublisher
from bot.services.vk_spintax import format_vk_post

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vk_tool")


def preview_posts():
    """Демонстрация работы Spintax-генератора с различными стилями и событиями."""
    sample_movies = [
        {
            "title": "Дюна 3: Мессия",
            "media_type": "movie",
            "event_type": "announced",
            "air_date": date.today() + timedelta(days=120),
            "genres": ["фантастика", "приключения"],
            "network": "Warner Bros.",
            "overview": "Пол Атрейдес правит галактикой в качестве императора, сталкиваясь с заговорами и последствиями священной войны.",
            "item_id": 12345,
        },
        {
            "title": "Очень странные дела",
            "media_type": "tv",
            "event_type": "renewed",
            "season_number": 5,
            "air_date": date.today() + timedelta(days=45),
            "genres": ["фантастика", "ужасы", "детектив"],
            "network": "Netflix",
            "overview": "Финальный сезон легендарной саги об изнанке и героях Хоукинса.",
            "item_id": 66732,
        },
        {
            "title": "Бэтмен: Часть 2",
            "media_type": "movie",
            "event_type": "filming_started",
            "air_date": date.today() + timedelta(days=300),
            "genres": ["боевик", "криминал", "детектив"],
            "network": "DC Studios",
            "overview": "Тёмный рыцарь Готэма продолжает противостоять преступному синдикату города.",
            "item_id": 414906,
        },
    ]

    print("=" * 60)
    print("ДЕМОНСТРАЦИЯ ГЕНЕРАТОРА СПИНТАКС-ПОСТОВ ДЛЯ ВК (БЕЗ AI)")
    print("=" * 60)

    for idx, movie in enumerate(sample_movies, 1):
        post = format_vk_post(
            title=movie["title"],
            media_type=movie["media_type"],
            event_type=movie["event_type"],
            season_number=movie.get("season_number"),
            air_date=movie["air_date"],
            genres=movie["genres"],
            network=movie["network"],
            overview=movie["overview"],
            item_id=movie["item_id"],
            site_url="https://kinojdun.ru",
        )

        print(f"\n[ОБРАЗЕЦ #{idx}: {movie['title']}]")
        print("-" * 40)
        print(post["text"])
        print("-" * 40)
        print(f"📊 Опрос: {post['poll']['question']}")
        print(f"   Варианты: {', '.join(post['poll']['answers'])}")
        print(f"🔗 Ссылка в сниппете: {post['target_url']}")
        print("=" * 60)


async def check_connection(settings: Settings):
    """Проверка доступности VK API и прав токена."""
    if not settings.VK_ACCESS_TOKEN or not settings.VK_GROUP_ID:
        print("❌ ОШИБКА: VK_ACCESS_TOKEN или VK_GROUP_ID не заданы в .env")
        print("Укажите их в .env файле, чтобы настроить связь с ВКонтакте.")
        return False

    client = VKClient(
        access_token=settings.VK_ACCESS_TOKEN,
        group_id=settings.VK_GROUP_ID,
        user_token=settings.VK_USER_TOKEN,
    )
    try:
        # Проверяем получение информации о группе
        res = await client.api_call("groups.getById", {"group_id": settings.VK_GROUP_ID})
        groups = res if isinstance(res, list) else res.get("groups", [])
        group_info = groups[0] if groups else {}
        print(f"✅ Успешное подключение к VK API!")
        print(f"   Сообщество: {group_info.get('name', 'ID ' + str(settings.VK_GROUP_ID))}")
        print(f"   ID: {settings.VK_GROUP_ID}")
        print(f"   Статус: Токен сообщества действителен.")
        if settings.VK_ATTACHMENT_MODE in ("text", "link"):
            print(f"   Режим публикации: {settings.VK_ATTACHMENT_MODE} (токен сообщества достаточен).")
        elif settings.VK_ATTACHMENT_MODE == "community_photo":
            print("   Режим community_photo отключён: фото из сообщений не отображается на стене.")
            return False
        elif settings.VK_USER_TOKEN:
            await client.api_call("photos.getWallUploadServer", {"group_id": client.group_id}, token=settings.VK_USER_TOKEN)
            print("   Загрузка фото: права проверены.")
        else:
            print("   Для фото нужен VK_USER_TOKEN — пользовательский токен администратора.")
            return False
        return True
    except Exception as e:
        print(f"❌ Ошибка подключения к VK API: {e}")
        return False
    finally:
        await client.close()


async def test_live_post(settings: Settings):
    """Публикация реального тестового поста в группу."""
    if not await check_connection(settings):
        return

    client = VKClient(
        access_token=settings.VK_ACCESS_TOKEN,
        group_id=settings.VK_GROUP_ID,
        user_token=settings.VK_USER_TOKEN,
    )

    try:
        post = format_vk_post(
            title="Тестовый анонс КиноЖдуна",
            media_type="movie",
            event_type="catalog_feature",
            air_date=date.today() + timedelta(days=30),
            genres=["фантастика"],
            network="КиноЖдун",
            overview="Это тестовая автоматическая публикация сервиса «КиноЖдун». Проверяем вариативность текста и интерактив.",
            site_url=settings.SITE_BASE_URL,
            link_in_comment=False,
            create_poll=settings.VK_CREATE_POLL,
        )

        poster_path = Path(__file__).resolve().parents[1] / "avatar.jpg"
        attachments = []
        if settings.VK_ATTACHMENT_MODE == "photo":
            attachments.insert(0, await client.upload_wall_photo(poster_path.read_bytes()))
        elif settings.VK_ATTACHMENT_MODE == "community_photo":
            attachments.append(await client.upload_community_photo(poster_path.read_bytes()))
        # for text mode, attachments remains empty
        if settings.VK_CREATE_POLL and settings.VK_ATTACHMENT_MODE == "photo":
            try:
                poll_attach = await client.create_poll(
                    post["poll"]["question"],
                    post["poll"]["answers"],
                )
                attachments.append(poll_attach)
            except Exception as e:
                print(f"⚠️ Предупреждение: не удалось создать опрос ({e})")

        post_id = await client.post_to_wall(
            text=post["text"],
            attachments=attachments if attachments else None,
        )
        print(f"🎉 Тестовый пост успешно опубликован на стене! Post ID: {post_id}")
    except Exception as e:
        print(f"❌ Не удалось опубликовать пост: {e}")
    finally:
        await client.close()


async def publish_movie_from_catalog(settings: Settings, index: int = 0):
    """Публикация реального фильма из каталога сайта КиноЖдун с постером."""
    import json
    seed_file = Path(__file__).parent.parent / "website" / "catalog_seed.json"
    if not seed_file.exists():
        print("Файл каталога не найден")
        return

    with open(seed_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    titles = data.get("titles", [])
    if not titles or index < 0 or index >= len(titles):
        print("Нет доступных фильмов в каталоге")
        return

    item = titles[index]
    print(f"🎬 Публикация фильма из каталога: «{item['title']}»...")

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from bot.db.models import Base
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    publisher = VKPublisher(session_factory=session_factory, settings=settings)
    try:
        release_d = None
        if item.get("release_date"):
            try:
                release_d = date.fromisoformat(item["release_date"])
            except Exception:
                pass

        post_id = await publisher.publish_event(
            title=item["title"],
            media_type=item.get("media_type", "movie"),
            event_type="announced" if release_d and release_d >= date.today() else "catalog_feature",
            tmdb_id=item.get("id"),
            season_number=item.get("season"),
            air_date=release_d,
            genres=item.get("genres", []),
            overview=item.get("overview"),
            poster_path=(item.get("image") or item.get("poster")) if settings.VK_ATTACHMENT_MODE == "community_photo" else (item.get("poster") or item.get("image")),
            item_id=item.get("id"),
            force=False,
        )
        if post_id:
            print(f"🎉 Фильм «{item['title']}» успешно опубликован на стене VK! Post ID: {post_id}")
            print(f"🔗 Ссылка на запись: https://vk.ru/club{settings.VK_GROUP_ID}?w=wall-{settings.VK_GROUP_ID}_{post_id}")
        else:
            print("❌ Не удалось опубликовать фильм")
    finally:
        await publisher.close()
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="VK Autoposting Tool for KinoZhdun")
    parser.add_argument("--preview", action="store_true", help="Показать примеры сгенерированных постов")
    parser.add_argument("--check", action="store_true", help="Проверить подключение к VK API")
    parser.add_argument("--test-post", action="store_true", help="Опубликовать тестовый пост в VK")
    parser.add_argument("--publish-movie", type=int, nargs="?", const=0, default=None, help="Опубликовать фильм из каталога по индексу (по умолчанию 0)")

    args = parser.parse_args()

    if args.preview or (len(sys.argv) == 1 and args.publish_movie is None):
        preview_posts()
        return

    try:
        settings = Settings.from_env()
    except Exception as e:
        print(f"Ошибка загрузки конфигурации: {e}")
        return

    if args.check:
        asyncio.run(check_connection(settings))
    elif args.test_post:
        asyncio.run(test_live_post(settings))
    elif args.publish_movie is not None:
        asyncio.run(publish_movie_from_catalog(settings, index=args.publish_movie))


if __name__ == "__main__":
    main()
