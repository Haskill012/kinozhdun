import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


DATA = Path("/data")
PROFILE = DATA / "profile"
STATE_FILE = DATA / "state.json"
SCREENSHOT = DATA / "login-qr.png"
SHORTS = Path("/shorts")
STUDIO_URL = os.getenv("DZEN_STUDIO_URL", "https://dzen.ru/profile/editor/kinojdun")
SCAN_SECONDS = int(os.getenv("DZEN_SCAN_SECONDS", "180"))


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"initialized": False, "files": {}}


def save_state(state):
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def final_videos():
    return sorted(
        (p for p in SHORTS.glob("*.mp4") if p.is_file() and p.stat().st_size > 100_000),
        key=lambda p: p.stat().st_mtime,
    )


def _meta_from_file(path):
    match = re.match(r"^(movie|tv)_(\d+)_\d+_", path.stem)
    database = Path("/kino-data/kinozhdun.db")
    info = {"media_type": match.group(1) if match else None, "tmdb_id": int(match.group(2)) if match else None, "title": "", "network": ""}
    if match and database.exists():
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            row = connection.execute(
                "SELECT title, network FROM channel_posts WHERE media_type=? AND tmdb_id=? ORDER BY id DESC LIMIT 1",
                (match.group(1), int(match.group(2))),
            ).fetchone()
            connection.close()
            if row:
                info["title"] = row[0] or ""
                info["network"] = row[1] or ""
        except sqlite3.Error:
            pass
    if not info["title"]:
        stem = re.sub(r"^(movie|tv)_\d+_\d+_", "", path.stem)
        info["title"] = stem or "Новая премьера"
    return info


def title_from_file(path):
    return _meta_from_file(path)["title"]


def browser_context(playwright):
    PROFILE.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(PROFILE),
        headless=True,
        locale="ru-RU",
        timezone_id="Europe/Moscow",
        viewport={"width": 1440, "height": 1000},
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )


def studio_page(context):
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(2_000)
    return page


def is_authorized(page):
    try:
        create = page.get_by_role("button", name=re.compile(r"Создать публикацию", re.I))
        if create.count() and create.first.is_visible():
            return True
        login = page.get_by_role("button", name=re.compile(r"^Войти$", re.I))
        return "/profile/editor/" in page.url and not (login.count() and login.first.is_visible())
    except Exception:
        return False


def dismiss_overlays(page):
    close = page.get_by_test_id("close-button")
    try:
        if close.count() and close.first.is_visible():
            close.first.click()
            page.wait_for_timeout(500)
    except Exception:
        pass


def open_video_upload(page):
    dismiss_overlays(page)
    create = page.get_by_test_id("add-publication-button")
    create.wait_for(state="visible", timeout=30_000)
    create.click()
    upload = page.get_by_text(re.compile(r"Загрузить видео", re.I), exact=True)
    upload.wait_for(state="visible", timeout=15_000)
    upload.click()
    file_input = page.locator('input[type="file"]')
    file_input.wait_for(state="attached", timeout=15_000)
    return file_input


def open_qr_login(page):
    if "passport.yandex" not in page.url:
        for login in (
            page.get_by_role("button", name=re.compile(r"Войти", re.I)),
            page.get_by_role("link", name=re.compile(r"Войти", re.I)),
        ):
            try:
                if login.count() and login.first.is_visible():
                    login.first.click()
                    page.wait_for_timeout(2_000)
                    break
            except Exception:
                continue
        yandex_id = page.get_by_text(re.compile(r"Войти через Яндекс ID", re.I))
        try:
            if yandex_id.count() and yandex_id.first.is_visible():
                yandex_id.first.click()
                page.wait_for_timeout(2_500)
        except Exception:
            pass
    candidates = [
        page.get_by_text(re.compile(r"QR[- ]?код", re.I)),
        page.get_by_role("button", name=re.compile(r"QR", re.I)),
        page.get_by_role("link", name=re.compile(r"QR", re.I)),
    ]
    for locator in candidates:
        try:
            if locator.count() and locator.first.is_visible():
                locator.first.click()
                page.wait_for_timeout(1_500)
                break
        except Exception:
            continue
    page.screenshot(path=str(SCREENSHOT), full_page=False)


