"""Durable website storage, separate from the running Telegram bot."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")
    except (ValueError, TypeError, AttributeError):
        return now()


def plain(value):
    import html
    return html.unescape(re.sub(r"<[^>]*>", "", value or "")).strip()


CYRILLIC_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
}


def slugify(text: str, max_length: int = 60) -> str:
    s = (text or "").lower()
    chars = []
    for c in s:
        if c in CYRILLIC_MAP:
            chars.append(CYRILLIC_MAP[c])
        elif c.isalnum() and ord(c) < 128:
            chars.append(c)
        elif c in (' ', '-', '_', ':', '.', '/', '«', '»', '"', "'", ',', '!', '?'):
            chars.append('-')
    cleaned = re.sub(r'-+', '-', ''.join(chars)).strip('-')
    return cleaned[:max_length].rstrip('-') or 'post'


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
          slug TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
          title TEXT NOT NULL, category TEXT NOT NULL, summary TEXT NOT NULL,
          body TEXT NOT NULL, source_url TEXT NOT NULL, image TEXT,
          media_type TEXT, tmdb_id INTEGER, release_date TEXT,
          published TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS titles (
          key TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()

    def publish(self, fingerprint, title, category, summary, body, source_url,
                image=None, media_type=None, tmdb_id=None, release_date=None, published=None):
        base_slug = slugify(title)
        hash_suffix = hashlib.sha256(fingerprint.encode()).hexdigest()[:8]
        slug = f"{base_slug}-{hash_suffix}"
        timestamp = published or now()
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (slug, fingerprint, title, category, summary, json.dumps(body, ensure_ascii=False),
             source_url, image, media_type, tmdb_id, release_date, timestamp, timestamp))
        self.db.commit()
        return cursor.rowcount > 0

    def articles(self, category=None, query="", limit=24, offset=0):
        clauses, params = [], []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if query:
            clauses.append("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\')")
            pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params.extend([pattern, pattern])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM articles" + where + " ORDER BY julianday(published) DESC, slug LIMIT ? OFFSET ?",
            (*params, limit, offset))]

    def article(self, slug):
        row = self.db.execute("SELECT * FROM articles WHERE slug = ?", (slug,)).fetchone()
        if not row and slug.startswith("post-"):
            row = self.db.execute("SELECT * FROM articles WHERE slug LIKE ?", (f"%{slug.removeprefix('post-')[:8]}%",)).fetchone()
        return dict(row) if row else None

    def titles(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM titles")]

    def snapshot(self, key):
        row = self.db.execute("SELECT data FROM titles WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_title(self, key, data):
        self.db.execute("INSERT OR REPLACE INTO titles VALUES (?,?,?)",
                        (key, json.dumps(data, ensure_ascii=False), now()))
        self.db.commit()

    def state(self, key, value=None):
        if value is not None:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, value))
            self.db.commit()
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def seed_guides(self, bot_url):
        guides = [
            ("tracking", "Как не пропустить новый сезон любимого сериала", "Сохраните сериал в КиноЖдуне — бот будет следить за датой следующего сезона.",
             ["Ожидание нового сезона не должно превращаться в ежедневный поиск новостей. КиноЖдун собирает ваш личный список ожидания в Telegram и проверяет изменения в каталоге TMDB.",
              "Откройте бота, отправьте название сериала и выберите нужный результат. Нажмите «Добавить в отслеживание»: бот сохранит проект и будет проверять сведения о новых сезонах и датах выхода.",
              "Когда дата появится в каталоге, бот сможет прислать уведомление. Даты могут меняться, а обновления TMDB иногда появляются с задержкой: проверяйте ссылку на источник в сообщении."]),
            ("calendar", "Дата выхода фильма: как устроен календарь премьер", "Почему даты премьер различаются и как следить за изменениями без бесконечного поиска.",
             ["У фильма может быть несколько дат выхода: фестивальная, международная, российская и цифровая. В нашем календаре используется дата, указанная в каталоге TMDB; она не гарантирует доступность на конкретной платформе или в вашей стране.",
              "Материалы на сайте формируются из данных каталога и опубликованных сообщений КиноЖдуна. Если дата изменится при следующей проверке, сайт создаст отдельный материал о переносе.",
              "Чтобы следить за конкретным фильмом, найдите его в Telegram-боте и добавьте в список ожидания. Бот также позволяет указать дату вручную."]),
            ("watchlist", "Ваш список ожидания — теперь в Telegram", "Фильмы, сериалы и новые сезоны в одном месте. А ещё списком можно поделиться с друзьями.",
             ["КиноЖдун — личный трекер кино и сериалов. Добавляйте проекты, которые хотите посмотреть, и возвращайтесь к ним в разделе «Мой список ожидания».",
              "Список можно отправить другу: бот создаёт снимок выбранных проектов без раскрытия личных данных владельца. Получатель сможет добавить отдельные фильмы или весь список в своё отслеживание.",
              "Новости и календарь на сайте помогают найти интересный проект. Telegram-бот помогает сохранить его и следить за появлением новых сведений о премьере."]),
        ]
        for key, title, summary, body in guides:
            self.publish("guide:" + key, title, "guides", summary, body, bot_url)

    def import_channel(self, database_path, channel_url):
        if not database_path or not Path(database_path).exists():
            return 0
        count = 0
        try:
            with closing(sqlite3.connect(Path(database_path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute("SELECT * FROM channel_posts WHERE status='published' AND credibility='confirmed' AND is_sponsored=0").fetchall()
            for row in rows:
                r = dict(row)
                text = plain(r.get("post_text"))
                if not text:
                    continue
                if r.get("event_type") == "weekly_digest":
                    dates = re.findall(r"\b(\d{2}\.\d{2}\.\d{4})\b", text)
                    try:
                        dates = [datetime.strptime(d, "%d.%m.%Y").date() for d in dates]
                        inconsistent = len(dates) >= 3 and any(not dates[0] <= d <= dates[1] for d in dates[2:])
                    except ValueError:
                        inconsistent = True
                    if inconsistent:
                        # Remove only this site's mirror, never touch the bot database.
                        self.db.execute("DELETE FROM articles WHERE fingerprint=?", ("channel:" + r["content_hash"],))
                        self.db.commit()
                        continue
                image = r.get("poster_path")
                source = (f"https://www.themoviedb.org/{r['media_type']}/{r['tmdb_id']}"
                          if r.get("tmdb_id") and r.get("media_type") in ("movie", "tv") else channel_url)
                count += self.publish(
                    "channel:" + r["content_hash"], plain(r["title"]),
                    "series" if r.get("media_type") == "tv" else "movies" if r.get("media_type") == "movie" else "news",
                    text[:190], [p for p in text.split("\n\n") if p], source,
                    "https://image.tmdb.org/t/p/w780" + image if image and image.startswith("/") else None,
                    r.get("media_type"), r.get("tmdb_id"), r.get("air_date"),
                    timestamp(r.get("published_at") or r.get("created_at")))
        except sqlite3.Error:
            # The bot may be creating/migrating its tables; retry next cycle.
            return count
        return count
