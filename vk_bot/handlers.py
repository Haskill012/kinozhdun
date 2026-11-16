import re
from bot.db.repositories import Repository
from bot.utils.formatting import safe_html, format_date_ru
from max_bot.handlers import MaxBotHandlers
from max_bot.keyboards import callback_button, inline_keyboard, main_menu_keyboard


class VKBotHandlers(MaxBotHandlers):
    """Reuse tracking workflows, with VK paging and ownership checks."""
    async def _ensure_user(self, user_id, first_name, username):
        async with self.session_factory() as session:
            await Repository(session).get_or_create_user(user_id, username, first_name, referral_source='vk_organic')
            await session.commit()

    async def _owns(self, user_id, item_id):
        async with self.session_factory() as session:
            item = await Repository(session).get_tracked_item(item_id)
            return bool(item and item.user and item.user.telegram_id == user_id)

    async def _require_owned(self, user_id, chat_id, item_id):
        if await self._owns(user_id, item_id): return True
        await self.client.send_message(chat_id=chat_id, text='❌ Проект не найден в вашем списке.', attachments=main_menu_keyboard())
        return False

    async def handle_item_details(self, user_id, chat_id, item_id):
        if await self._require_owned(user_id, chat_id, item_id):
            await super().handle_item_details(user_id, chat_id, item_id)

    async def handle_setdate_prompt(self, user_id, chat_id, item_id):
        if await self._require_owned(user_id, chat_id, item_id):
            await super().handle_setdate_prompt(user_id, chat_id, item_id)

    async def handle_remove_confirm_prompt(self, user_id, chat_id, item_id):
        if await self._require_owned(user_id, chat_id, item_id):
            await super().handle_remove_confirm_prompt(user_id, chat_id, item_id)

    async def show_items(self, user_id, chat_id, action='details', page=0):
        self.state.clear_state(user_id)
        async with self.session_factory() as session:
            items = await Repository(session).get_user_items(user_id)
        if not items:
            await self.client.send_message(chat_id=chat_id, text='🍿 Ваш список ожидания пока пуст. Напишите название фильма или сериала.', attachments=main_menu_keyboard())
            return
        pages = (len(items) + 7) // 8
        page = max(0, min(page, pages - 1))
        heading = {'details':'🍿 МОЙ КИНОЖДУН', 'remove':'🗑 Выберите проект для удаления', 'setdate':'📅 Выберите проект для своей даты'}[action]
        lines = [heading, f'Всего проектов: {len(items)} · Страница {page+1}/{pages}', '']
        rows = []
        for item in items[page*8:(page+1)*8]:
            date = item.custom_date or item.next_air_date
            lines.append(safe_html(item.title) + ' — ' + (format_date_ru(date) if date else 'дата не объявлена'))
            icon = '📺' if item.media_type == 'tv' else '🎬'
            rows.append([callback_button(f'{icon} {item.title}', f'{action}:{item.id}')])
        nav = []
        if page > 0: nav.append(callback_button('← Назад', f'page:{action}:{page-1}'))
        if page < pages-1: nav.append(callback_button('Далее →', f'page:{action}:{page+1}'))
        if nav: rows.append(nav)
        rows.append([callback_button('🏠 Главное меню', 'menu:main')])
        await self.client.send_message(chat_id=chat_id, text='\n'.join(lines), attachments=inline_keyboard(rows))

    async def handle_list(self, user_id, chat_id):
        await self.show_items(user_id, chat_id)

    async def handle_remove_menu(self, user_id, chat_id):
        await self.show_items(user_id, chat_id, 'remove')

    async def handle_setdate_menu(self, user_id, chat_id):
        await self.show_items(user_id, chat_id, 'setdate')

    async def dispatch_callback(self, callback_id, user_id, chat_id, payload):
        if re.fullmatch(r'page:(details|remove|setdate):\d+', payload or ''):
            await self.client.answer_callback(callback_id)
            _, action, page = payload.split(':')
            await self.show_items(user_id, chat_id, action, int(page))
            return
        valid = (payload in {'menu:main','menu:search','menu:list','menu:status','menu:setdate','menu:remove','menu:help','back_to_list','cancel_search','back_to_search','already_tracked'}
                 or re.fullmatch(r'(preview|confirm_track):(movie|tv):[1-9]\d*', payload or '')
                 or re.fullmatch(r'(details|setdate|remove|confirm_remove):[1-9]\d*', payload or ''))
        if not valid:
            await self.client.answer_callback(callback_id, notification='Кнопка устарела. Откройте главное меню.')
            return
        await super().dispatch_callback(callback_id, user_id, chat_id, payload)
