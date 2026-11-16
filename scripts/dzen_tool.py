"""Утилита командной строки для тестирования и управления автопостингом в Дзене.

Примеры использования:
  # Просмотр образцов публикаций и дайджестов для Дзена:
  python scripts/dzen_tool.py --preview

  # Проверка настроек и подключения:
  python scripts/dzen_tool.py --check

  # Тестовая публикация пробного поста:
  python scripts/dzen_tool.py --test-post

  # Публикация карточки фильма по TMDB ID:
  python scripts/dzen_tool.py --publish-movie 12345

  # Просмотр структуры RSS-ленты Дзена:
  python scripts/dzen_tool.py --export-rss
"""

import argparse
import asyncio
from datetime import date, timedelta
import json
import logging
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.config import Settings
from bot.db.engine import create_db_engine, get_session_factory, init_db
from bot.services.dzen_publisher import (
    DzenPublisher,
    format_dzen_post_text,
    format_dzen_daily_digest,
    format_dzen_weekly_digest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dzen_tool")


def preview_posts():
    """Демонстрация форматирования публикаций и дайджестов для канала Дзена."""
    print("=" * 65)
    print("ДЕМОНСТРАЦИЯ ПУБЛИКАЦИЙ ДЛЯ КАНАЛА ДЗЕНА «КИНОЖДУН»")
    print("=" * 65)

    sample_post = format_dzen_post_text(
        title="Дюна: Часть третья",
        media_type="movie",
        event_type="date_announced",
        air_date=date.today() + timedelta(days=240),
        genres=["фантастика", "приключения", "драма"],
        network="Warner Bros. Pictures",
        overview="Продолжение эпической саги Дени Вильнёва по роману Фрэнка Герберта «Мессия Дюны». Пол Атрейдес правит Вселенной, но над Арракисом сгущаются новые тучи заговоров.",
        trailer_url="https://youtube.com/watch?v=sample_trailer",
        tmdb_id=12345,
        site_url="https://kinojdun.ru",
        bot_username="kinojdun_bot",
    )

    print("\n[1. ОБРАЗЕЦ АНОНСА ПРЕМЬЕРЫ ФИЛЬМА ДЛЯ ДЗЕНА]")
    print("-" * 50)
    print(sample_post)
    print("-" * 50)

    sample_series = format_dzen_post_text(
        title="Очень странные дела",
        media_type="tv",
        event_type="renewed",
        season_number=5,
        air_date=date.today() + timedelta(days=90),
        genres=["фантастика", "ужасы", "детектив"],
        network="Netflix",
        overview="Финальный сезон культового фантастического сериала о борьбе подростков из Хоукинса с монстрами Изнанки.",
        tmdb_id=66732,
        site_url="https://kinojdun.ru",
        bot_username="kinojdun_bot",
    )

    print("\n[2. ОБРАЗЕЦ ПРОДЛЕНИЯ СЕРИАЛА ДЛЯ ДЗЕНА]")
    print("-" * 50)
    print(sample_series)
    print("-" * 50)

    sample_daily = format_dzen_daily_digest(
        items=[
            {
                "title": "Дом Дракона",
                "tag": "старт 3 сезона",
                "network": "HBO Max",
                "media_type": "tv",
                "tmdb_id": 94997,
            },
            {
                "title": "Гладиатор 2",
                "tag": "премьера фильма",
                "network": "Paramount Pictures",
                "media_type": "movie",
                "tmdb_id": 558449,
            },
        ],
        date_label="15 октября 2026",
        site_url="https://kinojdun.ru",
        bot_username="kinojdun_bot",
    )

    print("\n[3. ОБРАЗЕЦ ДНЕВНОГО ДАЙДЖЕСТА «ЧТО ВЫХОДИТ СЕГОДНЯ»]")
    print("-" * 50)
    print(sample_daily)
    print("-" * 50)


async def check_settings():
    """Проверка настроек подключения и режимов автопостинга в Дзен."""
    print("=" * 65)
    print("ПРОВЕРКА КОНФИГУРАЦИИ ДЗЕНА (.env)")
    print("=" * 65)

    settings = Settings.from_env()

    print(f"DZEN_POSTING_ENABLED:             {settings.DZEN_POSTING_ENABLED}")
    print(f"DZEN_AUTO_PUBLISH:                {settings.DZEN_AUTO_PUBLISH}")
    print(f"DZEN_SYNC_MODE:                   {settings.DZEN_SYNC_MODE}")
    print(f"DZEN_CHANNEL_URL:                 {settings.DZEN_CHANNEL_URL or 'не задан'}")
    print(f"DZEN_CHANNEL_ID:                  {settings.DZEN_CHANNEL_ID or 'не задан'}")
    print(f"DZEN_MIN_POST_INTERVAL_MINUTES:   {settings.DZEN_MIN_POST_INTERVAL_MINUTES} мин.")
    print(f"DZEN_WEBHOOK_URL:                 {'задан' if settings.DZEN_WEBHOOK_URL else 'не задан'}")
    print(f"DZEN_SESSION_TOKEN:               {'задан' if settings.DZEN_SESSION_TOKEN else 'не задан'}")
    print("-" * 65)

    if settings.DZEN_SYNC_MODE == "telegram_sync":
        print("ℹ️  Режим «telegram_sync»:")
        print("   Посты автоматически публикуются через Telegram-канал (@kinojdun_channel)")
        print("   и транслируются в канал Дзена с помощью официального бота Дзена (@zen_sync_bot).")
        print(f"   Связанный TELEGRAM_CHANNEL_ID: {settings.TELEGRAM_CHANNEL_ID or 'НЕ ЗАДАН!'}")
    elif settings.DZEN_SYNC_MODE == "webhook":
        print("ℹ️  Режим «webhook»:")
        print(f"   URL вебхука: {settings.DZEN_WEBHOOK_URL or 'НЕ ЗАДАН!'}")
    elif settings.DZEN_SYNC_MODE == "rss":
        print("ℹ️  Режим «rss»:")
        print(f"   Адрес RSS-ленты для Дзена: {settings.SITE_BASE_URL.rstrip('/')}/dzen/rss.xml")
    print("=" * 65)


async def run_test_post():
    """Выполнение тестовой публикации в Дзен."""
    settings = Settings.from_env()
    engine = create_db_engine(settings.DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    from aiogram import Bot
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_BOT_TOKEN else None
    publisher = DzenPublisher(session_factory, settings, bot=bot)

    try:
        print("Отправка тестового поста в Дзен...")
        res = await publisher.publish_test_post()
        print("Результат отправки:")
        print(json.dumps(res, indent=2, ensure_ascii=False))
    finally:
        await publisher.close()
        if bot:
            await bot.session.close()
        await engine.dispose()



async def publish_movie_by_id(tmdb_id: int):
    """Публикация фильма или сериала по его ID из каталога seed."""
    settings = Settings.from_env()
    engine = create_db_engine(settings.DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    from aiogram import Bot
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_BOT_TOKEN else None
    publisher = DzenPublisher(session_factory, settings, bot=bot)

    seed_file = Path(__file__).parent.parent / "website" / "catalog_seed.json"
    target_item = None
    if seed_file.exists():
        with open(seed_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data.get("titles", []):
                if item.get("id") == tmdb_id:
                    target_item = item
                    break

    if not target_item:
        print(f"Тайтл с ID {tmdb_id} не найден в website/catalog_seed.json, создаю базовый пост.")
        target_item = {
            "title": f"Проект #{tmdb_id}",
            "media_type": "movie",
            "release_date": date.today().isoformat(),
            "genres": ["кино"],
            "overview": "Карточка проекта в каталоге КиноЖдуна.",
        }

    rel_date = None
    if target_item.get("release_date"):
        try:
            rel_date = date.fromisoformat(target_item["release_date"])
        except Exception:
            pass

    try:
        print(f"Публикация: «{target_item['title']}» (ID {tmdb_id})...")
        post = await publisher.publish_event(
            title=target_item["title"],
            media_type=target_item.get("media_type", "movie"),
            event_type="catalog_feature",
            tmdb_id=tmdb_id,
            air_date=rel_date,
            genres=target_item.get("genres", []),
            overview=target_item.get("overview"),
            poster_path=target_item.get("poster") or target_item.get("image"),
            force=True,
        )

        if post:
            print(f"✅ Успешно! ID публикации: {post.id}, статус: {post.status}")
        else:
            print("❌ Публикация не создана (возможно, отключена в настройках).")
    finally:
        await publisher.close()
        if bot:
            await bot.session.close()
        await engine.dispose()




def export_rss_preview():
    """Предпросмотр адреса и структуры RSS-ленты для Дзена."""
    settings = Settings.from_env()
    rss_url = f"{settings.SITE_BASE_URL.rstrip('/')}/dzen/rss.xml"
    print("=" * 65)
    print("RSS-ЛЕНТА КИНОЖДУНА ДЛЯ ДЗЕНА")
    print("=" * 65)
    print(f"URL ленты для добавления в Студию Дзена: {rss_url}")
    print("Формат: RSS 2.0 (content:encoded, enclosure, category, guid, pubDate)")
    print("Поддерживает: автоматический импорт статей и карточек премьер сайта.")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Утилита управления автопостингом в Дзен")
    parser.add_argument("--preview", action="store_true", help="Предпросмотр образцов постов для Дзена")
    parser.add_argument("--check", action="store_true", help="Проверка настроек окружения")
    parser.add_argument("--test-post", action="store_true", help="Отправка тестового поста")
    parser.add_argument("--publish-movie", type=int, help="Опубликовать фильм/сериал по TMDB ID")
    parser.add_argument("--export-rss", action="store_true", help="Показать URL и формат RSS ленты Дзена")

    args = parser.parse_args()

    if args.preview:
        preview_posts()
    elif args.check:
        asyncio.run(check_settings())
    elif args.test_post:
        asyncio.run(run_test_post())
    elif args.publish_movie:
        asyncio.run(publish_movie_by_id(args.publish_movie))
    elif args.export_rss:
        export_rss_preview()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
