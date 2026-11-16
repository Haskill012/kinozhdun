"""Точка входа для запуска бота КиноЖдун в мессенджере Макс (MAX Messenger)."""

import asyncio
import logging
import signal
import sys

from bot.db.engine import create_db_engine, get_session_factory, init_db
from bot.services.tmdb import TMDBClient
from max_bot.client import MaxBotClient
from max_bot.config import MaxBotSettings
from max_bot.dispatcher import MaxBotDispatcher
from max_bot.handlers import MaxBotHandlers
from max_bot.scheduler import setup_scheduler
from max_bot.state import StateManager


async def main() -> None:
    """Главная функция инициализации и запуска бота."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(name)s] - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    logger = logging.getLogger("max_bot")

    settings = MaxBotSettings.from_env()

    # 1. База данных
    engine = create_db_engine(settings.MAX_DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    logger.info("База данных MAX успешно инициализирована: %s", settings.MAX_DATABASE_URL)

    # 2. Клиенты TMDB и MAX
    tmdb_client = TMDBClient(api_key=settings.TMDB_API_KEY, base_url=settings.TMDB_BASE_URL)
    client = MaxBotClient(token=settings.MAX_BOT_TOKEN)

    # 3. Информация о боте и регистрация команд
    try:
        bot_info = await client.get_me()
        bot_name = bot_info.get("name") or bot_info.get("first_name") or "КиноЖдун"
        bot_username = bot_info.get("username") or ""
        logger.info("Подключен к MAX Bot API: %s (@%s, ID: %s)", bot_name, bot_username, bot_info.get("user_id"))
    except Exception as e:
        logger.error("Не удалось подключиться к MAX Bot API: %s", e)
        await tmdb_client.close()
        await engine.dispose()
        return

    # Установка всплывающего меню команд
    try:
        commands = [
            {"name": "start", "description": "Главное меню / Перезапуск"},
            {"name": "list", "description": "Мой Кинождун (список ожидания)"},
            {"name": "status", "description": "Проверить статус релизов"},
            {"name": "setdate", "description": "Указать дату премьеры вручную"},
            {"name": "remove", "description": "Удалить из отслеживания"},
            {"name": "help", "description": "Справка по боту"},
        ]
        await client.set_commands(commands)
        logger.info("Команды бота успешно зарегистрированы в MAX")
    except Exception as e:
        logger.warning("Не удалось зарегистрировать команды: %s", e)

    # 4. Диспетчер и обработчики
    state_manager = StateManager()
    handlers = MaxBotHandlers(
        client=client,
        session_factory=session_factory,
        tmdb=tmdb_client,
        settings=settings,
        state_manager=state_manager,
    )
    dispatcher = MaxBotDispatcher(handlers)

    # 5. Фоновый планировщик
    scheduler = setup_scheduler(client, session_factory, tmdb_client, settings)
    scheduler.start()
    logger.info("Планировщик фоновых проверок и уведомлений запущен")

    # 6. Цикл Long Polling
    running = True

    def stop_signal():
        nonlocal running
        running = False
        logger.info("Получен сигнал остановки...")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_signal)
        except (NotImplementedError, RuntimeError):
            # В Windows signal handler на event loop может не поддерживаться
            pass

    marker: int | None = None
    logger.info("[MAX] Бот КиноЖдун в MAX Messenger запущен и ожидает сообщений!")

    try:
        while running:
            try:
                data = await client.get_updates(
                    marker=marker,
                    limit=100,
                    timeout=settings.POLL_TIMEOUT_SECONDS,
                )
                marker = data.get("marker", marker)
                updates = data.get("updates", [])

                for upd in updates:
                    asyncio.create_task(dispatcher.process_update(upd))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Ошибка в цикле получения обновлений: %s", e)
                await asyncio.sleep(2)

    finally:
        logger.info("Завершение работы бота MAX...")
        scheduler.shutdown(wait=False)
        await client.close()
        await tmdb_client.close()
        await engine.dispose()
        logger.info("Бот MAX корректно остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
