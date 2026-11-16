"""Verify branding and apply remaining VK profile fields when supported."""
import asyncio,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot.config import Settings
from bot.services.vk_client import VKClient,VKApiError
import aiohttp

async def main():
    s=Settings.from_env();c=VKClient(s.VK_ACCESS_TOKEN,s.VK_GROUP_ID)
    out=ROOT/'diagnostics/channel-fixes-2026-10-06/vk-verification.json';result={}
    def save():out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        actions=[('status','status.set',{'group_id':abs(s.VK_GROUP_ID),'text':'Премьеры фильмов и сериалов. Календарь: kinojdun.ru'}),
                 ('bot_link','groups.addLink',{'group_id':abs(s.VK_GROUP_ID),'link':'https://t.me/kinojdun_bot','text':'Личный трекер и напоминания'}),
                 ('channel_link','groups.addLink',{'group_id':abs(s.VK_GROUP_ID),'link':'https://t.me/kinojdun_channel','text':'Премьеры в Telegram'})]
        for key,method,params in actions:
            try:
                response=await c.api_call(method,params)
                result[key]={'applied':bool(response)}
            except VKApiError as e:result[key]={'error_code':e.error_code,'message':e.error_msg}
            except Exception as e:result[key]={'error_type':type(e).__name__}
            save();print(key,result[key],flush=True)
        try:
            server=await c.api_call('photos.getOwnerPhotoUploadServer',{'owner_id':-abs(s.VK_GROUP_ID)})
            form=aiohttp.FormData()
            form.add_field('photo',(ROOT/'website/static/channel-avatar-v2.png').read_bytes(),filename='avatar.png',content_type='image/png')
            http=await c._get_session()
            async with http.post(server['upload_url'],data=form) as response:
                response.raise_for_status();receipt=await response.json(content_type=None)
            answer=await c.api_call('photos.saveOwnerPhoto',{key:receipt[key] for key in ['server','photo','hash']})
            result['avatar']={'applied':bool(answer.get('photo_hash') or answer.get('photo_src'))}
        except VKApiError as e:result['avatar']={'error_code':e.error_code,'message':e.error_msg}
        except Exception as e:result['avatar']={'error_type':type(e).__name__}
        save();print('avatar',result['avatar'],flush=True)
        response=await c.api_call('groups.getById',{'group_id':abs(s.VK_GROUP_ID),'fields':'description,status,site,links,cover'})
        group=response['groups'][0]
        result['verification']={key:group.get(key) for key in ['id','name','description','status','site','links','photo_200']}
        result['verification']['has_cover']=bool(group.get('cover',{}).get('enabled'))
        save();print(json.dumps(result['verification'],ensure_ascii=False))
    finally:await c.close()

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(main())
