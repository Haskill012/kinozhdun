import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from playwright.sync_api import sync_playwright


DATA = Path("/data")
PROFILE = DATA / "profile"
STATE_FILE = DATA / "state.json"
SHORTS = Path("/shorts")
GROUP_ID = os.getenv("VK_GROUP_ID", "242087163")
CLIPS_URL = f"https://vk.ru/clips/club{GROUP_ID}"
SCAN_SECONDS = int(os.getenv("VK_SCAN_SECONDS", "180"))
START_DELAY_SECONDS = int(os.getenv("VK_START_DELAY_SECONDS", "90"))


def browser_context(playwright):
    PROFILE.mkdir(parents=True, exist_ok=True)
    headless = os.getenv("VK_HEADLESS", "true").lower() not in ("false", "0", "no")
    return playwright.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, locale="ru-RU",
        timezone_id="Europe/Moscow", viewport={"width": 1440, "height": 1000},
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )


def page_for(context, url=CLIPS_URL):
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3_000)
    return page


def is_authorized(page):
    if "/login" in page.url or "id.vk." in page.url:
        return False
    login_button = page.get_by_test_id("left_menu_login_button")
    return not (login_button.count() and login_button.first.is_visible())


def login(timeout):
    DATA.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = page_for(context)
        if is_authorized(page):
            print("AUTHORIZED", flush=True)
            context.close()
            return 0
        page.goto("https://id.vk.com/", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5_000)
        enter = page.get_by_text("Войти через VK ID", exact=True).first
        if enter.count() and enter.is_visible():
            enter.click()
            page.wait_for_timeout(5_000)
        print("AUTH_STAGE_URL", page.url, flush=True)
        print("AUTH_STAGE_TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[:1200], flush=True)
        print("LOGIN_URLS " + " | ".join(p.url for p in context.pages), flush=True)
        page.screenshot(path=str(DATA / "login.png"), full_page=False)
        print("LOGIN_READY /data/login.png", flush=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            page.wait_for_timeout(2_000)
            if is_authorized(page):
                page.goto(CLIPS_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(3_000)
                if is_authorized(page):
                    print("AUTHORIZED", flush=True)
                    context.close()
                    return 0
            if int(time.time()) % 10 < 2:
                page.screenshot(path=str(DATA / "login.png"), full_page=False)
        context.close()
    print("AUTH_TIMEOUT", flush=True)
    return 2


def probe():
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = page_for(context)
        page.screenshot(path=str(DATA / "probe.png"), full_page=False)
        print("AUTHORIZED", is_authorized(page), flush=True)
        print("URL", page.url, flush=True)
        print("TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[:3500], flush=True)
        print("BUTTONS", page.locator("button").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => ({text:e.innerText,aria:e.getAttribute('aria-label'),title:e.title,testid:e.dataset.testid}))"
        ), flush=True)
        context.close()


def editor_probe():
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = page_for(context)
        if not is_authorized(page):
            raise RuntimeError("authorization_required")
        page.get_by_role("button", name="Опубликовать", exact=True).click()
        page.wait_for_timeout(3_000)
        print("EDITOR_URL", page.url, flush=True)
        print("EDITOR_TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[:3500], flush=True)
        print("EDITOR_CONTROLS", page.locator("input,textarea,[contenteditable=true]").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null || e.type === 'file').map(e => ({tag:e.tagName,type:e.type,placeholder:e.placeholder,aria:e.getAttribute('aria-label'),name:e.name,accept:e.accept,testid:e.dataset.testid}))"
        ), flush=True)
        print("EDITOR_BUTTONS", page.locator("button").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => ({text:e.innerText,aria:e.getAttribute('aria-label'),title:e.title,testid:e.dataset.testid,disabled:e.disabled}))"
        ), flush=True)
        page.screenshot(path=str(DATA / "editor.png"), full_page=False)
        context.close()


