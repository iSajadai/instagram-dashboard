"""Linting a Persian Instagram caption before it goes out: what the feed shows before «... more»
(about 125 characters), whether the first line is worth that space, hashtags (Instagram caps them at
five since December 2025), dead links, how many asks, emoji, the search phrases, and the half-spaces
Persian needs. Same checks as caption.py in instagram-agent-skill, written for Persian."""
import re

from .text import (EMOJI_RE, HASHTAG_RE, LINK_RE, MENTION_RE, ZWNJ, concrete_markers, normalize, phrase_re, squash)
from . import human

LIMIT = 2200
TRUNCATE = 125
HASHTAG_LIMIT = 5
FILLER_TAGS = {squash(t) for t in """
#viral #explore #explorepage #fyp #foryou #foryoupage #reels #reel #instagood #trending #trend #instagram #follow #like
#likeforlike #followforfollow #اکسپلور #اکسپلورر #فالو #لایک #فالوور #فالوورز #ریلز #ریل #ترند #کامنت #فالو_کن
#لایک_کن #ویرال #اینستاگرام #پیج #جذب_فالوور
""".split()}
ASKS = [
    (re.compile(r"کامنت[\s‌]*(?:کن|کنید|بذار|بزار|بذارید|بزارید|بنویس|بده)|(?:زیر|تو|توی)[\s‌]*(?:همین[\s‌]*)?(?:پست|کامنت(?:ها)?)[\s‌]*(?:بنویس|بگو)"), "کامنت"),
    (re.compile(r"(?:ذخیره|سیو)[\s‌]*(?:ش|اش)?[\s‌]*(?:کن|کنید)"), "ذخیره"),
    (re.compile(r"فالو[\s‌]*(?:کن|کنید)|(?:پیج|صفحه)[\s‌]*رو[\s‌]*دنبال"), "فالو"),
    (re.compile(r"(?:بفرست|بفرستید|شیر[\s‌]*کن|شیرش[\s‌]*کن|منشن[\s‌]*کن|تگ[\s‌]*کن)"), "فرستادن"),
    (re.compile(r"(?:دایرکت|دایرک|پیوی|پی[\s‌]*وی)[\s‌]*(?:بده|بدید|بزن|پیام)|پیام[\s‌]*بده"), "دایرکت"),
    (re.compile(r"لینک[\s‌]*(?:تو|توی|در)[\s‌]*(?:بایو|بیو|پروفایل)"), "لینک بایو"),
]
# the keyword usually comes first in Persian («کلمهٔ «پرامپت» رو کامنت کن»), but «کامنت کن: پرامپت» happens too
KEYWORD_ASK = re.compile(r"[«\"“]([^»\"”\n]{1,40})[»\"”][\s‌]*(?:رو|را)?[\s‌]*(?:زیر[\s‌]*(?:همین[\s‌]*)?پست[\s‌]*)?(?:کامنت|بنویس)"
                         r"|کامنت[\s‌]*(?:کن|کنید|بذار|بزار|بنویس)?[\s‌:]*[«\"“]([^»\"”\n]{1,40})[»\"”]")
GREETING = re.compile(r"^\s*(?:سلام|درود|عرض\s*ادب|وقت(?:تون|ت)?\s*بخیر)")
VERDICT_FA = {"READY": "آماده", "REVIEW": "یه نگاه بنداز", "FIX": "باید درست بشه"}


def visible_window(text, cut=TRUNCATE):
    """The part the feed shows: up to the cut, and only the first lines (a line break also cuts it)."""
    t = text.strip()
    lines = t.split("\n")
    shown = "\n".join(lines[:2]) if len(lines) > 1 else t
    return shown[:cut]


