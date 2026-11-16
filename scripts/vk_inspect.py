"""Read-only VK diagnostics. Never print credentials or upload URLs."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bot.config import Settings
from bot.services.vk_client import VKClient, VKApiError


async def main():
    s = Settings.from_env()
    c = VKClient(s.VK_ACCESS_TOKEN, s.VK_GROUP_ID, user_token=s.VK_USER_TOKEN)
    try:
        checks = [
            ("groups.getById", {"group_id": c.group_id}, None),
            ("wall.get", {"owner_id": -c.group_id, "count": 5}, s.VK_USER_TOKEN),
            ("photos.getWallUploadServer", {"group_id": c.group_id}, s.VK_USER_TOKEN),
        ]
        for method, params, token in checks:
            try:
                r = await c.api_call(method, params, token=token)
                if method == "wall.get":
                    result = {"count": r.get("count"), "posts": [
                        {"id": p["id"], "text": p.get("text"),
                         "attachments": [{"type": a["type"],
                                          "url": a.get("link", {}).get("url"),
                                          "photo_id": a.get("photo", {}).get("id")}
                                         for a in p.get("attachments", [])]}
                        for p in r.get("items", [])]}
                elif method == "photos.getWallUploadServer":
                    result = {"upload_available": bool(r.get("upload_url"))}
                else:
                    groups = r if isinstance(r, list) else r.get("groups", [])
                    result = [{"id": g["id"], "name": g["name"]} for g in groups]
                print(json.dumps({"method": method, "result": result}, ensure_ascii=False))
            except VKApiError as e:
                print(json.dumps({"method": method, "error_code": e.error_code,
                                  "message": e.error_msg}, ensure_ascii=False))
            except Exception as e:
                print({"method": method, "error_type": type(e).__name__})
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
