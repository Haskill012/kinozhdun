import asyncio, json, ssl
from urllib.request import urlopen
import aiohttp

async def main():
    ctx = ssl.create_default_context()
    with urlopen('https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer', timeout=30) as r:
        cert = r.read()
    ctx.load_verify_locations(cadata=cert.decode() if cert.startswith(b'-----') else ssl.DER_cert_to_PEM_cert(cert))
    async with aiohttp.ClientSession(headers={'Authorization':MAX_TOKEN}, connector=aiohttp.TCPConnector(ssl=ctx)) as s:
        for path in ('/chats/-79850172292508', '/chats/-79850172292508/members/me', '/messages?chat_id=-79850172292508&count=5'):
            async with s.get('https://platform-api2.max.ru'+path) as r:
                print(path, r.status, json.dumps(await r.json(), ensure_ascii=False))
asyncio.run(main())