def analyse(text, keywords=None, cut=TRUNCATE):
    raw = str(text or "").rstrip()
    t = normalize(raw).strip()
    chars = len(t)
    first = t.split("\n")[0].strip() if t else ""
    tags = HASHTAG_RE.findall(t)
    links = LINK_RE.findall(re.sub(r"@[\w.]+", "", t))
    emoji = EMOJI_RE.findall(t)
    window = visible_window(t, cut)
    asks = [name for p, name in ASKS if p.search(t)]
    filler = [x for x in tags if squash(x) in FILLER_TAGS]
    keywords = [k.strip() for k in (keywords or []) if str(k).strip()]
    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    add("طول", "FAIL" if chars > LIMIT else "PASS", f"{chars} از {LIMIT} حرف" + (f"، {chars - LIMIT} تا بیشتر از سقف" if chars > LIMIT else ""))
    if not first:
        add("خط اول", "FAIL", "کپشن با خط خالی شروع می‌شه")
    elif first.startswith(("#", "@")):
        add("خط اول", "FAIL", "با هشتگ یا منشن شروع می‌شه؛ این تنها جاییه که ارزش یه جمله رو داره")
    elif GREETING.match(first):
        add("خط اول", "FAIL", "با سلام شروع می‌شه؛ ۱۲۵ حرفی که دیده می‌شه رو صرف احوال‌پرسی نکن")
    elif EMOJI_RE.match(first):
        add("خط اول", "WARN", "اولین حرف ایموجیه؛ با کلمه شروع کن")
    elif len(first) > cut:
        add("خط اول", "WARN", f"{len(first)} حرف، پس وسط جمله در {cut} بریده می‌شه. اگه بریدگی کنجکاوی بسازه خوبه، اگه وسط یه جملهٔ فرعی باشه بد")
    else:
        add("خط اول", "PASS", f"{len(first)} حرف، کامل دیده می‌شه")
    nums, names, quoted, spoken = concrete_markers(window)
    hits = len(nums) + len(names) + len(quoted) + len(spoken)
    add("چیز مشخص قبل از بیشتر", "PASS" if hits else "WARN",
        f"{hits} عدد یا اسم تو بخش دیده‌شده" + ("" if hits else " - قبل از لمس هیچ چیز قابل‌سنجشی نیست"))
    if len(tags) > HASHTAG_LIMIT:
        add("هشتگ", "FAIL", f"{len(tags)} هشتگ؛ سقف اینستاگرام از دسامبر ۲۰۲۵ پنج‌تاست. بیشتر از پنج حساب نمی‌شه و قدیمی به نظر می‌رسه")
    elif filler:
        add("هشتگ", "WARN", f"{len(tags)} هشتگ، {len(filler)} تاش کلی ({'، '.join(filler[:3])}). این‌ها چیزی رو توصیف نمی‌کنن؛ موضوع بنویس")
    else:
        add("هشتگ", "PASS", f"{len(tags)} هشتگ" + (f": {' '.join(tags)}" if tags else ""))
    if tags and any(x in window for x in tags):
        add("جای هشتگ", "WARN", "هشتگ تو بخش دیده‌شده‌ست و جای فید رو برای یه برچسب خرج می‌کنه")
    elif tags:
        add("جای هشتگ", "PASS", "هشتگ‌ها زیر بخش دیده‌شده‌ان")
    add("لینک", "WARN" if links else "PASS",
        f"{len(links)} لینک تو کپشن، و کپشن کلیک نمی‌خوره. ببرش تو بایو یا دایرکت" if links else "لینک مرده‌ای تو متن نیست")
    if len(asks) == 1:
        add("یک درخواست", "PASS", f"یه دعوت به کار: {asks[0]}")
    elif not asks:
        add("یک درخواست", "WARN", "هیچ دعوتی به کار نیست. تصمیم بگیر این پست برای چیه")
    else:
        add("یک درخواست", "WARN", f"{len(asks)} درخواست ({'، '.join(asks)}). دو درخواست یعنی هیچ‌کدوم")
    m = KEYWORD_ASK.search(t)
    if m:
        kw = (m.group(1) or m.group(2)).strip()
        ok = len(re.split(rf"[\s{ZWNJ}]+", kw)) == 1 and not EMOJI_RE.search(kw)
        add("کلمهٔ کامنت", "PASS" if ok else "WARN",
            f"«{kw}» یه کلمه‌ست و راحت تایپ می‌شه" if ok else f"«{kw}» یه کلمه نیست؛ یه کلمهٔ کوتاه بی‌فاصله بذار که تو ویدیو هم بگی")
    density = len(emoji) * 100 / max(chars, 1)
    add("ایموجی", "WARN" if density > 4 else "PASS", f"{len(emoji)} ایموجی، {density:.1f} در هر ۱۰۰ حرف" + (" - تزئینی شده" if density > 4 else ""))
    if chars > 400 and "\n\n" not in t:
        add("پاراگراف", "WARN", "بیشتر از ۴۰۰ حرف بدون خط فاصله؛ تو گوشی یه دیوار متن می‌شه")
    fixes = human.halfspace_fixes(raw)
    add("نیم‌فاصله", "WARN" if fixes else "PASS",
        f"{len(fixes)} جا نیم‌فاصله لازمه ({'، '.join(f'«{a}» ← «{b}»' for a, b in fixes[:3])})" if fixes else "نیم‌فاصله‌ها درسته")
    if keywords:
        found = [k for k in keywords if phrase_re(k).search(t)]
        missing = [k for k in keywords if k not in found]
        in_window = [k for k in found if phrase_re(k).search(window)]
        add("عبارت جست‌وجو", "PASS" if not missing else ("WARN" if found else "FAIL"),
            f"{len(found)} از {len(keywords)} هست" + (f"، {len(in_window)} تاش تو بخش دیده‌شده" if found else "")
            + (f". جا افتاده: {'، '.join(missing)}" if missing else ""))
    fails = sum(c["status"] == "FAIL" for c in checks)
    warns = sum(c["status"] == "WARN" for c in checks)
    verdict = "FIX" if fails else ("REVIEW" if warns else "READY")
    return {"characters": chars, "limit": LIMIT, "truncate_at": cut, "visible": window, "truncated": chars > len(window),
            "hashtags": tags, "mentions": MENTION_RE.findall(t), "links": links, "emoji": len(emoji), "asks": asks,
            "checks": checks, "verdict": verdict, "verdict_fa": VERDICT_FA[verdict]}
