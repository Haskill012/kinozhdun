import json
import re


def action_payload(payload):
    if isinstance(payload, str):
        try: payload = json.loads(payload)
        except (ValueError, TypeError): return ''
    action = payload.get('action', '') if isinstance(payload, dict) else ''
    return action if isinstance(action, str) else ''


class VKBotDispatcher:
    def __init__(self, handlers, group_id):
        self.handlers = handlers
        self.group_id = group_id

    async def process_update(self, update):
        if update.get('group_id') != self.group_id: return
        obj = update.get('object') or {}
        if update.get('type') == 'message_event':
            user = obj.get('user_id', 0); peer = obj.get('peer_id', 0)
            if user <= 0 or peer != user: return
            callback_id = json.dumps({k:obj[k] for k in ('event_id','user_id','peer_id')})
            await self.handlers._ensure_user(user, None, None)
            await self.handlers.dispatch_callback(callback_id, user, peer, action_payload(obj.get('payload')))
        elif update.get('type') == 'message_new':
            message = obj.get('message', obj)
            user = message.get('from_id', 0); peer = message.get('peer_id', 0)
            if message.get('out') or user <= 0 or peer != user: return
            await self.handlers._ensure_user(user, None, None)
            payload = action_payload(message.get('payload'))
            ref = message.get('ref') or ''
            if re.fullmatch(r'c_(movie|tv)_[1-9]\d*', ref):
                await self.handlers.handle_start(user, peer, None, None, payload=ref)
            elif payload:
                await self.handlers.dispatch_callback('', user, peer, payload)
            else:
                text = message.get('text', '').strip()
                if text.lower() in {'начать','start','меню'}: text = '/start'
                if text: await self.handlers.dispatch_message(user, peer, None, None, text)
