import asyncio, json, ssl
from urllib.request import urlopen
from pathlib import Path
import aiohttp

async def main():
    ctx=ssl.create_default_context()
    with urlopen('https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer',timeout=30) as r:cert=r.read()
    ctx.load_verify_locations(cadata=cert.decode() if cert.startswith(b'-----') else ssl.DER_cert_to_PEM_cert(cert))
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ctx)) as s:
        headers={'Authorization':MAX_TOKEN}
        async with s.post('https://platform-api2.max.ru/uploads?type=image',headers=headers) as r:
            upload=await r.json();assert r.status==200,upload.get('code')
        image=AVATAR_BYTES
        form=aiohttp.FormData();form.add_field('data',image,filename='channel-avatar.png',content_type='image/png')
        async with s.post(upload['url'],data=form) as r:
            result=await r.json();print('UPLOAD',r.status,'keys',list(result));assert r.status==200
        photos=result.get('photos',{});token=next(iter(photos.values()))['token']
        async with s.patch('https://platform-api2.max.ru/chats/-79850172292508',headers=headers,json={'icon':{'token':token},'notify':False}) as r:
            d=await r.json();print('AVATAR',r.status,json.dumps({k:d.get(k) for k in ('code','message','icon','title')},ensure_ascii=False));assert r.status==200
        async with s.get('https://platform-api2.max.ru/chats/-79850172292508',headers=headers) as r:
            d=await r.json();print('VERIFIED',json.dumps({'title':d['title'],'icon':d['icon']},ensure_ascii=False))
asyncio.run(main())
