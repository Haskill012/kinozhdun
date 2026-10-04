import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from bot.config import Settings
from bot.db.engine import init_db, get_session_factory, create_db_engine
from bot.services.tmdb import TMDBClient
from bot.handlers.start import router as start_router
from bot.handlers.tracking import router as tracking_router
from bot.handlers.list import router as list_router
from bot.scheduler.jobs import setup_scheduler

# Добавляем поддержку доступа через bot['attr'] и bot.get('attr')
Bot.__getitem__ = lambda self, item: getattr(self, item)
Bot.get = lambda self, item, default=None: getattr(self, item, default)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    settings = Settings.from_env()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    engine = create_db_engine(settings.DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)

    tmdb_client = TMDBClient(api_key=settings.TMDB_API_KEY, base_url=settings.TMDB_BASE_URL)

    # Привязываем сервисы и к bot, и к dp workflow_data
    bot.session_factory = session_factory
    bot.tmdb_client = tmdb_client
    bot.settings = settings

    dp["session_factory"] = session_factory
    dp["tmdb_client"] = tmdb_client
    dp["settings"] = settings

    dp.include_router(start_router)
    dp.include_router(list_router)
    dp.include_router(tracking_router)

    scheduler = setup_scheduler(bot, session_factory, tmdb_client, settings)
    scheduler.start()

    try:
        await bot.delete_webhook(drop_pending_updates=True)

        # Настраиваем всплывающее меню команд Telegram
        await bot.set_my_commands([
            BotCommand(command="start", description="Главное меню / Перезапуск"),
            BotCommand(command="list", description="Мой список ожидания"),
            BotCommand(command="status", description="Проверить статус релизов"),
            BotCommand(command="setdate", description="Указать дату премьеры вручную"),
            BotCommand(command="remove", description="Удалить из отслеживания"),
            BotCommand(command="help", description="Справка по боту"),
        ])

        logging.info("Бот КиноЖдун успешно запущен и слушает обновления!")
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await tmdb_client.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