def login(timeout_seconds):
    DATA.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        if is_authorized(page):
            print("AUTHORIZED", flush=True)
            context.close()
            return 0
        open_qr_login(page)
        print(f"QR_READY {SCREENSHOT}", flush=True)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            page.wait_for_timeout(2_000)
            if is_authorized(page):
                page.goto(STUDIO_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2_000)
                if is_authorized(page):
                    print("AUTHORIZED", flush=True)
                    context.close()
                    return 0
        context.close()
    print("AUTH_TIMEOUT", flush=True)
    return 2


def upload_video(path):
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        if not is_authorized(page):
            open_qr_login(page)
            context.close()
            raise RuntimeError("authorization_required")

        upload = open_video_upload(page)
        upload.set_input_files(str(path))

        publish_open_roll(page, path)
        context.close()


def roll_description(path):
    info = _meta_from_file(path)
    title = info["title"]
    if info["media_type"] and info["tmdb_id"]:
        url = f"https://kinojdun.ru/title/{info['media_type']}/{info['tmdb_id']}?from=dzen"
    else:
        url = "https://kinojdun.ru/?from=dzen"
    tag_title = "#" + re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", title)[:24]
    kind_tag = "#сериалы" if info["media_type"] == "tv" else "#кино"
    text = f"Премьера: {title}. Ждёте выход? Пишите в комментариях!\nТрекер: {url}\n{tag_title} #премьера {kind_tag}"
    if len(text) > 200:
        text = f"Премьера: {title}.\nТрекер выхода: {url}\n#премьера {kind_tag}"
    return text[:200]


def publish_open_roll(page, path):
    description = page.locator('[contenteditable="true"][data-placeholder*="Описание"]')
    description.first.wait_for(state="visible", timeout=180_000)
    description.first.fill(roll_description(path)[:200])

    publish = page.get_by_role("button", name="Опубликовать", exact=True)
    publish.wait_for(state="visible", timeout=180_000)
    deadline = time.time() + 300
    while publish.is_disabled() and time.time() < deadline:
        page.wait_for_timeout(2_000)
    if publish.is_disabled():
        raise RuntimeError("publish_button_disabled")
    publish.click()
    page.wait_for_timeout(3_000)
    setup = page.get_by_text("Настройка канала", exact=True)
    if setup.count() and setup.first.is_visible():
        checkbox = page.locator('input[type="checkbox"]').last
        if checkbox.count():
            checkbox.check(force=True)
        else:
            agreement = page.get_by_text(re.compile(r"Я принимаю условия", re.I)).first
            agreement.click()
        continue_button = page.get_by_role("button", name="Продолжить", exact=True)
        deadline = time.time() + 30
        while continue_button.is_disabled() and time.time() < deadline:
            page.wait_for_timeout(500)
        if continue_button.is_disabled():
            raise RuntimeError("channel_setup_not_ready")
        continue_button.click()
        page.wait_for_timeout(5_000)
        # The first click only saves the one-time channel setup. Submit the
        # already prepared roll once more.
        if publish.is_visible():
            publish.click()
            page.wait_for_timeout(5_000)
    page.screenshot(path=str(DATA / "after-publish.png"), full_page=False)
    if publish.is_visible():
        text = re.sub(r"\s+", " ", page.locator("body").inner_text())
        print("PUBLISH_STILL_OPEN", text[-1800:], flush=True)
        raise RuntimeError("publish_dialog_still_open")

    # A successful publication closes the roll editor. Merely clicking the
    # button is not enough: Dzen may keep the item as a draft.
    page.wait_for_timeout(2_000)
    if page.get_by_text(re.compile(r"ошиб", re.I)).count():
        raise RuntimeError("dzen_reported_error")


