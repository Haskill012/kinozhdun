"""Self-service privacy controls; deletion requires a fresh per-user confirmation."""
import secrets
import time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.db.repositories import Repository

router = Router(name='privacy_router')

class PrivacyState(StatesGroup):
    confirming = State()


@router.message(Command('privacy'))
async def show_privacy(message: Message):
    await message.answer(
        '🔒 <b>Ваши данные в КиноЖдуне</b>\n\n'
        'Для работы списка я сохраняю ваш идентификатор Telegram, имя, username, '
        'выбранные проекты, свои даты и историю напоминаний.\n\n'
        'Вы можете удалять проекты отдельно или удалить свой профиль целиком. '
        'Удаление профиля остановит напоминания и отключит созданные вами ссылки на списки.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='Удалить мои данные', callback_data='privacy_delete_request')]]))


@router.callback_query(F.data == 'privacy_delete_request')
async def request_deletion(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    nonce = secrets.token_hex(12)
    await state.set_state(PrivacyState.confirming)
    await state.update_data(delete_nonce=nonce, delete_user=callback.from_user.id, delete_time=time.time())
    await callback.message.edit_text(
        'Удалить ваш профиль, список ожидания, свои даты и ссылки на общие списки?\n\n'
        'Это действие нельзя отменить. Списки других пользователей останутся на месте.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='Да, удалить мои данные', callback_data='privacy_delete_confirm:'+nonce)], [
            InlineKeyboardButton(text='Отмена', callback_data='privacy_delete_cancel')]]))


@router.callback_query(F.data.startswith('privacy_delete_confirm:'))
async def confirm_deletion(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    nonce = callback.data.split(':', 1)[1]
    if (data.get('delete_user') != callback.from_user.id or
            not secrets.compare_digest(str(data.get('delete_nonce', '')), nonce) or
            time.time()-data.get('delete_time', 0) > 600):
        await callback.answer('Подтверждение устарело. Откройте /privacy ещё раз.', show_alert=True)
        return
    async with callback.bot['session_factory']() as session:
        await Repository(session).delete_user_data(callback.from_user.id)
        await session.commit()
    await state.clear()
    await callback.answer()
    await callback.message.edit_text('Ваши данные удалены. Напоминания остановлены, ссылки на ваши списки отключены.\n\n'
                                     'Если захотите начать заново, отправьте /start.')


@router.callback_query(F.data == 'privacy_delete_cancel')
async def cancel_deletion(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text('Удаление отменено. Ваш список на месте.')
