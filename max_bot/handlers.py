"""Обработчики команд, сообщений и callback-кнопок бота КиноЖдун в MAX Messenger."""

import datetime
import logging
import re
from typing import Any, Optional

from bot.db.repositories import Repository
from bot.services.season_dates import upcoming_season
from bot.services.tmdb import TMDBClient
from bot.utils.formatting import (
    format_date_ru,
    format_item_details,
    format_search_results_message,
    safe_html,
)
from max_bot.client import MaxBotClient
from max_bot.config import MaxBotSettings
from max_bot.keyboards import (
    cancel_keyboard,
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

logger = logging.getLogger(__name__)


class MaxBotHandlers:
    """Класс обработки событий и бизнес-логики бота MAX."""

    def __init__(
        self,
        client: MaxBotClient,
        session_factory: Any,
        tmdb: TMDBClient,
        settings: MaxBotSettings,
        state_manager: StateManager,
    ):
        self.client = client
        self.session_factory = session_factory
        self.tmdb = tmdb
        self.settings = settings
        self.state = state_manager

    # =========================================================================
    # Вспомогательные методы
    # =========================================================================

    async def _ensure_user(self, user_id: int, first_name: str | None, username: str | None):
        """Гарантирует регистрацию пользователя в БД."""
        async with self.session_factory() as session:
            repo = Repository(session)
            await repo.get_or_create_user(
                telegram_id=user_id,
                username=username,
                first_name=first_name,
                referral_source="max_organic",
            )
            await session.commit()

    # =========================================================================
    # Команды и меню
    # =========================================================================

    async def handle_start(
        self,
        user_id: int,
        chat_id: int,
        first_name: str | None,
        username: str | None,
        payload: str | None = None,
    ) -> None:
        """Приветствие при старте бота."""
        await self._ensure_user(user_id, first_name, username)
        self.state.clear_state(user_id)

        if payload:
            match = re.match(r"^(?:c|share)_(tv|movie)_(\d+)", payload.strip())
            if match:
                media_type = match.group(1)
                tmdb_id = int(match.group(2))
                await self.handle_preview(user_id, chat_id, media_type, tmdb_id)
                return

        safe_name = safe_html(first_name or "друг")
        text = (
            "🎬 <b>КИНОЖДУН</b> • Личный трекер премьер\n\n"
            f"Привет, <b>{safe_name}</b>! 👋\n\n"
            "Я слежу за выходом новых сезонов сериалов и продолжений фильмов "
            "в официальных каталогах (TMDB, Netflix, HBO, Apple TV+, Кинопоиск и др.).\n\n"
            "✨ <b>Возможности бота:</b>\n"
            "• 🔍 <b>Поиск</b>: просто отправьте название любого фильма или сериала\n"
            "• 🍿 <b>«Мой Кинождун»</b>: ваш личный список отслеживания\n"
            "• 🔔 <b>Уведомления</b>: бот сам пришлёт дату релиза и напомнит перед премьерой!\n"
            "• 📅 <b>Своя дата</b>: можно указать собственную дату напоминания\n\n"
            "👇 <b>Выберите действие в меню ниже:</b>"
        )
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=main_menu_keyboard(),
        )

    async def handle_help(self, user_id: int, chat_id: int) -> None:
        """Справка по боту."""
        self.state.clear_state(user_id)
        text = (
            "ℹ️ <b>Справка по боту КиноЖдун:</b>\n\n"
            "🔍 <b>Как искать:</b>\n"
            "Нажмите «🔍 Найти сериал / фильм» или просто напишите название в чат "
            "(например, <i>«Дюна»</i> или <i>«Пацаны»</i>).\n\n"
            "➕ <b>Как отслеживать:</b>\n"
            "В карточке найденного фильма или сериала нажмите «➕ Добавить в отслеживание».\n\n"
            "🔔 <b>Как приходят уведомления:</b>\n"
            "• При появлении официальной даты выхода нового сезона или фильма\n"
            "• За 3 дня до даты премьеры\n"
            "• В день выхода фильма или сезона сериала\n\n"
            "📅 <b>Своя дата премьеры:</b>\n"
            "В разделе «📅 Указать дату» вы можете задать желаемую дату личного напоминания "
            "в формате ДД.ММ.ГГГГ.\n\n"
            "🍿 <b>Команды бота:</b>\n"
            "/start — главное меню\n"
            "/list — список ожидаемого\n"
            "/status — проверить статус релизов\n"
            "/setdate — указать дату вручную\n"
            "/remove — удалить из отслеживания\n"
            "/help — эта справка"
        )
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=main_menu_keyboard(),
        )

    async def handle_search_prompt(self, user_id: int, chat_id: int) -> None:
        """Запрос текста для поиска."""
        self.state.set_state(user_id, STATE_SEARCH_INPUT)
        text = (
            "🔍 <b>Поиск фильма или сериала</b>\n\n"
            "Напишите в ответ название проекта, который вы ждёте.\n"
            "<i>Например: Ведьмак, Мандалорец, Дюна, Острые козырьки...</i>"
        )
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=cancel_keyboard(),
        )

    async def handle_search_query(self, user_id: int, chat_id: int, query: str) -> None:
        """Поиск по TMDB и выдача результатов."""
        self.state.clear_state(user_id)
        query = query.strip()
        if not query:
            return

        results = await self.tmdb.search_multi(query)
        if not results:
            text = (
                f"🔍 По запросу <b>«{safe_html(query)}»</b> ничего не найдено.\n"
                "Попробуйте уточнить название или проверьте опечатки."
            )
            await self.client.send_message(
                chat_id=chat_id,
                text=text,
                attachments=main_menu_keyboard(),
            )
            return

        # Сохраняем в память для кнопки «Назад к поиску»
        self.state.update_data(user_id, last_search={"query": query, "results": results})

        text = format_search_results_message(query, results)
        keyboard = search_results_keyboard(results)
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=keyboard,
        )

    # =========================================================================
    # Карточка предпросмотра и отслеживание
    # =========================================================================

    async def handle_preview(
        self,
        user_id: int,
        chat_id: int,
        media_type: str,
        tmdb_id: int,
    ) -> None:
        """Показ подробной карточки проекта."""
        if media_type == "tv":
            details = await self.tmdb.get_tv_details(tmdb_id)
        else:
            details = await self.tmdb.get_movie_details(tmdb_id)

        if not details:
            await self.client.send_message(
                chat_id=chat_id,
                text="❌ Не удалось загрузить информацию о проекте из каталога TMDB.",
                attachments=main_menu_keyboard(),
            )
            return

        # Проверяем, отслеживает ли уже пользователь
        is_already_tracked = False
        tracked_item_id = None
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=user_id)
            for it in items:
                if it.tmdb_id == tmdb_id and it.media_type == media_type:
                    is_already_tracked = True
                    tracked_item_id = it.id
                    break

        card_text = format_item_details(details, media_type)
        raw_title = details.get("title") or details.get("name") or "Без названия"

        keyboard = preview_item_keyboard(
            media_type=media_type,
            tmdb_id=tmdb_id,
            is_already_tracked=is_already_tracked,
            tracked_item_id=tracked_item_id,
            title=raw_title,
            site_url=self.settings.SITE_BASE_URL,
        )

        attachments = list(keyboard)
        # Если есть постер — загружаем и прикрепляем через токен
        poster_path = details.get("poster_path")
        if poster_path:
            poster_url = f"{self.settings.TMDB_IMAGE_BASE_URL}{poster_path}"
            photo_token = await self.client.upload_image_from_url(poster_url)
            if photo_token:
                attachments.insert(0, {
                    "type": "image",
                    "payload": {"token": photo_token}
                })

        try:
            await self.client.send_message(
                chat_id=chat_id,
                text=card_text,
                attachments=attachments,
            )
        except Exception:
            # Fallback на отправку без картинки, если сервер отклонил медиа
            await self.client.send_message(
                chat_id=chat_id,
                text=card_text,
                attachments=keyboard,
            )

    async def handle_confirm_track(
        self,
        user_id: int,
        chat_id: int,
        media_type: str,
        tmdb_id: int,
    ) -> None:
        """Добавление фильма или сериала в отслеживание."""
        if media_type == "tv":
            details = await self.tmdb.get_tv_details(tmdb_id)
        else:
            details = await self.tmdb.get_movie_details(tmdb_id)

        if not details:
            await self.client.send_message(
                chat_id=chat_id,
                text="❌ Проект не найден в каталоге TMDB.",
                attachments=main_menu_keyboard(),
            )
            return

        async with self.session_factory() as session:
            repo = Repository(session)
            user = await repo.get_or_create_user(
                telegram_id=user_id,
                username=None,
                first_name=None,
            )

            # Проверка лимита
            existing_items = await repo.get_user_items(telegram_id=user_id)
            if len(existing_items) >= self.settings.MAX_ITEMS_PER_USER:
                await self.client.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ Достигнут лимит отслеживаемых проектов ({self.settings.MAX_ITEMS_PER_USER}).\n"
                        "Удалите ненужные тайтлы перед добавлением новых."
                    ),
                    attachments=main_menu_keyboard(),
                )
                return

            # Проверка дубликата
            for it in existing_items:
                if it.tmdb_id == tmdb_id and it.media_type == media_type:
                    await self.client.send_message(
                        chat_id=chat_id,
                        text=f"ℹ️ <b>«{safe_html(it.title)}»</b> уже находится в вашем списке ожидания!",
                        attachments=main_menu_keyboard(),
                    )
                    return

            title = details.get("title") or details.get("name") or "Без названия"
            orig_title = details.get("original_title") or details.get("original_name")
            poster = details.get("poster_path")
            network = details.get("network")

            if media_type == "tv":
                next_season, next_air_date = upcoming_season(details)
                last_season = details.get("number_of_seasons")
                last_air_date = None
            else:
                next_season = None
                raw_rel = details.get("release_date")
                next_air_date = None
                if raw_rel:
                    try:
                        next_air_date = datetime.date.fromisoformat(raw_rel[:10])
                    except Exception:
                        pass
                last_season = None
                last_air_date = next_air_date

            tmdb_url = details.get("tmdb_url") or f"https://www.themoviedb.org/{media_type}/{tmdb_id}"

            await repo.add_tracked_item(
                user_id=user.id,
                tmdb_id=tmdb_id,
                media_type=media_type,
                title=title,
                original_title=orig_title,
                poster_path=poster,
                last_known_season=last_season,
                last_known_air_date=last_air_date,
                next_air_date=next_air_date,
                tmdb_url=tmdb_url,
                network=network,
            )
            await session.commit()

        success_text = (
            f"✅ <b>«{safe_html(title)}»</b> успешно добавлен в ваш список отслеживания!\n\n"
            "Как только появится официальная дата премьеры или новый сезон — я сразу пришлю уведомление 🍿"
        )
        keyboard = track_success_keyboard(
            media_type=media_type,
            tmdb_id=tmdb_id,
            site_url=self.settings.SITE_BASE_URL,
        )
        await self.client.send_message(
            chat_id=chat_id,
            text=success_text,
            attachments=keyboard,
        )

    # =========================================================================
    # Список («Мой Кинождун») и статус
    # =========================================================================

    async def handle_list(self, user_id: int, chat_id: int) -> None:
        """Показ списка отслеживаемых проектов пользователя."""
        self.state.clear_state(user_id)
        async with self.session_factory() as session:
            repo = Repository(session)
            await repo.get_or_create_user(telegram_id=user_id, username=None, first_name=None)
            items = await repo.get_user_items(telegram_id=user_id)

        if not items:
            text = (
                "🍿 <b>МОЙ КИНОЖДУН</b>\n\n"
                "📭 Ваш список ожидания пока пуст.\n\n"
                "Нажмите <b>«🔍 Найти сериал / фильм»</b> ниже или просто отправьте название тайтла в чат!"
            )
            await self.client.send_message(
                chat_id=chat_id,
                text=text,
                attachments=main_menu_keyboard(),
            )
            return

        lines = [
            "🍿 <b>МОЙ КИНОЖДУН</b>",
            f"Вы отслеживаете проектов: <b>{len(items)}</b>\n",
        ]
        for i, item in enumerate(items, 1):
            media_type = getattr(item, "media_type", "movie")
            icon = "📺" if media_type == "tv" else "🎬"
            title = safe_html(getattr(item, "title", "Без названия"))
            next_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
            date_info = f" — <b>{format_date_ru(next_date)}</b>" if next_date else " — <i>дата не объявлена</i>"
            lines.append(f"{i}. {icon} <b>{title}</b>{date_info}")

        lines.append("\n👇 <i>Выберите проект ниже для просмотра подробностей:</i>")
        text = "\n".join(lines)
        keyboard = user_items_keyboard(items, action="details")

        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=keyboard,
        )

    async def handle_status(self, user_id: int, chat_id: int) -> None:
        """Актуализация статусов всех отслеживаемых проектов с TMDB."""
        self.state.clear_state(user_id)
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=user_id)

            if not items:
                await self.client.send_message(
                    chat_id=chat_id,
                    text="📭 Ваш список ожидания пуст. Нечего обновлять.",
                    attachments=main_menu_keyboard(),
                )
                return

            for item in items:
                try:
                    if item.media_type == "tv":
                        details = await self.tmdb.get_tv_details(item.tmdb_id)
                        if details:
                            if details.get("network"):
                                item.network = details["network"]
                            item.next_season_number, item.next_air_date = upcoming_season(details)
                            item.status = "announced" if item.next_air_date else details.get("status", "waiting")
                    else:
                        details = await self.tmdb.get_movie_details(item.tmdb_id)
                        if details:
                            raw_rel = details.get("release_date")
                            if raw_rel:
                                try:
                                    item.next_air_date = datetime.date.fromisoformat(raw_rel[:10])
                                    item.status = "announced"
                                except Exception:
                                    pass
                            else:
                                item.status = details.get("status", "waiting")
                except Exception as e:
                    logger.warning("Ошибка обновления тайтла %s в status: %s", item.title, e)

            await session.commit()
            items = await repo.get_user_items(telegram_id=user_id)

        lines = [
            "🔄 <b>СТАТУС РЕЛИЗОВ АКТУАЛИЗИРОВАН:</b>\n",
        ]
        for i, item in enumerate(items, 1):
            media_type = getattr(item, "media_type", "movie")
            icon = "📺" if media_type == "tv" else "🎬"
            title = safe_html(getattr(item, "title", "Без названия"))
            next_date = getattr(item, "next_air_date", None) or getattr(item, "custom_date", None)
            date_info = f"<b>{format_date_ru(next_date)}</b>" if next_date else "<i>пока не объявлена</i>"
            lines.append(f"{i}. {icon} <b>{title}</b>: {date_info}")

        text = "\n".join(lines)
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=main_menu_keyboard(),
        )

    async def handle_item_details(self, user_id: int, chat_id: int, item_id: int) -> None:
        """Показ детальной карточки уже отслеживаемого проекта."""
        async with self.session_factory() as session:
            repo = Repository(session)
            item = await repo.get_tracked_item(item_id)

        if not item:
            await self.client.send_message(
                chat_id=chat_id,
                text="❌ Проект не найден в вашем списке.",
                attachments=main_menu_keyboard(),
            )
            return

        text = format_item_details(item)
        keyboard = item_details_keyboard(item, site_url=self.settings.SITE_BASE_URL)

        attachments = list(keyboard)
        if getattr(item, "poster_path", None):
            poster_url = f"{self.settings.TMDB_IMAGE_BASE_URL}{item.poster_path}"
            photo_token = await self.client.upload_image_from_url(poster_url)
            if photo_token:
                attachments.insert(0, {
                    "type": "image",
                    "payload": {"token": photo_token}
                })

        try:
            await self.client.send_message(
                chat_id=chat_id,
                text=text,
                attachments=attachments,
            )
        except Exception:
            await self.client.send_message(
                chat_id=chat_id,
                text=text,
                attachments=keyboard,
            )

    # =========================================================================
    # Ручная установка даты премьеры
    # =========================================================================

    async def handle_setdate_menu(self, user_id: int, chat_id: int) -> None:
        """Меню выбора проекта для указания даты."""
        self.state.clear_state(user_id)
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=user_id)

        if not items:
            await self.client.send_message(
                chat_id=chat_id,
                text="📭 Ваш список ожидания пуст. Сначала добавьте тайтл для установки даты.",
                attachments=main_menu_keyboard(),
            )
            return

        text = (
            "📅 <b>Установка личной даты премьеры</b>\n\n"
            "Выберите проект, для которого хотите настроить дату напоминания:"
        )
        keyboard = user_items_keyboard(items, action="setdate")
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=keyboard,
        )

    async def handle_setdate_prompt(self, user_id: int, chat_id: int, item_id: int) -> None:
        """Запрос ввода даты пользователем."""
        async with self.session_factory() as session:
            repo = Repository(session)
            item = await repo.get_tracked_item(item_id)

        if not item:
            await self.client.send_message(
                chat_id=chat_id,
                text="❌ Проект не найден.",
                attachments=main_menu_keyboard(),
            )
            return

        self.state.set_state(user_id, STATE_DATE_INPUT, item_id=item_id)
        text = (
            f"📅 <b>Укажите свою дату премьеры</b> для «{safe_html(item.title)}».\n\n"
            "Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например: <code>15.11.2026</code>):"
        )
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=cancel_keyboard(),
        )

    async def handle_date_input(self, user_id: int, chat_id: int, text: str) -> None:
        """Обработка введённой даты."""
        data = self.state.get_data(user_id)
        item_id = data.get("item_id")
        if not item_id:
            self.state.clear_state(user_id)
            await self.handle_start(user_id, chat_id, None, None)
            return

        clean_text = text.strip()
        parsed_date = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                parsed_date = datetime.datetime.strptime(clean_text, fmt).date()
                break
            except ValueError:
                pass

        if not parsed_date:
            await self.client.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ <b>Некорректный формат даты!</b>\n\n"
                    "Пожалуйста, введите дату строго в формате <b>ДД.ММ.ГГГГ</b> (например: <code>25.12.2026</code>):"
                ),
                attachments=cancel_keyboard(),
            )
            return

        async with self.session_factory() as session:
            repo = Repository(session)
            success = await repo.set_custom_date(item_id, parsed_date, telegram_id=user_id)
            if success:
                item = await repo.get_tracked_item(item_id)
                title = item.title if item else "проекта"
                await session.commit()
                self.state.clear_state(user_id)
                await self.client.send_message(
                    chat_id=chat_id,
                    text=(
                        f"✅ Личная дата напоминания для «{safe_html(title)}» "
                        f"успешно сохранена: <b>{format_date_ru(parsed_date)}</b> 🍿"
                    ),
                    attachments=main_menu_keyboard(),
                )
            else:
                self.state.clear_state(user_id)
                await self.client.send_message(
                    chat_id=chat_id,
                    text="❌ Не удалось сохранить дату (проект не найден).",
                    attachments=main_menu_keyboard(),
                )

    # =========================================================================
    # Удаление тайтлов
    # =========================================================================

    async def handle_remove_menu(self, user_id: int, chat_id: int) -> None:
        """Меню выбора проекта для удаления."""
        self.state.clear_state(user_id)
        async with self.session_factory() as session:
            repo = Repository(session)
            items = await repo.get_user_items(telegram_id=user_id)

        if not items:
            await self.client.send_message(
                chat_id=chat_id,
                text="📭 Ваш список ожидания пуст. Нечего удалять.",
                attachments=main_menu_keyboard(),
            )
            return

        text = "🗑 <b>Удаление из отслеживания</b>\n\nВыберите тайтл, который хотите убрать из списка:"
        keyboard = user_items_keyboard(items, action="remove")
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=keyboard,
        )

    async def handle_remove_confirm_prompt(self, user_id: int, chat_id: int, item_id: int) -> None:
        """Запрос подтверждения удаления."""
        async with self.session_factory() as session:
            repo = Repository(session)
            item = await repo.get_tracked_item(item_id)

        if not item:
            await self.client.send_message(
                chat_id=chat_id,
                text="❌ Проект не найден.",
                attachments=main_menu_keyboard(),
            )
            return

        text = f"❓ Вы действительно хотите удалить «{safe_html(item.title)}» из вашего Кинождуна?"
        keyboard = confirm_remove_keyboard(item_id)
        await self.client.send_message(
            chat_id=chat_id,
            text=text,
            attachments=keyboard,
        )

    async def handle_confirm_remove(self, user_id: int, chat_id: int, item_id: int) -> None:
        """Выполнение удаления проекта."""
        async with self.session_factory() as session:
            repo = Repository(session)
            item = await repo.get_tracked_item(item_id)
            title = item.title if item else "Проект"
            success = await repo.remove_tracked_item(item_id, telegram_id=user_id)
            if success:
                await session.commit()
                await self.client.send_message(
                    chat_id=chat_id,
                    text=f"🗑 <b>«{safe_html(title)}»</b> удалён из вашего списка ожидания.",
                    attachments=main_menu_keyboard(),
                )
            else:
                await self.client.send_message(
                    chat_id=chat_id,
                    text="❌ Не удалось удалить проект.",
                    attachments=main_menu_keyboard(),
                )

    # =========================================================================
    # Диспетчер входящих Callback-кнопок
    # =========================================================================

    async def dispatch_callback(
        self,
        callback_id: str,
        user_id: int,
        chat_id: int,
        payload: str,
    ) -> None:
        """Маршрутизация нажатий инлайн-кнопок."""
        # Отвечаем на callback_id сразу, чтобы убрать индикатор загрузки у пользователя
        try:
            await self.client.answer_callback(callback_id)
        except Exception as e:
            logger.debug("Не удалось отправить answer_callback %s: %s", callback_id, e)

        payload = (payload or "").strip()

        # Меню и навигация
        if payload == "menu:main":
            self.state.clear_state(user_id)
            await self.handle_start(user_id, chat_id, None, None)
            return
        if payload == "menu:search":
            await self.handle_search_prompt(user_id, chat_id)
            return
        if payload == "menu:list" or payload == "back_to_list":
            await self.handle_list(user_id, chat_id)
            return
        if payload == "menu:status":
            await self.handle_status(user_id, chat_id)
            return
        if payload == "menu:setdate":
            await self.handle_setdate_menu(user_id, chat_id)
            return
        if payload == "menu:remove":
            await self.handle_remove_menu(user_id, chat_id)
            return
        if payload == "menu:help":
            await self.handle_help(user_id, chat_id)
            return
        if payload == "cancel_search":
            self.state.clear_state(user_id)
            await self.client.send_message(
                chat_id=chat_id,
                text="❌ Действие отменено.",
                attachments=main_menu_keyboard(),
            )
            return

        # Назад к результатам поиска
        if payload == "back_to_search":
            last_search = self.state.get_data(user_id).get("last_search")
            if last_search:
                q = last_search.get("query", "")
                res = last_search.get("results", [])
                text = format_search_results_message(q, res)
                kb = search_results_keyboard(res)
                await self.client.send_message(chat_id=chat_id, text=text, attachments=kb)
            else:
                await self.handle_search_prompt(user_id, chat_id)
            return

        # Предпросмотр: preview:{media_type}:{tmdb_id}
        if payload.startswith("preview:"):
            parts = payload.split(":")
            if len(parts) >= 3:
                media_type = parts[1]
                tmdb_id = int(parts[2])
                await self.handle_preview(user_id, chat_id, media_type, tmdb_id)
            return

        # Подтверждение отслеживания: confirm_track:{media_type}:{tmdb_id}
        if payload.startswith("confirm_track:"):
            parts = payload.split(":")
            if len(parts) >= 3:
                media_type = parts[1]
                tmdb_id = int(parts[2])
                await self.handle_confirm_track(user_id, chat_id, media_type, tmdb_id)
            return

        # Детали тайтла: details:{item_id}
        if payload.startswith("details:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                await self.handle_item_details(user_id, chat_id, int(parts[1]))
            return

        # Установка даты: setdate:{item_id}
        if payload.startswith("setdate:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                await self.handle_setdate_prompt(user_id, chat_id, int(parts[1]))
            return

        # Удаление: remove:{item_id}
        if payload.startswith("remove:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                await self.handle_remove_confirm_prompt(user_id, chat_id, int(parts[1]))
            return

        # Подтверждение удаления: confirm_remove:{item_id}
        if payload.startswith("confirm_remove:"):
            parts = payload.split(":")
            if len(parts) >= 2 and parts[1].isdigit():
                await self.handle_confirm_remove(user_id, chat_id, int(parts[1]))
            return

        if payload == "already_tracked":
            await self.client.send_message(
                chat_id=chat_id,
                text="ℹ️ Этот проект уже находится в вашем списке ожидания!",
            )
            return

    # =========================================================================
    # Диспетчер входящих текстовых сообщений
    # =========================================================================

    async def dispatch_message(
        self,
        user_id: int,
        chat_id: int,
        first_name: str | None,
        username: str | None,
        text: str,
    ) -> None:
        """Маршрутизация входящего текстового сообщения."""
        text = text.strip()
        if not text:
            return

        # Обработка команд
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/start", "/start@id5001170357_1_bot"):
                await self.handle_start(user_id, chat_id, first_name, username, payload=arg)
                return
            if cmd in ("/help", "/help@id5001170357_1_bot"):
                await self.handle_help(user_id, chat_id)
                return
            if cmd in ("/list", "/list@id5001170357_1_bot"):
                await self.handle_list(user_id, chat_id)
                return
            if cmd in ("/status", "/status@id5001170357_1_bot"):
                await self.handle_status(user_id, chat_id)
                return
            if cmd in ("/setdate", "/setdate@id5001170357_1_bot"):
                await self.handle_setdate_menu(user_id, chat_id)
                return
            if cmd in ("/remove", "/remove@id5001170357_1_bot"):
                await self.handle_remove_menu(user_id, chat_id)
                return
            if cmd in ("/cancel", "/cancel@id5001170357_1_bot"):
                self.state.clear_state(user_id)
                await self.client.send_message(
                    chat_id=chat_id,
                    text="❌ Действие отменено.",
                    attachments=main_menu_keyboard(),
                )
                return

        # Проверка текущего FSM состояния
        current_state = self.state.get_user_state(user_id)
        if current_state == STATE_DATE_INPUT:
            await self.handle_date_input(user_id, chat_id, text)
            return

        # Поиск по любому обычному тексту
        await self.handle_search_query(user_id, chat_id, text)