def upload_probe(path):
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = page_for(context)
        if not is_authorized(page):
            raise RuntimeError("authorization_required")
        page.get_by_role("button", name="Опубликовать", exact=True).click()
        file_input = page.locator('input[type="file"]')
        file_input.wait_for(state="attached", timeout=30_000)
        file_input.set_input_files(str(path))
        page.wait_for_timeout(15_000)
        print("UPLOAD_URL", page.url, flush=True)
        print("UPLOAD_TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[-5000:], flush=True)
        print("UPLOAD_CONTROLS", page.locator("input,textarea,[contenteditable=true]").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null || e.type === 'file').map(e => ({tag:e.tagName,type:e.type,placeholder:e.placeholder,aria:e.getAttribute('aria-label'),name:e.name,value:e.value,testid:e.dataset.testid}))"
        ), flush=True)
        print("UPLOAD_BUTTONS", page.locator("button").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => ({text:e.innerText,aria:e.getAttribute('aria-label'),title:e.title,testid:e.dataset.testid,disabled:e.disabled}))"
        ), flush=True)
        page.screenshot(path=str(DATA / "upload.png"), full_page=False)
        context.close()


def draft_probe():
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = page_for(context, f"https://vk.ru/clips/upload-{GROUP_ID}")
        page.wait_for_timeout(5_000)
        print("DRAFT_URL", page.url, flush=True)
        print("DRAFT_TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[-4500:], flush=True)
        print("CHECKBOXES", page.locator('input[type="checkbox"]').evaluate_all(
            "els => els.map((e,i) => ({i,checked:e.checked,parent:e.parentElement?.parentElement?.innerText?.slice(0,300),outer:e.outerHTML.slice(0,300)}))"
        ), flush=True)
        print("DRAFT_BUTTONS", page.locator("button").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => ({text:e.innerText,disabled:e.disabled,aria:e.getAttribute('aria-label')}))"
        ), flush=True)
        page.screenshot(path=str(DATA / "draft.png"), full_page=False)
        context.close()


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"initialized": False, "files": {}}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def videos():
    return sorted((p for p in SHORTS.glob("*.mp4") if p.stat().st_size > 100_000), key=lambda p: p.stat().st_mtime)


def _meta_for(path):
    match = re.match(r"^(movie|tv)_(\d+)_\d+_", path.stem)
    db = Path("/kino-data/kinozhdun.db")
    info = {"media_type": match.group(1) if match else None, "tmdb_id": int(match.group(2)) if match else None, "title": "", "network": ""}
    if match and db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            row = con.execute("SELECT title, network FROM channel_posts WHERE media_type=? AND tmdb_id=? ORDER BY id DESC LIMIT 1", (match.group(1), int(match.group(2)))).fetchone()
            con.close()
            if row:
                info["title"] = row[0] or ""
                info["network"] = row[1] or ""
        except sqlite3.Error:
            pass
    if not info["title"]:
        info["title"] = re.sub(r"^(movie|tv)_\d+_\d+_", "", path.stem) or "Новая премьера"
    return info


def title_for(path):
    return _meta_for(path)["title"]


