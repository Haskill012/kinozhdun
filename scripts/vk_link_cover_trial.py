"""Try a link preview cover with community-only media storage; no messages sent."""
from pathlib import Path
import subprocess
import sys
CODE = r'''
import asyncio, json, sqlite3, hashlib
from pathlib import Path
from datetime import date
from bot.config import Settings
from bot.services.vk_client import VKClient, VKApiError
from bot.services.vk_spintax import format_vk_post
async def main():
    s=Settings.from_env()
    assert abs(s.VK_GROUP_ID)==242059739 and not s.VK_AUTO_PUBLISH
    c=VKClient(s.VK_ACCESS_TOKEN,s.VK_GROUP_ID)
    item=next(x for x in json.loads(Path('website/catalog_seed.json').read_text())['titles'] if x['id']==1423191)
    post=format_vk_post(title=item['title'],media_type=item['media_type'],event_type='catalog_feature',
        item_id=item['id'],air_date=date.fromisoformat(item['release_date']),genres=item.get('genres'),
        overview=item.get('overview'),site_url=s.SITE_BASE_URL,create_poll=False,link_in_comment=False)
    db=sqlite3.connect('data/kinozhdun.db')
    guard=hashlib.sha256(b'link-preview-cover-trial-1423191-v2').hexdigest()
    row=db.execute('SELECT vk_post_id FROM vk_posts WHERE content_hash=?',(guard,)).fetchone()
    if row:
        print(json.dumps({'already_attempted':True,'post_id':row[0]})); return
    # Persist guard before any wall write; an ambiguous response is never blindly retried.
    db.execute("INSERT INTO vk_posts(content_hash,title,event_type,tmdb_id,media_type,status,created_at) VALUES(?,?,?,?,?,?,datetime('now'))",
        (guard,item['title'],'link_preview_trial',item['id'],item['media_type'],'verification_pending'))
    db.commit()
    try:
        http=await c._get_session()
        url='https://kinojdun.ru/social-image/3icyRAqgakNcQn6aDVz9libFmBA.jpg'
        async with http.get(url) as r:
            r.raise_for_status(); image=await r.read()
        from website.vk_upload_check import send_poster
        server=await c.api_call('photos.getMessagesUploadServer')
        receipt=await send_poster(http,server['upload_url'],image)
        saved=await c.api_call('photos.saveMessagesPhoto',receipt)
        p=saved[0]
        ident=str(p['owner_id'])+'_'+str(p['id'])
        result=await c.api_call('wall.post',{'owner_id':-c.group_id,'from_group':1,'message':post['text'],
            'attachments':post['target_url'],'link_photo_id':ident,'link_title':item['title'],'guid':guard})
        pid=result.get('post_id')
        assert isinstance(pid,int) and pid>0
        db.execute('UPDATE vk_posts SET vk_post_id=? WHERE content_hash=?',(pid,guard)); db.commit()
        print(json.dumps({'post_id':pid,'url':f'https://vk.ru/wall-{c.group_id}_{pid}',
            'requested_link_cover':ident,'preview_visually_confirmed':False},ensure_ascii=False))
    except VKApiError as e:
        db.execute('UPDATE vk_posts SET status=? WHERE content_hash=?',('failed',guard)); db.commit()
        print(json.dumps({'error_code':e.error_code,'message':e.error_msg,'new_post':False},ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'stage_failure':type(e).__name__,'automatic_retry':False}))
    finally:
        await c.close(); db.close()
asyncio.run(main())
'''
if __name__=='__main__':
    r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/kinojdun_codex_deploy'),'-o','BatchMode=yes',
        '-o','ConnectTimeout=10','root@62.217.176.12','docker exec -i kinozhdun_bot python -'],
        input=CODE,text=True,encoding='utf-8',capture_output=True)
    sys.stdout.reconfigure(encoding='utf-8',errors='replace'); print(r.stdout)
    if r.returncode: print(r.stderr)
    raise SystemExit(r.returncode)
