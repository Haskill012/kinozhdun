"""Copy Telegram channel branding, adapting the personal-bot link for MAX."""
import asyncio, json, ssl
from urllib.request import urlopen
from aiogram import Bot
from bot.config import Settings
import aiohttp

async def main():
    ctx = ssl.create_default_context()
    with urlopen('https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer', timeout=30) as r:
        cert = r.read()
    ctx.load_verify_locations(cadata=cert.decode() if cert.startswith(b'-----') else ssl.DER_cert_to_PEM_cert(cert))
    s = Settings.from_env(); b = Bot(s.TELEGRAM_BOT_TOKEN)
    try:
        tg = await b.get_chat(s.TELEGRAM_CHANNEL_ID)
    finally:
        await b.session.close()
    description = tg.description.replace('@kinojdun_bot','https://max.ru/id5001170357_1_bot')
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx)) as session:
        url = 'https://platform-api2.max.ru/chats/-79850172292508'
        headers = {'Authorization':MAX_TOKEN}
        async with session.get(url, headers=headers) as r:
            before = await r.json()
        assert before['type']=='channel' and before['link']=='https://max.ru/channel_kinojdun'
        print('BEFORE',json.dumps(before,ensure_ascii=False))
        for key,value in [('title',tg.title),('description',description),('icon',{'url':'https://kinojdun.ru/static/channel-avatar-v2.png'})]:
            async with session.patch(url,headers=headers,json={key:value,'notify':False}) as r:
                d=await r.json()
                print('APPLY',key,r.status,json.dumps(d,ensure_ascii=False))
        async with session.get(url,headers=headers) as r:
            after=await r.json()
        print('AFTER',json.dumps(after,ensure_ascii=False))
        assert after['title']==tg.title and after['description']==description and after.get('icon')
asyncio.run(main())