def upload_clip(path):
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = page_for(context)
        if not is_authorized(page):
            context.close()
            raise RuntimeError("authorization_required")

        page.get_by_role("button", name="Опубликовать", exact=True).click()
        file_input = page.locator('input[type="file"]')
        file_input.wait_for(state="attached", timeout=30_000)
        file_input.set_input_files(str(path))

        description = page.locator('textarea[placeholder="О чём ваш клип?"]')
        description.wait_for(state="visible", timeout=120_000)
        info = _meta_for(path)
        title = info["title"]
        if info["media_type"] and info["tmdb_id"]:
            card_url = f"https://kinojdun.ru/title/{info['media_type']}/{info['tmdb_id']}?from=vk-clips"
        else:
            card_url = "https://kinojdun.ru/?from=vk-clips"
        tag_title = "#" + re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", title)[:28]
        kind_tag = "#сериалы" if info["media_type"] == "tv" else "#фильмы"
        net_tag = (" #" + re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", info["network"])[:20]) if info["network"] else ""
        description.fill(
            f"Премьера: {title} 🍿\n"
            "Будете смотреть или пропустите? Пишите в комментариях!\n"
            f"Дата выхода, трейлер и напоминания в боте: {card_url}\n"
            f"{tag_title} #премьера #кино {kind_tag} #чтопосмотреть{net_tag}"
        )

        # Keep the clip on the community's main page, but do not duplicate the
        # existing independent Story publication.
        checkboxes = page.locator('input[type="checkbox"]')
        for index in range(checkboxes.count()):
            checkbox = checkboxes.nth(index)
            parent_text = checkbox.evaluate(
                "e => (e.closest('label')?.innerText || e.parentElement?.parentElement?.innerText || '')"
            )
            if "Показать на главной сообщества" in parent_text and not checkbox.is_checked():
                checkbox.click()
            if "Опубликовать в истории" in parent_text and checkbox.is_checked():
                checkbox.click()

        body = page.locator("body").inner_text()
        match = re.search(r"https://vk\.ru/(clip-\d+_\d+)", body)
        clip_url = f"https://vk.ru/{match.group(1)}" if match else None

        publish = page.get_by_role("button", name="Опубликовать", exact=True).last
        deadline = time.time() + 360
        while publish.is_disabled() and time.time() < deadline:
            page.wait_for_timeout(2_000)
        if publish.is_disabled():
            page.screenshot(path=str(DATA / "publish-disabled.png"), full_page=False)
            context.close()
            raise RuntimeError("publish_button_disabled")
        publish.click()
        page.wait_for_timeout(8_000)

        page.goto(CLIPS_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5_000)
        result_text = re.sub(r"\s+", " ", page.locator("body").inner_text())
        if "У автора пока нет клипов" in result_text:
            page.screenshot(path=str(DATA / "publish-unconfirmed.png"), full_page=False)
            context.close()
            raise RuntimeError("publication_not_confirmed")
        page.screenshot(path=str(DATA / "published.png"), full_page=False)
        print(f"CLIP_CONFIRMED {clip_url or title}", flush=True)
        context.close()
        return clip_url


def watch(once=False):
    DATA.mkdir(parents=True, exist_ok=True)
    if not once and START_DELAY_SECONDS > 0:
        print(f"START_DELAY {START_DELAY_SECONDS}", flush=True)
        time.sleep(START_DELAY_SECONDS)
    while True:
        state = load_state()
        current = videos()
        if not state["initialized"]:
            for path in current:
                state["files"][path.name] = {"status": "baseline", "mtime": path.stat().st_mtime}
            state["initialized"] = True
            save_state(state)
            print(f"BASELINE {len(current)}", flush=True)
        else:
            for path in current:
                record = state["files"].get(path.name)
                if record and record.get("status") in {"baseline", "published"}:
                    continue
                try:
                    upload_clip(path)
                    state["files"][path.name] = {"status": "published", "mtime": path.stat().st_mtime}
                    print(f"PUBLISHED {path.name}", flush=True)
                except Exception as exc:
                    state["files"][path.name] = {"status": "retry", "mtime": path.stat().st_mtime, "error": str(exc)}
                    print(f"RETRY {path.name} {exc}", flush=True)
                save_state(state)
        if once:
            return
        time.sleep(SCAN_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    lp = sub.add_parser("login")
    lp.add_argument("--timeout", type=int, default=900)
    sub.add_parser("probe")
    sub.add_parser("editor-probe")
    upload_probe_parser = sub.add_parser("upload-probe")
    upload_probe_parser.add_argument("filename")
    sub.add_parser("draft-probe")
    publish_parser = sub.add_parser("publish")
    publish_parser.add_argument("filename")
    sub.add_parser("watch")
    sub.add_parser("once")
    args = parser.parse_args()
    if args.command == "login":
        return login(args.timeout)
    if args.command == "probe":
        probe()
        return 0
    if args.command == "editor-probe":
        editor_probe()
        return 0
    if args.command == "upload-probe":
        upload_probe(SHORTS / args.filename)
        return 0
    if args.command == "draft-probe":
        draft_probe()
        return 0
    if args.command == "publish":
        path = SHORTS / args.filename
        if not path.exists():
            raise FileNotFoundError(path)
        upload_clip(path)
        return 0
    watch(once=args.command == "once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
