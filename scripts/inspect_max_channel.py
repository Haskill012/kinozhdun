import asyncio, json, sqlite3, ssl
from urllib.request import urlopen
import aiohttp
from bot.config import Settings
from aiogram import Bot

async def main():
    s = Settings.from_env()
    ctx = ssl.create_default_context()
    with urlopen('https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer', timeout=30) as r:
        cert = r.read()
    pem = cert.decode() if cert.startswith(b'-----') else ssl.DER_cert_to_PEM_cert(cert)
    ctx.load_verify_locations(cadata=pem)
    async with aiohttp.ClientSession(headers={'Authorization': MAX_TOKEN}, connector=aiohttp.TCPConnector(ssl=ctx)) as session:
        for path in ('/me', '/chats?count=100', '/updates?timeout=0&limit=100', '/subscriptions'):
            async with session.get('https://platform-api2.max.ru'+path, timeout=aiohttp.ClientTimeout(total=30)) as r:
                d = await r.json()
                if path.startswith('/updates'):
                    d = [{'type': u.get('update_type'), 'chat_id': u.get('chat_id'), 'chat': u.get('chat')} for u in d.get('updates', [])]
                elif path == '/me':
                    d = {k:d.get(k) for k in ('user_id','username','name')}
                elif path == '/subscriptions':
                    d = {'count':len(d.get('subscriptions', []))}
                print(path, r.status, json.dumps(d, ensure_ascii=False))
    b = Bot(s.TELEGRAM_BOT_TOKEN)
    try:
        ch = await b.get_chat(s.TELEGRAM_CHANNEL_ID)
        print('TG_BRAND', json.dumps({'title':ch.title,'description':ch.description}, ensure_ascii=False))
    finally:
        await b.session.close()
    db = sqlite3.connect('file:data/kinozhdun.db?mode=ro', uri=True); db.row_factory = sqlite3.Row
    print('SOURCE_POSTS', json.dumps([dict(r) for r in db.execute('select id,post_type,status,published_at,poster_path,post_text from channel_posts order by id desc limit 4')], ensure_ascii=False))
    print('SCHEDULE', s.DAILY_DIGEST_HOUR, s.WEEKLY_DIGEST_DAY, s.WEEKLY_DIGEST_HOUR, s.DAILY_DIGEST_SKIP_WEEKLY_DAY)
asyncio.run(main())
