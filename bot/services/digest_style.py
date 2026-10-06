"""Compact Telegram digest layout with project links and source-labelled ratings."""
import html
import re
from bot.utils.formatting import safe_html, site_title_url


def telegram_text_length(text):
    plain = html.unescape(re.sub(r"<[^>]*>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def render_digest(items, date_label, weekly=False, site_url="https://kinojdun.ru"):
    heading = "Главные премьеры недели" if weekly else "Сегодня на экране"
    header = f"🎬 <b>{heading} · {safe_html(date_label)}</b>"
    calendar = html.escape(site_url.rstrip('/') + '/calendar', quote=True)
    footer = f'<a href="{calendar}">Все даты и подробности на KinoЖдун ↗</a>'
    blocks = []
    for item in (items or [])[:5]:
        raw_title = str(item.get("title") or "Без названия")
        label = safe_html(raw_title[:67] + "…" if len(raw_title) > 68 else raw_title)
        link = site_title_url(item.get("media_type"), item.get("tmdb_id"), site_url)
        title = f'<a href="{html.escape(link, quote=True)}">{label}</a>' if link else label
        try:
            rating, votes = float(item.get("vote_average") or 0), int(item.get("vote_count") or 0)
        except (ValueError, TypeError):
            rating, votes = 0, 0
        score = f"★ {rating:.1f}/10 · TMDB" if 0 < rating <= 10 and votes > 0 else "TMDB · пока без оценки"
        if 0 < votes < 50 and rating > 0:
            score += " · мало оценок"
        details = [str(item.get("tag") or ("премьера фильма" if item.get("media_type") == "movie" else "Новая серия"))]
        if weekly and item.get("date_str"):
            details.insert(0, item["date_str"])
        if item.get("network"):
            details.append(str(item["network"])[:35])
        block = f"<b>{title}</b>\n{score}\n{safe_html(' · '.join(details))}"
        if telegram_text_length("\n\n".join([header, *blocks, block, footer])) > 1000:
            break
        blocks.append(block)
    return "\n\n".join([header, *blocks, footer])
