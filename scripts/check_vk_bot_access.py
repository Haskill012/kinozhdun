"""Check bot API permissions without logging credentials or response parameters."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from bot.services.vk_client import VKClient, VKApiError

async def main():
    env=dotenv_values('.env')
    client=VKClient(env['VK_BOT_TOKEN'], int(env['VK_BOT_GROUP_ID']))
    try:
        methods=[('groups.getById',{'group_id':client.group_id}),('groups.getTokenPermissions',{})]
        if '--configure' in sys.argv:
            methods += [('groups.setSettings',{'group_id':client.group_id,'messages':1,'bots_capabilities':1,'bots_start_button':1}),
                        ('groups.setLongPollSettings',{'group_id':client.group_id,'enabled':1,'api_version':'5.199','message_new':1,'message_event':1})]
        methods += [('groups.getLongPollSettings',{'group_id':client.group_id}),('groups.getLongPollServer',{'group_id':client.group_id})]
        for method, params in methods:
            try:
                result=await client.api_call(method,params)
                if method.endswith('getLongPollServer'):print(method+': OK (server and cursor available)')
                elif method.endswith('getById'):
                    groups=result.get('groups',[]) if isinstance(result,dict) else result
                    print(method+': '+str([(g.get('id'),g.get('name')) for g in groups]))
                else:print(method+': '+str(result))
            except VKApiError as exc:print(method+': ERROR '+str(exc.error_code)+' '+exc.error_msg)
    finally:await client.close()

if __name__=='__main__':asyncio.run(main())