def publish_existing_draft(path):
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        dismiss_overlays(page)
        page.get_by_text("Публикации", exact=True).first.click()
        page.wait_for_timeout(2_000)
        page.get_by_text(re.compile(r"^Черновики", re.I)).first.click()
        page.wait_for_timeout(1_500)
        draft = page.get_by_text(re.compile(re.escape(path.stem), re.I)).first
        draft.wait_for(state="visible", timeout=30_000)
        draft.click()
        publish_open_roll(page, path)

        published = page.get_by_text(re.compile(r"^Опубликованные", re.I)).first
        published.click()
        page.wait_for_timeout(2_000)
        body = page.locator("body").inner_text()
        title = title_from_file(path)
        if title not in body and path.stem not in body:
            raise RuntimeError("publication_not_confirmed")
        print(f"PUBLISHED_CONFIRMED {title}", flush=True)
        context.close()


def probe():
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        if not is_authorized(page):
            context.close()
            raise RuntimeError("authorization_required")
        page.screenshot(path=str(DATA / "probe.png"), full_page=False)
        print("PROBE_URL", page.url, flush=True)
        print("PROBE_TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[:2500], flush=True)
        print("PROBE_BUTTONS", page.locator("button").evaluate_all(
            "els => els.map(e => ({text:e.innerText, aria:e.getAttribute('aria-label'), title:e.getAttribute('title')}))"
        ), flush=True)
        print("PROBE_EMPTY", page.locator("button").evaluate_all(
            "els => els.filter(e => !e.innerText.trim()).map(e => e.outerHTML.slice(0,700))"
        ), flush=True)
        print("PROBE_DIALOGS", page.locator('[role="dialog"], [aria-modal="true"]').count(), flush=True)
        open_video_upload(page)
        print("PROBE_OK", flush=True)
        context.close()


def verify_latest(show_drafts=False):
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        dismiss_overlays(page)
        publications = page.get_by_text("Публикации", exact=True).first
        publications.click()
        page.wait_for_timeout(3_000)
        if show_drafts:
            drafts = page.get_by_text(re.compile(r"^Черновики", re.I)).first
            drafts.click()
            page.wait_for_timeout(2_000)
        text = re.sub(r"\s+", " ", page.locator("body").inner_text())
        print("VERIFY_URL", page.url, flush=True)
        print("VERIFY_TEXT", text[:3500], flush=True)
        page.screenshot(path=str(DATA / "verify.png"), full_page=False)
        context.close()


def inspect_draft():
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        dismiss_overlays(page)
        page.get_by_text("Публикации", exact=True).first.click()
        page.wait_for_timeout(2_000)
        page.get_by_text(re.compile(r"^Черновики", re.I)).first.click()
        page.wait_for_timeout(1_500)
        page.get_by_text(re.compile(r"movie_1538497", re.I)).first.click()
        page.wait_for_timeout(2_000)
        print("DRAFT_URL", page.url, flush=True)
        print("DRAFT_TEXT", re.sub(r"\s+", " ", page.locator("body").inner_text())[:3500], flush=True)
        print("DRAFT_INPUTS", page.locator("input,textarea,[contenteditable=true]").evaluate_all(
            "els => els.map(e => ({tag:e.tagName,type:e.type,name:e.name,placeholder:e.placeholder,value:e.value,text:e.innerText,testid:e.dataset.testid}))"
        ), flush=True)
        print("DRAFT_BUTTONS", page.locator("button").evaluate_all(
            "els => els.map(e => ({text:e.innerText,aria:e.getAttribute('aria-label'),testid:e.dataset.testid,disabled:e.disabled}))"
        ), flush=True)
        page.screenshot(path=str(DATA / "draft.png"), full_page=False)
        context.close()


def inspect_published():
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        dismiss_overlays(page)
        page.get_by_text("Публикации", exact=True).first.click()
        page.wait_for_timeout(2_000)
        page.get_by_text(re.compile(r"movie_1538497", re.I)).first.click()
        page.wait_for_timeout(2_000)
        controls = page.locator("input,textarea,[contenteditable=true]").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map((e,i) => ({i,tag:e.tagName,type:e.type,placeholder:e.placeholder,value:e.value,text:e.innerText,html:e.outerHTML.slice(0,300)}))"
        )
        print("VISIBLE_CONTROLS", controls, flush=True)
        print("VISIBLE_BUTTONS", page.locator("button").evaluate_all(
            "els => els.filter(e => e.offsetParent !== null).map(e => ({text:e.innerText,testid:e.dataset.testid,disabled:e.disabled}))"
        ), flush=True)
        page.screenshot(path=str(DATA / "published-edit.png"), full_page=False)
        context.close()


