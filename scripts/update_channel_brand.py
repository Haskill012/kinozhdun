"""Apply approved Telegram branding; retain every result for review."""
import asyncio
import json
import sys
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot.config import Settings
from bot.services.vk_client import VKClient, VKApiError

TITLE='КиноЖдун 🍿 Премьеры фильмов и сериалов'
DESCRIPTION=('Даты выхода фильмов, новых сезонов и серий. Подборки премьер, трейлеры и изменения расписания — с источниками и без спойлеров.\n\n'
             '🔔 Личные напоминания: @kinojdun_bot\n📅 Календарь: kinojdun.ru')
WELCOME=('<b>КиноЖдун — ваш список ожидания кино 🍿</b>\n\n'
         'Здесь — даты выхода фильмов, сезонов и серий, подборки премьер и трейлеры. Даты сопровождаем источниками; доступность зависит от страны и площадки.\n\n'
         '<b>Как получать личные напоминания:</b>\n'
         '1. Откройте @kinojdun_bot и отправьте название фильма или сериала.\n'
         '2. Выберите проект и нажмите «Добавить в отслеживание».\n'
         '3. Получайте уведомления об обновлении даты и напоминание перед премьерой.\n\n'
         'Расписание и карточки проектов: https://kinojdun.ru/calendar\n'
         'Делитесь своим списком ожидания с друзьями через бота.')
VK_TITLE='КиноЖдун | Фильмы, сериалы и даты выхода'
VK_DESCRIPTION=('Что посмотреть и когда выходит продолжение? Премьеры фильмов, новые сезоны и серии, трейлеры и изменения дат.\n\n'
                'Понятное расписание, краткий сюжет без спойлеров и ссылки на источники.\n'
                'Календарь: https://kinojdun.ru\nЛичные напоминания: https://t.me/kinojdun_bot')

async def main():
    s=Settings.from_env()
    assert s.TELEGRAM_CHANNEL_ID=='@kinojdun_channel' and abs(s.VK_GROUP_ID)==242059739
    output=ROOT/'diagnostics/channel-fixes-2026-10-06/branding-result.json'
    result={}
    def save():output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    b=Bot(s.TELEGRAM_BOT_TOKEN)
    try:
        actions=[('title',lambda:b.set_chat_title(s.TELEGRAM_CHANNEL_ID,TITLE)),
                 ('description',lambda:b.set_chat_description(s.TELEGRAM_CHANNEL_ID,DESCRIPTION)),
                 ('avatar',lambda:b.set_chat_photo(s.TELEGRAM_CHANNEL_ID,FSInputFile(ROOT/'website/static/channel-avatar-v2.png'))),
                 ('welcome',lambda:b.edit_message_text(WELCOME,chat_id=s.TELEGRAM_CHANNEL_ID,message_id=12,parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text='🔔 Открыть личный трекер',url='https://t.me/kinojdun_bot')],
                        [InlineKeyboardButton(text='📅 Календарь премьер',url='https://kinojdun.ru/calendar')]])))]
        for key,action in actions:
            try:result[key]={'applied':bool(await action())}
            except Exception as e:result[key]={'error_type':type(e).__name__}
            save();print(key,result[key],flush=True)
        result['cleanup']=[]
        # Test #3, obsolete prototype digests #4–7, and the incorrect weekly digest #15.
        for mid in [3,4,5,6,7,14,15]:
            row={'message_id':mid}
            try:row['deleted']=await b.delete_message(s.TELEGRAM_CHANNEL_ID,mid)
            except Exception as e:row['error_type']=type(e).__name__
            result['cleanup'].append(row);save();print(row,flush=True)
        chat=await b.get_chat(s.TELEGRAM_CHANNEL_ID)
        result['verification']={'title':chat.title,'description':chat.description,'has_photo':bool(chat.photo),
                                'pinned_message_id':chat.pinned_message.message_id if chat.pinned_message else None,
                                'pinned_text':chat.pinned_message.text if chat.pinned_message else None}
        if chat.photo:
            photo=await b.get_file(chat.photo.big_file_id)
            await b.download_file(photo.file_path,destination=output.with_name('telegram-avatar-applied.jpg'))
        save()
    finally:await b.session.close()
    vk=VKClient(s.VK_ACCESS_TOKEN,s.VK_GROUP_ID)
    try:
        try:
            answer=await vk.api_call('groups.edit',{'group_id':abs(s.VK_GROUP_ID),'title':VK_TITLE,
                                                  'description':VK_DESCRIPTION,'website':'https://kinojdun.ru'})
            result['vk_branding']={'applied':answer==1}
        except VKApiError as e:
            result['vk_branding']={'error_code':e.error_code,'message':e.error_msg}
        except Exception as e:result['vk_branding']={'error_type':type(e).__name__}
        save();print('VK',result['vk_branding'],flush=True)
    finally:await vk.close()

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
