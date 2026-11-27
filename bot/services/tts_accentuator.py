"""
Подготовка текста для русской озвучки (Yandex SpeechKit / edge-tts):
- словарь бренда и киноиндустрии (КиноЖдун, стриминги, термины);
- контекстное разрешение омографов (стоит/стои́т, всё/все и др.);
- словарная ёфикация и расстановка ударений '+' по базе OpenRussian (SQLite);
- транслитерация популярных платформ/сетей, не трогая отображаемые субтитры.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import sqlite3
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
_DEFAULT_DB = _ASSETS_DIR / "ru_stress.sqlite"
_DEFAULT_GZ = _ASSETS_DIR / "ru_stress.sqlite.gz"

# Фиксированные формы бренда, частых кинотерминов и слов вне OpenRussian (высший приоритет).
CUSTOM_ACCENTS: dict[str, str] = {
    # Бренд
    "кинождун": "Киножд+ун",
    "кинождуна": "Киножд+уна",
    "кинождуну": "Киножд+уну",
    "кинождуном": "Киножд+уном",
    "кинождуне": "Киножд+уне",
    # Кинотермины и частые слова
    "трейлер": "тр+ейлер",
    "трейлера": "тр+ейлера",
    "трейлере": "тр+ейлере",
    "трейлеры": "тр+ейлеры",
    "тизер": "т+изер",
    "тизера": "т+изера",
    "сезон": "сез+он",
    "сезона": "сез+она",
    "сезону": "сез+ону",
    "сезоне": "сез+оне",
    "сезоны": "сез+оны",
    "релиз": "рел+из",
    "релиза": "рел+иза",
    "триллер": "тр+иллер",
    "триллера": "тр+иллера",
    "хоррор": "х+оррор",
    "хоррора": "х+оррора",
    "экшен": "+экшен",
    "экшена": "+экшена",
    "боевик": "боев+ик",
    "боевика": "боев+ика",
    "фэнтези": "ф+энтези",
    "аниме": "аним+э",
    "дорама": "дор+ама",
    "дорамы": "дор+амы",
    "дораму": "дор+аму",
    "сиквел": "с+иквел",
    "сиквела": "с+иквела",
    "приквел": "пр+иквел",
    "приквела": "пр+иквела",
    "ремейк": "рем+ейк",
    "ремейка": "рем+ейка",
    "спин-офф": "спин-+офф",
    "спин-оффа": "спин-+оффа",
    "шоураннер": "шоур+аннер",
    "шоураннера": "шоур+аннера",
    "сценарист": "сценар+ист",
    "продюсер": "прод+юсер",
    "продюсера": "прод+юсера",
    "бегущий": "бег+ущий",
    "бегущего": "бег+ущего",
    "бегущему": "бег+ущему",
    "бегущим": "бег+ущим",
    "выходящий": "выход+ящий",
    "предстоящий": "предсто+ящий",
    "долгожданный": "долгожд+анный",
    "долгожданная": "долгожд+анная",
    "долгожданное": "долгожд+анное",
    "долгожданного": "долгожд+анного",
    "сериальный": "сери+альный",
    "сериальная": "сери+альная",
    "кинопремьера": "кинопремь+ера",
    "кинопоиск": "Киноп+оиск",
    "кинопоиске": "Киноп+оиске",
    "премьер": "Премь+ер",
    "окко": "+Окко",
    "винк": "В+инк",
    "кион": "Ки+он",
    "иви": "+Иви",
    "нетфликс": "Н+этфликс",
    "дисней": "Дисн+ей",
    "пиксар": "Пикс+ар",
    "марвел": "М+арвел",
    "голливуд": "Голлив+уд",
    "голливуда": "Голлив+уда",
    "голливуде": "Голлив+уде",
    "онлайн": "онл+айн",
    "кинотеатр": "киноте+атр",
    "кинотеатрах": "киноте+атрах",
    "кинотеатре": "киноте+атре",
    "телеканал": "телекан+ал",
    "телеканале": "телекан+але",
    "стриминг": "стр+иминг",
    "стриминге": "стр+иминге",
    "стриминга": "стр+иминга",
    "подписка": "подп+иска",
    "подписке": "подп+иске",
    "уведомление": "уведомл+ение",
    "уведомления": "уведомл+ения",
    "описание": "опис+ание",
    "описании": "опис+ании",
    "внимание": "вним+ание",
    "присмотритесь": "присмотр+итесь",
    "обратите": "обрат+ите",
    "отслеживайте": "отсл+еживайте",
    "добавьте": "доб+авьте",
    "сохраните": "сохран+ите",
    "включите": "включ+ите",
    "непростой": "непрост+ой",
    "неординарная": "неордин+арная",
    "семейные": "сем+ейные",
}

# Фразовые замены для платформ/студий/аббревиатур (выполняются до пословной разметки).
PHRASE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bAmazon\s+Prime\s+Video\b", re.IGNORECASE), "Амаз+он Пр+айм В+идео"),
    (re.compile(r"\bPrime\s+Video\b", re.IGNORECASE), "Пр+айм В+идео"),
    (re.compile(r"\bApple\s+TV\+", re.IGNORECASE), "+Эппл Ти Ви Пл+юс"),
    (re.compile(r"\bApple\s+TV\b", re.IGNORECASE), "+Эппл Ти Ви"),
    (re.compile(r"\bDisney\+", re.IGNORECASE), "Дисн+ей Пл+юс"),
    (re.compile(r"\bWalt\s+Disney(?:\s+Animation\s+Studios)?\b", re.IGNORECASE), "У+олт Дисн+ей"),
    (re.compile(r"\bParamount\+", re.IGNORECASE), "Парам+аунт Пл+юс"),
    (re.compile(r"\bHBO\s+Max\b", re.IGNORECASE), "Эйч Би +О М+акс"),
    (re.compile(r"\bHBO\b", re.IGNORECASE), "Эйч Би +О"),
    (re.compile(r"\bNetflix\b", re.IGNORECASE), "Н+этфликс"),
    (re.compile(r"\bShowtime\b", re.IGNORECASE), "Шоут+айм"),
    (re.compile(r"\bPeacock\b", re.IGNORECASE), "Пик+ок"),
    (re.compile(r"\bHulu\b", re.IGNORECASE), "Х+улу"),
    (re.compile(r"\bSyfy\b", re.IGNORECASE), "Сай Ф+ай"),
    (re.compile(r"\bBBC(?:\s+One|\s+Two)?\b", re.IGNORECASE), "Би Би Си"),
    (re.compile(r"\bFX\b"), "Эф Икс"),
    (re.compile(r"\bAMC\b"), "Эй Эм Си"),
    (re.compile(r"\bCBS\b"), "Си Би Эс"),
    (re.compile(r"\bNBC\b"), "Эн Би Си"),
    (re.compile(r"\bABC\b"), "Эй Би Си"),
    (re.compile(r"\bCW\b"), "Си Дабл Ю"),
    (re.compile(r"\bOkko\b", re.IGNORECASE), "+Окко"),
    (re.compile(r"\bWink\b", re.IGNORECASE), "В+инк"),
    (re.compile(r"\bPREMIER\b", re.IGNORECASE), "Премь+ер"),
    (re.compile(r"\bSTART\b"), "Ст+арт"),
    (re.compile(r"\bKION\b", re.IGNORECASE), "Ки+он"),
    (re.compile(r"\bIVI\b", re.IGNORECASE), "+Иви"),
    (re.compile(r"\bMore\.tv\b", re.IGNORECASE), "М+оре Ти Ви"),
    (re.compile(r"\bТНТ\b"), "Тэ Эн Тэ"),
    (re.compile(r"\bСТС\b"), "Эс Тэ Эс"),
    (re.compile(r"\bНТВ\b"), "Эн Тэ Вэ"),
    (re.compile(r"\bТВ-?3\b", re.IGNORECASE), "Тэ Вэ Тр+и"),
    (re.compile(r"\bkinojdun\.ru\b", re.IGNORECASE), "киножд+ун точка ру"),
]

# Порядковые числительные (1-й сезон -> п+ервый сез+он).
_ORDINAL_NOM = {
    "1": "п+ервый", "2": "втор+ой", "3": "тр+етий", "4": "четв+ёртый", "5": "п+ятый",
    "6": "шест+ой", "7": "седьм+ой", "8": "восьм+ой", "9": "дев+ятый", "10": "дес+ятый",
}
_ORDINAL_GEN = {
    "1": "п+ервого", "2": "втор+ого", "3": "тр+етьего", "4": "четв+ёртого", "5": "п+ятого",
    "6": "шест+ого", "7": "седьм+ого", "8": "восьм+ого", "9": "дев+ятого", "10": "дес+ятого",
}

_STOIT_INF_NEXT = {
    "добавить", "посмотреть", "увидеть", "ждать", "обратить", "подождать",
    "оценить", "включить", "попробовать", "знать", "помнить", "присмотреться",
    "пропустить", "бояться", "доверять",
}
_STOIT_PREV_WORDS = {"который", "которую", "которое", "которые", "точно", "обязательно", "того", "не"}
_STOYAT_NEXT_PREPS = {"на", "перед", "за", "у", "рядом", "в", "во", "под", "между", "около"}

_VSYO_NEXT = {
    "еще", "ещё", "же", "равно", "больше", "меньше", "сильнее", "глубже",
    "сложнее", "хуже", "лучше", "дальше", "ближе", "вокруг", "это", "идет",
    "идёт", "меняется", "рушится", "решается", "начинается", "происходит", "будет",
    "становится", "оказывается", "время",
}
_VSYO_PREV = {"прежде", "после", "несмотря", "про", "обо", "за", "на", "во"}

_WORD_TOKEN_RE = re.compile(r"([А-Яа-яЁё+]+(?:-[А-Яа-яЁё+]+)*)")
_CLEAN_WORD_RE = re.compile(r"^[а-яё]+(?:-[а-яё]+)*$")
_VOWELS = set("аеёиоуыэюя")


def _resolve_db_path() -> Optional[Path]:
    env_path = os.getenv("RU_STRESS_DB_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    if _DEFAULT_DB.exists():
        return _DEFAULT_DB
    if _DEFAULT_GZ.exists():
        tmp_db = Path(tempfile.gettempdir()) / "kinojdun_ru_stress.sqlite"
        if not tmp_db.exists() or tmp_db.stat().st_size < 1_000_000:
            tmp_part = tmp_db.with_suffix(".tmp")
            with gzip.open(_DEFAULT_GZ, "rb") as f_in, tmp_part.open("wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            tmp_part.replace(tmp_db)
        return tmp_db
    return None


@lru_cache(maxsize=1)
def _get_conn() -> Optional[sqlite3.Connection]:
    db_path = _resolve_db_path()
    if db_path is None:
        return None
    try:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        return sqlite3.connect(uri, uri=True, check_same_thread=False)
    except Exception:
        return sqlite3.connect(str(db_path), check_same_thread=False)


@lru_cache(maxsize=16384)
def _lookup_db(plain_word: str) -> Optional[str]:
    conn = _get_conn()
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT accented FROM stress WHERE plain = ?", (plain_word,)).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _preserve_case(orig: str, repl: str) -> str:
    """Переносит регистр с исходного слова на размеченное (учитывая ведущий '+' перед первой гласной)."""
    if not orig or not repl:
        return repl
    # Не трогаем, если в CUSTOM_ACCENTS уже задан явный бренд/собственное имя с заглавной
    if any(ch.isupper() for ch in repl):
        if orig[0].islower() and repl[0].isupper():
            return repl[0].lower() + repl[1:]
        return repl

    if orig[0].isupper():
        if repl.startswith("+") and len(repl) > 1:
            return "+" + repl[1].upper() + repl[2:]
        return repl[0].upper() + repl[1:]
    return repl


def _count_vowels(word: str) -> int:
    return sum(1 for ch in word.lower() if ch in _VOWELS)


def _contextual_accent(words_lower: list[str], idx: int) -> Optional[str]:
    w = words_lower[idx]
    prev_w = words_lower[idx - 1] if idx > 0 else ""
    next_w = words_lower[idx + 1] if idx + 1 < len(words_lower) else ""

    if w == "стоит":
        if next_w in _STOYAT_NEXT_PREPS:
            return "сто+ит"
        if next_w in _STOIT_INF_NEXT or prev_w in _STOIT_PREV_WORDS:
            return "ст+оит"
        return "ст+оит" if next_w == "ли" else None

    if w == "все":
        if next_w in _VSYO_NEXT or prev_w in _VSYO_PREV:
            return "вс+ё"
        return None

    if w == "всего" and prev_w in {"больше", "меньше", "прежде", "после", "итого", "хуже", "лучше"}:
        return "всег+о"

    if w == "ее" or w == "её":
        return "е+ё"

    return None


def _accent_single_word(orig: str, contextual: Optional[str], is_sentence_start: bool) -> str:
    if "+" in orig:
        return orig

    low = orig.lower()
    if contextual:
        return _preserve_case(orig, contextual)

    if low in CUSTOM_ACCENTS:
        return _preserve_case(orig, CUSTOM_ACCENTS[low])

    # Если в оригинале уже стоит 'ё' (и слово не в CUSTOM_ACCENTS), 'ё' сама задаёт ударение
    if "ё" in low:
        return _preserve_case(orig, low.replace("ё", "+ё", 1))

    if _count_vowels(low) <= 1 or not _CLEAN_WORD_RE.match(low):
        return orig

    # Не ставим ударение из словаря для вероятных имён собственных с заглавной буквы в середине предложения
    # (например, имя "Кора" != "кор+а", "Роман" != "ром+ан").
    if orig[0].isupper() and not is_sentence_start:
        return orig

    plain = low.replace("ё", "е")
    found = _lookup_db(plain)
    if found:
        return _preserve_case(orig, found)

    # Для дефисных слов вроде "девочка-подросток" пробуем разметить каждую часть отдельно
    if "-" in plain:
        parts_orig = orig.split("-")
        parts_out = []
        changed = False
        for p in parts_orig:
            pl = p.lower()
            if pl in CUSTOM_ACCENTS:
                parts_out.append(_preserve_case(p, CUSTOM_ACCENTS[pl]))
                changed = True
            elif "ё" in pl:
                parts_out.append(_preserve_case(p, pl.replace("ё", "+ё", 1)))
                changed = True
            elif _count_vowels(pl) > 1:
                sub = _lookup_db(pl.replace("ё", "е"))
                if sub:
                    parts_out.append(_preserve_case(p, sub))
                    changed = True
                else:
                    parts_out.append(p)
            else:
                parts_out.append(p)
        if changed:
            return "-".join(parts_out)

    return orig


def prepare_tts_text(text: str, use_plus: bool = True) -> str:
    """
    Готовит текст для дикторской озвучки.
    - use_plus=True: расставляет '+' перед ударной гласной для Yandex SpeechKit.
    - use_plus=False: оставляет ёфикацию и транслитерацию, убирая '+' (для edge-tts fallback).
    """
    if not text:
        return ""

    out = text.replace("«", " ").replace("»", " ").replace('"', " ")
    out = re.sub(r"\s*[—–]\s*", ", ", out)

    # Порядковые числительные с сохранением заглавной в начале предложения
    def _ord_sub(mapping: dict[str, str]):
        def _fn(m: re.Match[str]) -> str:
            repl = mapping.get(m.group(1))
            if not repl:
                return m.group(0)
            before = out[:m.start()].rstrip()
            if not before or before[-1] in ".!?":
                return _preserve_case("А", repl)
            return repl
        return _fn

    out = re.sub(r"\b(\d+)-й\b", _ord_sub(_ORDINAL_NOM), out, flags=re.IGNORECASE)
    out = re.sub(r"\b(\d+)-го\b", _ord_sub(_ORDINAL_GEN), out, flags=re.IGNORECASE)

    # Платформы, студии, аббревиатуры
    for pat, repl in PHRASE_REPLACEMENTS:
        out = pat.sub(repl, out)

    # Смягчаем слова полностью в ВЕРХНЕМ РЕГИСТРЕ из кириллицы (кроме коротких аббревиатур <= 3 букв)
    def _uncaps(m: re.Match[str]) -> str:
        w = m.group(0)
        if len(w) > 3 and w.isupper():
            return w.capitalize()
        return w

    out = re.sub(r"\b[А-ЯЁ]{4,}\b", _uncaps, out)

    # Токенизируем, чтобы учитывать соседние слова для омографов и начало предложений
    tokens = _WORD_TOKEN_RE.split(out)
    word_indices = [i for i in range(1, len(tokens), 2)]
    words_lower = [tokens[i].lower().replace("+", "") for i in word_indices]

    for pos, tok_idx in enumerate(word_indices):
        ctx = _contextual_accent(words_lower, pos)
        prefix = "".join(tokens[:tok_idx]).rstrip()
        is_start = (not prefix) or (prefix[-1] in ".!?")
        tokens[tok_idx] = _accent_single_word(tokens[tok_idx], ctx, is_start)

    res = "".join(tokens)
    res = re.sub(r"\s+([,.!?;:])", r"\1", res)
    res = re.sub(r"\s{2,}", " ", res).strip()

    if not use_plus:
        res = res.replace("+", "")

    return res