def repair_published_description(path):
    with sync_playwright() as playwright:
        context = browser_context(playwright)
        page = studio_page(context)
        dismiss_overlays(page)
        page.get_by_text("Публикации", exact=True).first.click()
        page.wait_for_timeout(2_000)
        page.get_by_text(re.compile(re.escape(path.stem), re.I)).first.click()
        page.wait_for_timeout(2_000)
        editor = page.locator('[contenteditable="true"][data-placeholder*="Описание"]').first
        editor.fill(roll_description(path)[:200])
        custom_comments = page.get_by_test_id("publication-custom-comments-title-input")
        if custom_comments.count():
            custom_comments.fill("")
        save = page.get_by_test_id("publish-btn")
        deadline = time.time() + 30
        while save.is_disabled() and time.time() < deadline:
            page.wait_for_timeout(500)
        if save.is_disabled():
            raise RuntimeError("save_button_disabled")
        save.click()
        page.wait_for_timeout(5_000)
        print(f"DESCRIPTION_REPAIRED {title_from_file(path)}", flush=True)
        context.close()


def watch(once=False):
    DATA.mkdir(parents=True, exist_ok=True)
    while True:
        state = load_state()
        videos = final_videos()
        if not state["initialized"]:
            for path in videos:
                state["files"][path.name] = {"status": "baseline", "mtime": path.stat().st_mtime}
            state["initialized"] = True
            save_state(state)
            print(f"BASELINE {len(videos)}", flush=True)
        else:
            for path in videos:
                record = state["files"].get(path.name)
                if record and record.get("status") in {"baseline", "published"}:
                    continue
                try:
                    upload_video(path)
                    state["files"][path.name] = {"status": "published", "mtime": path.stat().st_mtime}
                    print(f"PUBLISHED {path.name}", flush=True)
                except Exception as exc:
                    state["files"][path.name] = {
                        "status": "retry", "mtime": path.stat().st_mtime,
                        "error": type(exc).__name__ + ":" + str(exc), "attempted_at": time.time(),
                    }
                    print(f"RETRY {path.name} {exc}", flush=True)
                save_state(state)
        if once:
            return
        time.sleep(SCAN_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    login_parser = sub.add_parser("login")
    login_parser.add_argument("--timeout", type=int, default=900)
    sub.add_parser("watch")
    sub.add_parser("once")
    sub.add_parser("probe")
    sub.add_parser("verify")
    sub.add_parser("drafts")
    sub.add_parser("draft-form")
    sub.add_parser("published-form")
    repair_parser = sub.add_parser("repair-published")
    repair_parser.add_argument("filename")
    publish_draft_parser = sub.add_parser("publish-draft")
    publish_draft_parser.add_argument("filename")
    args = parser.parse_args()
    if args.command == "login":
        return login(args.timeout)
    if args.command == "probe":
        probe()
        return 0
    if args.command == "verify":
        verify_latest()
        return 0
    if args.command == "drafts":
        verify_latest(show_drafts=True)
        return 0
    if args.command == "draft-form":
        inspect_draft()
        return 0
    if args.command == "published-form":
        inspect_published()
        return 0
    if args.command == "repair-published":
        path = SHORTS / args.filename
        repair_published_description(path)
        return 0
    if args.command == "publish-draft":
        path = SHORTS / args.filename
        if not path.exists():
            raise FileNotFoundError(path)
        publish_existing_draft(path)
        return 0
    watch(once=args.command == "once")
    return 0


if __name__ == "__main__":
    sys.exit(main())
