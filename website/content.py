"""Durable website storage, separate from the running Telegram bot."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path


def today():
    return datetime.now(timezone(timedelta(hours=3))).date()


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


def clean_post_paragraphs(raw_text: str, payload_json: str = None, known_titles: dict = None) -> list[str]:
    if not raw_text:
        return []

    items_map = {}
    if payload_json:
        try:
            payload_data = json.loads(payload_json)
            if isinstance(payload_data, list):
                for it in payload_data:
                    title = it.get('title')
                    media = it.get('media_type')
                    tmdb_id = it.get('tmdb_id')
                    if title and media and tmdb_id:
                        items_map[str(title).strip()] = (str(media), int(tmdb_id))
        except Exception:
            pass

    if known_titles:
        for title, val in known_titles.items():
            t_clean = str(title).strip()
            if t_clean and t_clean not in items_map:
                items_map[t_clean] = val

    paragraphs = [p.strip() for p in raw_text.split('\n\n') if p.strip()]
    cleaned_paragraphs = []

    # Match longer titles first
    sorted_titles = sorted(items_map.items(), key=lambda x: len(x[0]), reverse=True)

    for p in paragraphs:
        block = p
        # 1. Normalize absolute kinojdun.ru links to relative site paths
        block = re.sub(r'https?://(?:www\.)?kinojdun\.ru(/title/[a-z]+/\d+|/calendar)', r'\1', block)

        # 2. Check and wrap titles
        for title, (media, tmdb_id) in sorted_titles:
            link = f'/title/{media}/{tmdb_id}'
            if link in block:
                continue

            escaped = re.escape(title)
            # Case 2a: Inside <b>Title</b>
            if re.search(rf'<b>\s*{escaped}\s*</b>', block):
                block = re.sub(rf'<b>\s*{escaped}\s*</b>', f'<a href="{link}"><b>{title}</b></a>', block, count=1)
            # Case 2b: Inside «Title»
            elif re.search(rf'«\s*{escaped}\s*»', block):
                block = re.sub(rf'«\s*{escaped}\s*»', f'«<a href="{link}"><b>{title}</b></a>»', block, count=1)
            # Case 2c: On its own line or before newline
            elif re.search(rf'(?m)^\s*{escaped}\s*(?:\r?\n|$)', block):
                block = re.sub(rf'(?m)^\s*{escaped}\s*(?=\r?\n|$)', f'<a href="{link}"><b>{title}</b></a>', block, count=1)
            # Case 2d: In text if title is sufficiently distinctive
            elif len(title) >= 3 and title in block:
                pattern = rf'(?<!/)(?<![\w/]){escaped}(?![\w/])'
                if re.search(pattern, block):
                    block = re.sub(pattern, f'<a href="{link}"><b>{title}</b></a>', block, count=1)

        # 3. Footer calendar link
        if 'Все даты и подробности на KinoЖдун' in block and '/calendar' not in block:
            if 'Все даты и подробности на KinoЖдун ↗' in block:
                block = block.replace('Все даты и подробности на KinoЖдун ↗', '<a href="/calendar">Все даты и подробности на KinoЖдун ↗</a>', 1)
            else:
                block = block.replace('Все даты и подробности на KinoЖдун', '<a href="/calendar">Все даты и подробности на KinoЖдун ↗</a>', 1)

        cleaned_paragraphs.append(block)

    return cleaned_paragraphs


def extract_digest_summary(text: str, title: str = "", max_len: int = 180) -> str:
    cleaned = plain(text)
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    if not paragraphs:
        return title or ""

    candidate = None
    for p in paragraphs:
        # Ignore emoji headers like "🍿 Что выходит сегодня..." or "🎬 Сегодня на экране..."
        if re.match(r"^[🎬🍿🔥📅📢]?\s*(Что выходит|Главные премьеры|Сегодня на экране|Что посмотреть)", p):
            continue
        # Ignore list item blocks or items with ratings/TMDB lines or footer links
        if (p.startswith(("📺", "🎬", "•", "-", "└"))
                or "★" in p or "TMDB" in p
                or "Все даты" in p or "подробности" in p or "t.me" in p):
            continue
        candidate = p
        break

    if not candidate:
        if any(h in (title or "") for h in ("Что выходит сегодня", "Сегодня на экране", "Что посмотреть")):
            candidate = "Главные кино- и телепремьеры дня по данным трекера КиноЖдун."
        elif "Главные премьеры недели" in (title or ""):
            candidate = "Самые ожидаемые новинки кино и сериалов этой недели по данным трекера КиноЖдун."
        else:
            candidate = paragraphs[0].split("\n")[0].strip()

    # Clean leading emoji
    candidate = re.sub(r"^[🎬🍿🔥📅📢\s]+", "", candidate).strip()

    # Try taking the first sentence if it fits cleanly
    sentences = re.split(r"(?<=[.!?])\s+", candidate)
    if sentences and 25 <= len(sentences[0]) <= max_len:
        return sentences[0].strip()

    if len(candidate) <= max_len:
        return candidate

    # Cut strictly by word boundary with ellipsis
    truncated = candidate[:max_len].rsplit(" ", 1)[0].rstrip(" ,.-:;!?")
    return (truncated + "…") if truncated else candidate[:max_len]


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
        CREATE INDEX IF NOT EXISTS articles_title ON articles (media_type, tmdb_id);
        CREATE TABLE IF NOT EXISTS titles (
          key TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS catalog (
          key TEXT PRIMARY KEY, data TEXT NOT NULL, position INTEGER NOT NULL,
          published TEXT, added TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.repair_episode_articles()
        self.purge_corrupted_digests()
        self.repair_digest_links()
        self.db.commit()

    def repair_episode_articles(self):
        """Correct legacy TMDB episode headlines, preserving URLs and publication dates."""
        for row in self.db.execute("SELECT * FROM articles WHERE media_type='tv' AND fingerprint LIKE 'tmdb:%'").fetchall():
            match = re.search(r"Речь о (\d+)-м эпизоде (\d+)-го сезона", row["summary"])
            if not match or not row["release_date"] or not (":date:" in row["fingerprint"] or ":release:" in row["fingerprint"]):
                continue
            episode, season = map(int, match.groups())
            original = re.match(r"«(.+?)»", row["title"])
            if not original:
                continue
            released = datetime.fromisoformat(row["release_date"]).strftime("%d.%m.%Y")
            heading = f"«{original[1]}»: {season}-й сезон, {episode}-я серия — {released}"
            body = json.loads(row["body"])
            # Older versions compared dates of different episodes as a postponement.
            body = [p for p in body if not p.startswith("Ранее в каталоге была указана дата")]
            if episode > 1:
                clarification = "Это дата очередной серии, а не премьера нового сезона."
                if clarification not in body:
                    body.insert(1, clarification)
            if row["title"] != heading or json.loads(row["body"]) != body:
                self.db.execute("UPDATE articles SET title=?, body=?, updated=? WHERE slug=?",
                                (heading, json.dumps(body, ensure_ascii=False), now(), row["slug"]))

    def purge_corrupted_digests(self):
        """Purge invalid daily digests with fabricated releases, talk shows or broken word chops."""
        rows = self.db.execute("SELECT slug, fingerprint, title, summary, body FROM articles WHERE fingerprint LIKE 'channel:%' OR slug LIKE '%vyhodit-segodnya%'").fetchall()
        for row in rows:
            text = (row["summary"] or "") + " " + (row["body"] or "")
            is_corrupt = (
                ("chto-vyhodit-segodnya" in row["slug"] and "d2d6d01c" in row["slug"])
                or "мифическим утром" in text
                or "Good Mythical Morning" in text
                or "Монолог фа" in text
                or bool(re.search(r"[\u4e00-\u9fff]", text))
            )
            if is_corrupt:
                self.db.execute("DELETE FROM articles WHERE slug=?", (row["slug"],))
        self.db.commit()

    def repair_digest_links(self):
        """Ensure project cards and calendar links in digest articles are preserved and linked."""
        known_titles = {}
        for row in self.db.execute("SELECT data FROM titles").fetchall():
            try:
                t = json.loads(row[0])
                if t.get("title") and t.get("media_type") and t.get("id"):
                    known_titles[str(t["title"]).strip()] = (str(t["media_type"]), int(t["id"]))
            except Exception:
                pass

        rows = self.db.execute("SELECT slug, title, summary, body FROM articles WHERE category IN ('news', 'series', 'movies')").fetchall()
        for row in rows:
            try:
                body = json.loads(row["body"])
            except Exception:
                continue
            if not isinstance(body, list):
                continue
            raw_text = "\n\n".join(body)
            is_digest = any(h in row["title"] for h in ("Что посмотреть", "Что выходит", "Сегодня на экране", "Главные премьеры"))
            has_calendar = "Все даты и подробности на KinoЖдун" in raw_text
            if not (is_digest or has_calendar):
                continue

            cleaned_paragraphs = clean_post_paragraphs(raw_text, known_titles=known_titles)
            new_summary = extract_digest_summary(raw_text, row["title"]) if is_digest else row["summary"]
            if cleaned_paragraphs != body or new_summary != row["summary"]:
                self.db.execute("UPDATE articles SET body=?, summary=?, updated=? WHERE slug=?",
                                (json.dumps(cleaned_paragraphs, ensure_ascii=False), new_summary, now(), row["slug"]))
        self.db.commit()

    def publish(self, fingerprint, title, category, summary, body, source_url,
                image=None, media_type=None, tmdb_id=None, release_date=None, published=None, item=None):
        base_slug = slugify(title)
        hash_suffix = hashlib.sha256(fingerprint.encode()).hexdigest()[:8]
        slug = f"{base_slug}-{hash_suffix}"
        timestamp = published or now()
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (slug, fingerprint, title, category, summary, json.dumps(body, ensure_ascii=False),
             source_url, image, media_type, tmdb_id, release_date, timestamp, timestamp))
        created = cursor.rowcount > 0
        if not created:
            self.db.execute(
                "UPDATE articles SET title=?, category=?, summary=?, body=?, source_url=?, image=?, updated=? WHERE fingerprint=?",
                (title, category, summary, json.dumps(body, ensure_ascii=False), source_url, image, now(), fingerprint))
        self.ensure_news_card(media_type, tmdb_id, title, source_url, image, release_date, item)
        self.db.commit()
        return created

    def ensure_news_card(self, media, tmdb_id, title, source_url, image=None, release=None, item=None):
        if media not in ("movie", "tv") or not isinstance(tmdb_id, int) or tmdb_id <= 0:
            return
        key = f"{media}:{tmdb_id}"
        existing = self.catalog_item(key, False)
        if existing and existing.get("published") and not existing.get("needs_details"):
            return
        if item is None:
            item = self.snapshot(key)
            if item and "first_release" not in item:
                item = {**item, "needs_details": True}
        if not item:
            item = ({**existing, "needs_details": True} if existing else None) or {"key": key, "id": tmdb_id, "media_type": media,
                                "title": title, "source_url": source_url, "image": image,
                                "release_date": release, "needs_details": True}
        position = self.db.execute("SELECT COALESCE(MAX(position),0)+1 FROM catalog").fetchone()[0]
        # Use a full timestamp: news cards do not consume the daily discovery quota.
        self.db.execute("INSERT OR IGNORE INTO catalog VALUES (?,?,?,?,?)",
                        (key, json.dumps(item, ensure_ascii=False), position, now(), now()))
        self.db.execute("UPDATE catalog SET data=?, published=COALESCE(published,?) WHERE key=?",
                        (json.dumps(item, ensure_ascii=False), now(), key))

    def has_news_title(self, media, tmdb_id):
        return self.db.execute("SELECT 1 FROM articles WHERE media_type=? AND tmdb_id=? LIMIT 1",
                               (media, tmdb_id)).fetchone() is not None

    def news_titles(self):
        return [(r[0], r[1]) for r in self.db.execute(
            "SELECT DISTINCT media_type, tmdb_id FROM articles "
            "WHERE media_type IN ('movie','tv') AND tmdb_id > 0")]

    def restore_news_cards(self):
        """Repair older articles too, using their snapshots before fetching new details."""
        for row in self.db.execute(
                "SELECT * FROM articles WHERE media_type IN ('movie','tv') AND tmdb_id > 0 "
                "ORDER BY published DESC").fetchall():
            self.ensure_news_card(row["media_type"], row["tmdb_id"], row["title"],
                                   row["source_url"], row["image"], row["release_date"])
        self.db.commit()

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

    def title_articles(self, media, tmdb_id, limit=20, offset=0):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM articles WHERE media_type=? AND tmdb_id=? "
            "ORDER BY julianday(published) DESC, slug LIMIT ? OFFSET ?",
            (media, tmdb_id, limit, offset))]

    def title_articles_count(self, media, tmdb_id):
        return self.db.execute("SELECT COUNT(*) FROM articles WHERE media_type=? AND tmdb_id=?",
                               (media, tmdb_id)).fetchone()[0]

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

    def delete_title(self, key):
        self.db.execute("DELETE FROM titles WHERE key = ?", (key,))
        self.db.commit()

    def state(self, key, value=None):
        if value is not None:
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, value))
            self.db.commit()
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def catalog(self, published_only=True):
        where = " WHERE published IS NOT NULL" if published_only else ""
        return [{**json.loads(r["data"]), "published": r["published"]}
                for r in self.db.execute("SELECT * FROM catalog" + where + " ORDER BY position")]

    def catalog_item(self, key, published_only=True):
        row = self.db.execute("SELECT * FROM catalog WHERE key=?", (key,)).fetchone()
        if not row or (published_only and not row["published"]):
            return None
        return {**json.loads(row["data"]), "published": row["published"]}

    def queue_title(self, item):
        position = self.db.execute("SELECT COALESCE(MAX(position),0)+1 FROM catalog").fetchone()[0]
        self.db.execute("INSERT OR IGNORE INTO catalog VALUES (?,?,?,?,?)",
                        (item["key"], json.dumps(item, ensure_ascii=False), position, None, now()))
        self.db.commit()

    def update_catalog(self, item):
        self.db.execute("UPDATE catalog SET data=? WHERE key=?",
                        (json.dumps(item, ensure_ascii=False), item["key"]))
        self.db.commit()

    def release_catalog(self, daily=3):
        # A Moscow calendar day quota survives restarts. No catch-up burst.
        day = today().isoformat()
        with self.db:
            used = max(int(self.state("cards_published:" + day) or 0),
                       self.db.execute("SELECT COUNT(*) FROM catalog WHERE published=?", (day,)).fetchone()[0])
            rows = self.db.execute("SELECT key FROM catalog WHERE published IS NULL ORDER BY position LIMIT ?",
                                   (max(0, daily-used),)).fetchall()
            self.db.executemany("UPDATE catalog SET published=? WHERE key=?", [(day, r[0]) for r in rows])
            self.db.execute("INSERT OR REPLACE INTO state VALUES (?,?)", ("cards_published:" + day, str(used + len(rows))))
        return len(rows)

    def open_initial_catalog(self):
        """One-time migration: make the initial reviewed collection available."""
        if self.state("initial_catalog_visible"):
            return
        seed = json.loads(Path(__file__).with_name("catalog_seed.json").read_text(encoding="utf-8"))
        with self.db:
            self.db.executemany("UPDATE catalog SET published=COALESCE(published,?) WHERE key=?",
                                [(today().isoformat(), item["key"]) for item in seed["titles"]])
            self.db.execute("INSERT INTO state VALUES (?,?)", ("initial_catalog_visible", now()))

    def seed_live_catalog(self):
        news = set(self.news_titles())
        if self.state("catalog_selected") or any((t["media_type"], t["id"]) not in news for t in self.catalog(False)):
            return
        path = Path(__file__).with_name("catalog_seed.json")
        if not path.exists():
            return
        seed = json.loads(path.read_text(encoding="utf-8"))
        for item in seed["titles"]:
            self.queue_title(item)
            self.save_title(item["key"], item)
        self.state("catalog_selected", seed["selected_at"])

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

    def seed_catalog(self, bot_url):
        # 1. Clean up obsolete / past-year catalog entries from both titles and articles
        # Live snapshots are retained; expired dates are removed below.

        obsolete_fingerprints = [
            "catalog:tv:95396", "catalog:tv:111803", "catalog:tv:100088", "catalog:tv:66732",
            "catalog:tv:119051", "catalog:tv:106379", "catalog:tv:76479", "catalog:tv:94997",
            "catalog:movie:83533", "catalog:movie:533533"
        ]
        for fp in obsolete_fingerprints:
            self.db.execute("DELETE FROM articles WHERE fingerprint = ?", (fp,))

        # 2. Delete any titles whose release_date has already passed
        today_iso = today().isoformat()
        for row in self.db.execute("SELECT key, data FROM titles").fetchall():
            try:
                t = json.loads(row[1])
                if t.get("release_date") and t["release_date"] < today_iso and not self.catalog_item(row[0], False):
                    self.db.execute("DELETE FROM titles WHERE key = ?", (row[0],))
            except Exception:
                pass
        self.db.commit()

        movies = [
            (1400837, "Чужая мама", "2026-10-07",
             "Бэла, 8-летняя девочка из семьи, переживающей супружеский кризис, сталкивается со зловещей сущностью, появляющейся из её шкафа. Эта сущность становится всё более угрожающей для неё и её близких.",
             "/xM23YJnhlJgf8gOFE34IZBMxUy3.jpg", "/smZ8BT4Vzw4iCEppTLCnN8jNYtn.jpg"),
            (1281331, "Социальная расплата", "2026-10-07",
             "Фрэнсис Хоген, молодая сотрудница Facebook, обращается за помощью к репортеру Wall Street Journal, чтобы начать расследование, раскрывающее самые охраняемые секреты гиганта соцсетей.",
             "/nZ8cQbjAQHRuSqwxvuYhOfxyhfW.jpg", "/wXTaGcqX3jvdXSKCJAkl5jZyrKp.jpg"),
            (1153576, "Уличный боец", "2026-10-13",
             "Уличные бойцы Рю и Кен встречаются вновь и оказываются втянуты в турнир World Warrior. За зрелищными поединками скрывается опасный заговор, угрожающий будущему всех участников.",
             "/2qGRXNrhyg3N5KNAZuahmUvf15s.jpg", "/zDE9hd1SG9695YncbZGjSf7Z9Jk.jpg"),
            (1255833, "Кит: Во тьме глубин", "2026-10-14",
             "Молодой аквалангист Джей Гардинер погружается в океан и оказывается внутри гигантского кашалота. У него есть всего час, чтобы найти путь наружу, пока не закончился кислород.",
             "/sqrx5rMkdSSaXTmd19jAbUx5Cpc.jpg", "/dUzzwJpX4Fiet2QJy5P1TxpW1Qa.jpg"),
            (1400940, "Клэйфейс", "2026-10-21",
             "После тяжелой травмы молодой актёр Мэтт Хейген соглашается на экспериментальное лечение, превращающее его тело в податливую глину, а жажда мести делает его опасным монстром.",
             "/t6Dso7ojC23ztZSZtf6sje9iTPN.jpg", "/1A7s8zG4PF6YoJrncrTO6N4r0Sx.jpg"),
            (1294189, "Мангуст", "2026-10-29",
             "Обвинённый в преступлении, которого он не совершал, герой войны Райан Флэнаган пускается в бега. Полиция идёт по его следу, а миллионы зрителей следят за погоней в прямом эфире.",
             "/awpG3pnvPuOcfce76mSpS69NQ3E.jpg", "/iRIhPqqoUHiFBxn8oYf3gCQnaKk.jpg"),
            (1170608, "Дюна: Часть третья", "2026-12-15",
             "Продолжение монументальной фантастической саги Дени Вильнёва по роману Фрэнка Герберта «Мессия Дюны». Пол Атрейдес правит галактической империей, сталкиваясь с заговорами и судьбой.",
             "/x50ig6nAMNCP3ihDXKfUjnKM4Ud.jpg", "/i5E9H7Ik0u61ylDDTbmUpTL3Yw.jpg"),
            (1003596, "Мстители: Доктор Дум", "2026-12-16",
             "Мстители, Люди Икс, Фантастическая четвёрка, вакандцы и Новые Мстители объединяются, чтобы противостоять Доктору Думу в масштабном кроссовере киновселенной Marvel.",
             "/itU2A8Yco43cAuDfVcYBXlpJzH.jpg", "/s4v0UX1anfXm0UvloLsTTJ4v222.jpg"),
        ]

        series = [
            (288673, "Кэрри", "1 сезон", "2026-10-07",
             "После загадочного пожара на школьном выпускном полиция пытается восстановить цепочку событий. Кэрри Уайт, выросшая под строгим контролем матери, впервые сталкивается с внешним миром.",
             "/qrmBRcNOQ3eHv4zdXlO1anTELq0.jpg", "/x4HuDkzyAfGfZpuJURU8mg43q6H.jpg"),
            (285322, "Вглубь", "1 сезон", "2026-10-08",
             "Когда таинственное морское существо начинает наводить ужас на жителей отдалённого городка, опытный рыбак должен вступить в борьбу, чтобы защитить семью и привычный уклад жизни.",
             "/qadm9To9UfMVenVzGVLt0m0iuxv.jpg", "/cn0feYcDvVzVjUDoXa1O8sRgzz.jpg"),
            (213375, "Квест Вижна", "1 сезон", "2026-10-14",
             "После возвращения к жизни Вижн пытается восстановить свою личность и воспоминания, сталкиваясь с новыми угрозами и тайнами своего происхождения во вселенной Marvel.",
             "/WGyAyBPncfuu8MZhLY9RtfZPM0.jpg", "/v50p9hearMiu6BlYfp4O7FACmXl.jpg"),
            (213562, "Хрустальное озеро", "1 сезон", "2026-10-15",
             "Приквел культовой франшизы ужасов. История событий в лагере у Хрустального озера, положивших начало одной из самых пугающих легенд кинематографа.",
             "/3ENhExiD2fcjk5FX0AcAXcvLu9N.jpg", "/3qbNgNqMFrEEhIl43UKD9oxCkOw.jpg"),
            (314360, "Яга", "1 сезон", "2026-10-23",
             "Миф о Бабе-Яге оживает в наши дни: частный детектив расследует исчезновение молодого наследника в прибрежном городке, сталкиваясь с древней магией и скрытыми тайнами.",
             "/aERpptLNgIbrIuSeP1eWT9TmRXx.jpg", "/iqXeoigqrsRw81lMYVMs0Vg7Gdy.jpg"),
            (292741, "Ноктюрн", "1 сезон", "2026-10-29",
             "Когда жертва опасного преступника неожиданно оказывается жива, детектив Йона Линна спешит найти пропавших, пока его напарница ведёт смертельно опасную игру под прикрытием.",
             "/ueZzyDf0sAAu6FLUAD0L4ux4c8y.jpg", "/DCSa6Fd3NN075JOqcJqO3VU6fM.jpg"),
            (171802, "Бегущий по лезвию 2099", "1 сезон", "2026-11-25",
             "Продолжение культовой вселенной Ридли Скотта. В возрождённом Лос-Анджелесе будущего беглянка Кора объединяется с репликантом Олвен в борьбе за выживание и раскрытие заговора.",
             "/8yqy4ddY1LV147SxWvModlFZV1D.jpg", "/uOlIq21Rx0Sl7y39b1znTfQYGb7.jpg"),
            (224377, "Гарри Поттер", "1 сезон", "2026-12-25",
             "Новая многосерийная адаптация литературной саги Дж. К. Роулинг от HBO. Первый сезон подробно погружает в первый год обучения юного волшебника в школе чародейства и волшебства Хогвартс.",
             "/SJCnXVBJZh7X7ePLt6XMp6TZAj.jpg", "/g0VmjKGMyipJSlPwlQvlLBvXTAQ.jpg"),
        ]

        for tmdb_id, title, release_date, overview, poster, backdrop in movies:
            if not self._needs_catalog_seed(f"movie:{tmdb_id}", release_date):
                continue
            image_url = f"https://image.tmdb.org/t/p/w1280{backdrop}" if backdrop else f"https://image.tmdb.org/t/p/w500{poster}"
            source_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
            body = [
                overview,
                f"По данным каталога TMDB, запланированная дата премьеры — {release_date}.",
                "Сведения о дате выхода могут меняться создателями проекта. Сохраните фильм в список ожидания КиноЖдуна в Telegram, чтобы не пропустить премьеру."
            ]
            self.publish(
                fingerprint=f"catalog:movie:{tmdb_id}",
                title=f"«{title}»: дата выхода и подробности премьеры",
                category="movies",
                summary=overview[:185] + ("…" if len(overview) > 185 else ""),
                body=body,
                source_url=source_url,
                image=image_url,
                media_type="movie",
                tmdb_id=tmdb_id,
                release_date=release_date,
                published="2026-10-05T12:00:00+00:00"
            )
            self.save_title(f"movie:{tmdb_id}", {
                "key": f"movie:{tmdb_id}",
                "id": tmdb_id,
                "media_type": "movie",
                "title": title,
                "overview": overview,
                "release_date": release_date,
                "image": image_url,
                "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                "status": "In Production",
                "source_url": source_url
            })

        for tmdb_id, title, season_note, release_date, overview, poster, backdrop in series:
            if not self._needs_catalog_seed(f"tv:{tmdb_id}", release_date):
                continue
            image_url = f"https://image.tmdb.org/t/p/w1280{backdrop}" if backdrop else f"https://image.tmdb.org/t/p/w500{poster}"
            source_url = f"https://www.themoviedb.org/tv/{tmdb_id}"
            full_title = f"{title} ({season_note})"
            body = [
                overview,
                f"Согласно каталогу TMDB, выход новых эпизодов ({season_note}) запланирован на {release_date}.",
                "Точный график выхода серий зависит от вещателя и стриминговой платформы. Добавьте проект в отслеживание КиноЖдуна в Telegram — бот напомнит о премьере."
            ]
            self.publish(
                fingerprint=f"catalog:tv:{tmdb_id}",
                title=f"«{title}» ({season_note}): дата выхода нового сезона",
                category="series",
                summary=overview[:185] + ("…" if len(overview) > 185 else ""),
                body=body,
                source_url=source_url,
                image=image_url,
                media_type="tv",
                tmdb_id=tmdb_id,
                release_date=release_date,
                published="2026-10-05T12:00:00+00:00"
            )
            self.save_title(f"tv:{tmdb_id}", {
                "key": f"tv:{tmdb_id}",
                "id": tmdb_id,
                "media_type": "tv",
                "title": full_title,
                "overview": overview,
                "release_date": release_date,
                "image": image_url,
                "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                "status": "In Production",
                "source_url": source_url
            })

    def _needs_catalog_seed(self, key, release_date):
        # The initial catalogue must never replace live TMDB data or resurrect
        # a title removed by the editor. Its article records prior seeding.
        return (release_date >= today().isoformat()
                and self.snapshot(key) is None
                and self.db.execute("SELECT 1 FROM articles WHERE fingerprint = ?",
                                    ("catalog:" + key,)).fetchone() is None)

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
                text = r.get("post_text") or ""
                if not text:
                    continue
                plain_text = plain(text)
                if r.get("event_type") == "weekly_digest":
                    dates = re.findall(r"\b(\d{2}\.\d{2}\.\d{4})\b", plain_text)
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
                if r.get("event_type") == "daily_digest":
                    if (any(bad in plain_text for bad in ("мифическим утром", "Good Mythical Morning"))
                            or bool(re.search(r"[\u4e00-\u9fff]", plain_text))):
                        self.db.execute("DELETE FROM articles WHERE fingerprint=?", ("channel:" + r["content_hash"],))
                        self.db.commit()
                        continue
                image = r.get("poster_path")
                source = (f"https://www.themoviedb.org/{r['media_type']}/{r['tmdb_id']}"
                          if r.get("tmdb_id") and r.get("media_type") in ("movie", "tv") else channel_url)
                summary = extract_digest_summary(text, plain(r["title"]))
                body = clean_post_paragraphs(text, r.get("payload"))
                count += self.publish(
                    "channel:" + r["content_hash"], plain(r["title"]),
                    "series" if r.get("media_type") == "tv" else "movies" if r.get("media_type") == "movie" else "news",
                    summary, body, source,
                    "https://image.tmdb.org/t/p/w780" + image if image and image.startswith("/") else None,
                    r.get("media_type"), r.get("tmdb_id"), r.get("air_date"),
                    timestamp(r.get("published_at") or r.get("created_at")))

                if r.get("payload"):
                    try:
                        payload_items = json.loads(r["payload"])
                        if isinstance(payload_items, list):
                            for it in payload_items:
                                m = it.get("media_type")
                                tid = it.get("tmdb_id")
                                ttitle = it.get("title")
                                if m and tid and ttitle:
                                    timg = ("https://image.tmdb.org/t/p/w780" + it["poster_path"]
                                            if it.get("poster_path") and str(it["poster_path"]).startswith("/") else None)
                                    tsrc = f"https://www.themoviedb.org/{m}/{tid}"
                                    self.ensure_news_card(m, int(tid), ttitle, tsrc, timg)
                    except Exception:
                        pass
        except sqlite3.Error:
            # The bot may be creating/migrating its tables; retry next cycle.
            return count
        return count
