from html import escape

from website import views


def bots_page(config, source=""):
    source = source if source in {"dzen", "vk-clips", "direct"} else "direct"
    labels = {
        "dzen": "Вы пришли из ролика в Дзене",
        "vk-clips": "Вы пришли из VK Клипов",
        "direct": "Выберите удобный мессенджер",
    }
    cards = (
        ("Telegram", "Уведомления о фильмах и сериалах в Telegram", config["bot_url"], "tg"),
        ("MAX", "Следите за премьерами в MAX", config["max_bot_url"], "max"),
        ("ВКонтакте", "Откройте бота в сообщениях сообщества", config["vk_bot_url"], "vk"),
    )
    icons = {
        "tg": (
            '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#2AABEE"/>'
            '<path fill="#fff" d="M18.5 6.4 16.6 17c-.14.75-.53.93-1.07.58l-2.9-2.14-1.4 1.35c-.16.16-.29.29-.59.29l.21-2.96 5.39-4.87c.23-.21-.05-.33-.36-.12L9.22 13.3l-2.87-.9c-.62-.2-.64-.62.13-.92l11.2-4.32c.52-.19.97.13.82 1.24Z"/></svg>'
        ),
        "max": '<span class="brand-letter" aria-hidden="true">M</span>',
        "vk": '<span class="brand-vk" aria-hidden="true">VK</span>',
    }
    buttons = "".join(
        '<a class="bot-hub-card bot-hub-' + kind + '" href="' + escape(url, quote=True) + '" '
        'target="_blank" rel="noopener" data-bot-destination="' + kind + '">'
        '<span class="bot-hub-icon">' + icons[kind] + '</span>'
        '<span><strong>' + escape(name) + '</strong><small>' + escape(summary) + '</small></span>'
        '<b aria-hidden="true">→</b></a>'
        for name, summary, url, kind in cards
    )
    content = f'''
    <style>
      .bot-hub{{max-width:760px;margin:0 auto;padding:72px 20px 96px;text-align:center}}
      .bot-hub .eyebrow{{display:inline-flex;margin-bottom:18px}}
      .bot-hub h1{{font-size:clamp(38px,7vw,72px);line-height:.98;margin:0 auto 22px;max-width:720px}}
      .bot-hub-lead{{font-size:clamp(18px,2.5vw,23px);line-height:1.5;max-width:620px;margin:0 auto 34px;color:var(--muted,#777)}}
      .bot-hub-grid{{display:grid;gap:14px;text-align:left}}
      .bot-hub-card{{display:grid;grid-template-columns:54px 1fr auto;align-items:center;gap:16px;padding:18px 20px;border:1px solid #d9ddd9;border-radius:18px;background:#fff;color:#121614!important;text-decoration:none;transition:.18s transform,.18s border-color,.18s box-shadow}}
      .bot-hub-card:hover{{transform:translateY(-2px);border-color:#a7ef46;box-shadow:0 12px 34px rgba(0,0,0,.09)}}
      .bot-hub-icon{{width:54px;height:54px;display:grid;place-items:center}}
      .bot-hub-icon svg{{display:block;width:46px;height:46px}}
      .bot-hub-icon .brand-letter,.bot-hub-icon .brand-vk{{width:46px;height:46px;border-radius:13px;display:grid;place-items:center;color:#fff;font-weight:900;line-height:1}}
      .bot-hub-icon .brand-letter{{background:linear-gradient(145deg,#7047ff 10%,#405dff 55%,#1688ff);font-size:24px}}
      .bot-hub-icon .brand-vk{{background:#07f;font-size:15px;letter-spacing:-1px}}
      .bot-hub-card strong{{display:block;font-size:20px;margin-bottom:4px;color:#121614!important}}
      .bot-hub-card small{{display:block;font-size:15px;line-height:1.35;color:#5b655f!important}}
      .bot-hub-card b{{font-size:28px;font-weight:500;color:#46514b!important}}
      .bot-hub-note{{margin:24px auto 0;font-size:14px;color:var(--muted,#777)}}
      @media(max-width:520px){{.bot-hub{{padding-top:48px}}.bot-hub-card{{grid-template-columns:48px 1fr auto;padding:15px}}.bot-hub-icon{{width:48px;height:48px}}.bot-hub-icon svg,.bot-hub-icon .brand-letter,.bot-hub-icon .brand-vk{{width:42px;height:42px}}}}
    </style>
    <main class="bot-hub" data-source="{escape(source, quote=True)}">
      <span class="eyebrow lime">{escape(labels[source])}</span>
      <h1>Не пропускайте<br>то, что ждёте.</h1>
      <p class="bot-hub-lead">Выберите удобный бот. Он напомнит о премьере фильма, новом сезоне или серии.</p>
      <div class="bot-hub-grid">{buttons}</div>
      <p class="bot-hub-note">Бесплатно · Без лишних сообщений · Отписаться можно в любой момент</p>
    </main>'''
    return views.layout(
        config,
        "Боты КиноЖдуна",
        "Выберите КиноЖдун в Telegram, MAX или ВКонтакте и получайте напоминания о премьерах.",
        content,
        noindex=False,
    )
