"""Mirror published Telegram digests into MAX with a durable delivery journal."""
import asyncio
import datetime as dt
import json
import logging
import os
import signal
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from max_bot.client import MaxBotClient

log = logging.getLogger(__name__)
MOSCOW = ZoneInfo("Europe/Moscow")


def is_current_digest(post, today):
    if not post.get("published_at") or not post.get("post_text"):
        return False
    published = dt.datetime.fromisoformat(post["published_at"])
    if published.tzinfo is None:
        published = published.replace(tzinfo=dt.timezone.utc)
    day = published.astimezone(MOSCOW).date()
    if post["post_type"] == "daily_digest":
        return day == today
    if post["post_type"] == "weekly_digest":
        return day <= today and day - dt.timedelta(days=day.weekday()) == today - dt.timedelta(days=today.weekday())
    return False


class ChannelSync:
    def __init__(self, client, chat_id, source_path, journal_path,
                 site_url="https://kinojdun.ru", bot_url="https://max.ru/id5001170357_1_bot",
                 image_base="https://image.tmdb.org/t/p/w500"):
        self.client, self.chat_id = client, int(chat_id)
        self.source_path = Path(source_path)
        self.site_url, self.bot_url, self.image_base = site_url.rstrip("/"), bot_url, image_base.rstrip("/")
        Path(journal_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(journal_path, timeout=10)
        self.db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
            chat_id INTEGER NOT NULL, source_id INTEGER NOT NULL,
            state TEXT NOT NULL, message_id TEXT, error TEXT,
            updated_at TEXT NOT NULL, PRIMARY KEY(chat_id, source_id))""")
        self.db.commit()

    def candidates(self, today):
        uri = self.source_path.resolve().as_uri() + "?mode=ro"
        source = sqlite3.connect(uri, uri=True, timeout=10)
        try:
            source.row_factory = sqlite3.Row
            posts = [dict(r) for r in source.execute("""SELECT id, post_type, published_at,
                post_text, poster_path FROM channel_posts WHERE status='published'
                AND telegram_message_id IS NOT NULL
                AND post_type IN ('daily_digest','weekly_digest') ORDER BY id""")]
        finally:
            source.close()
        return [p for p in posts if is_current_digest(p, today) and not self.db.execute(
            "SELECT 1 FROM deliveries WHERE chat_id=? AND source_id=?",
            (self.chat_id, p["id"])).fetchone()]

    async def publish(self, post):
        attachments = []
        if post.get("poster_path"):
            poster = post["poster_path"]
            url = poster if poster.startswith("https://") else self.image_base + "/" + poster.lstrip("/")
            token = await self.client.upload_image_from_url(url)
            if not token:
                raise RuntimeError("Poster upload failed before delivery; will retry")
            attachments.append({"type":"image", "payload":{"token":token}})
        attachments.append({"type":"inline_keyboard", "payload":{"buttons":[
            [{"type":"link", "text":"📅 Календарь премьер", "url":self.site_url+"/calendar"}],
            [{"type":"link", "text":"🔔 Личные напоминания", "url":self.bot_url}],
        ]}})
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        # Claim before the request: an interrupted/ambiguous send is never auto-repeated.
        cursor = self.db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?,'sending',NULL,NULL,?)",
                                 (self.chat_id, post["id"], now))
        self.db.commit()
        if not cursor.rowcount:
            return False
        try:
            result = await self.client.send_message(chat_id=self.chat_id, text=post["post_text"], attachments=attachments)
            message_id = result.get("message", {}).get("body", {}).get("mid")
            if not message_id:
                raise RuntimeError("MAX response has no message ID; inspect delivery manually")
        except Exception as exc:
            self.db.execute("UPDATE deliveries SET state='failed', error=?, updated_at=? WHERE chat_id=? AND source_id=?",
                            (type(exc).__name__, now, self.chat_id, post["id"]))
            self.db.commit()
            raise
        self.db.execute("UPDATE deliveries SET state='published', message_id=?, updated_at=? WHERE chat_id=? AND source_id=?",
                        (message_id, now, self.chat_id, post["id"]))
        self.db.commit()
        log.info("MAX published source #%s as %s", post["id"], message_id)
        return True

    async def tick(self, today=None):
        count = 0
        for post in self.candidates(today or dt.datetime.now(MOSCOW).date()):
            count += bool(await self.publish(post))
        return count

    def unresolved(self):
        return self.db.execute("SELECT COUNT(*) FROM deliveries WHERE chat_id=? AND state!='published'", (self.chat_id,)).fetchone()[0]


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.getenv("MAX_CHANNEL_POSTING_ENABLED", "false").lower() != "true":
        raise RuntimeError("MAX channel posting is disabled")
    client = MaxBotClient(os.environ["MAX_BOT_TOKEN"])
    sync = ChannelSync(client, os.environ["MAX_CHANNEL_ID"],
                       os.getenv("MAX_CHANNEL_SOURCE_DB", "data/kinozhdun.db"),
                       os.getenv("MAX_CHANNEL_JOURNAL_DB", "data/kinozhdun_max_channel.db"),
                       os.getenv("SITE_BASE_URL", "https://kinojdun.ru"),
                       os.getenv("MAX_BOT_URL", "https://max.ru/id5001170357_1_bot"))
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await client.get_me()
        chat = await client._request("GET", f"/chats/{sync.chat_id}")
        member = await client._request("GET", f"/chats/{sync.chat_id}/members/me")
        if chat.get("type") != "channel" or not member.get("is_admin") or "write" not in member.get("permissions", []):
            raise RuntimeError("MAX channel admin/write permission required")
        log.info("MAX channel ready: %s (%s)", chat.get("title"), sync.chat_id)
        while not stop.is_set():
            error = None
            try:
                await sync.tick()
            except Exception as exc:
                error = type(exc).__name__
                log.exception("MAX channel synchronization failed")
            Path("data/max_channel_ready.json").write_text(json.dumps({
                "chat_id":sync.chat_id, "checked_at":dt.datetime.now(dt.timezone.utc).isoformat(),
                "ready":error is None and sync.unresolved() == 0,
                "error":error, "unresolved":sync.unresolved(),
            }))
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
    finally:
        sync.db.close()
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
