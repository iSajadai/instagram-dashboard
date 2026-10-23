"""Scoring a Reel hook in Persian, before a take is wasted on it: five checks out of 100, the same
idea as hookscore.py in instagram-agent-skill, rebuilt for how Persian is spoken. Negation is a verb
prefix («نکن»، «نمی‌شه»), names have no capital letters (so Latin brand names and «quoted» terms
count), and the verb comes last, so the payload has to sit in the first few words.

Also names which of the 26 formulas a hook uses (data/hooks_fa.json), for swipe files and audits."""
import re, statistics

from .text import (EMOJI_RE, HASHTAG_RE, LETTERS, ZWNJ, concrete_markers, data, normalize, squash, words)

WPM = 150  # spoken Persian, a calm on-camera pace; voice settings can change it

# Words that put something on the line. A hook with none of these is a statement.
STAKES = {squash(w) for w in """
هیچ هیچ‌کس هیچکس کسی هیچ‌وقت هیچوقت هرگز اشتباه اشتباهی غلط ضرر باختم باختی سوختم سوخت گرون گرونه رایگان مجانی
پول اخراج پاک دروغ راز مخفی پنهان بدترین ترس خطر هشدار ممنوع فقط بدون ولی اما قبل به‌جای بجای واقعاً واقعا هنوز
حتی فاجعه مشکل کلاهبرداری حیف پشیمون پشیمان نباید نیست نبود نشد نداره ندارم ندارن نداشتم نکن نکنید نزن نخر نده
نذار نرو نخون باختن شکست شکستم ورشکست دزدی دزدیدم بدزد جریمه بلاک ریپورت دیلیت حذف کنار بی‌فایده اصلاً اصلا
تنها برعکس عوض بیخیال مرد مُرد تموم تمام آخرین اولین بیشترین کمترین بدتر بهتر
""".split()}
# Negation is a prefix on the verb. «نمی‌…» is always one; for «ن…» only real negated verbs count, since
# «نکته»، «نتیجه»، «نوشتم» start with ن too.
_PAST = "کرد رفت دید خورد داشت بود شد گفت خرید فهمید خوند خواند زد داد ذاشت گذاشت ساخت تونست توانست اومد آمد دونست دانست خواست نوشت فروخت گرفت موند ماند شنید رسید پرسید".split()
_IMPER = "کن زن خر ده ذار گذار رو خون گو بین پرس ریز فرست ساز خور شو کش بند".split()
NEGATED = {squash("ن" + s + e) for s in _PAST for e in ("", "م", "ی", "یم", "ید", "ن", "ند")}
NEGATED |= {squash("ن" + s + e) for s in _IMPER for e in ("", "ید", "ین")}
NEGATED |= {squash(w) for w in "نداره ندارم نداری ندارن نداریم ندارید نیست نیستم نیستی نیستن نیستیم نباید نشه نشو نزار نذارید".split()}
# Openers that spend the first second saying nothing.
WEAK_OPENERS = [squash(w) for w in """
سلام درود خب خوب امروز تو‌این توی‌این در‌این میخوام می‌خوام میخواستم می‌خواستم قراره بیاید بیایید یکی‌از اینکه
راستش ببخشید عزیزان دوستان رفقا بچه‌ها همونطور همانطور شاید حتما حتماً اول بذارید بزارید ببینید‌چطور وقت‌بخیر
""".split()]
IMPERATIVES = {squash(w) for w in """
بخر نخر ببین کپی ذخیره سیو امتحان بزن بنویس بفرست بساز شروع پاک دانلود نصب بپرس بدزد تست بخون نکن نکنید
نزن بیخیال بذار نذار برو نرو بگیر دست نگه بشنو گوش یاد بکن بکنید بزنید بنویسید بسازید
""".split()}
SECOND_PERSON = {squash(w) for w in "تو شما خودت خودتون برات براتون بهت بهتون باهات ازت ازتون واست واستون تون".split()}
FIRST_PERSON = {squash(w) for w in "من ما خودم خودمون برام بهم ازم باهام مون".split()}
NOT_VERBS = {squash(w) for w in "آدم مردم قدم هم کم ستم چشم اسم رسم خشم جسم لازم مهم".split()}

DEALBREAKERS = [
    (re.compile(r"^\s*(?:اسکرول\s*نکن|رد\s*نشو|نرو\s*رد|صبر\s*کن|وایسا|نگه\s*دار)"),
     "با «اسکرول نکن» شروع می‌شه. خواهش برای توجه یعنی هنوز توجه رو به دست نیاوردی."),
    (re.compile(rf"(?:تو|توی|در)[\s{ZWNJ}]*این[\s{ZWNJ}]*(?:ویدیو|ویدئو|ریل|پست|کلیپ)|امروز[\s{ZWNJ}]*(?:می[\s{ZWNJ}]*)?خوام"
                rf"|می[\s{ZWNJ}]*خوام[\s{ZWNJ}]*(?:بهتون|براتون|بهت|برات)[\s{ZWNJ}]*(?:نشون|بگم|توضیح)|قراره[\s{ZWNJ}]*(?:بهتون|براتون|بهت|برات)"),
     "مقدمهٔ ویدیو («تو این ویدیو…»). پاکش کن و مستقیم با نتیجه شروع کن."),
    (re.compile(r"^\s*(?:سلام|درود|عرض\s*ادب|وقت(?:تون|ت)?\s*بخیر|هی\s|خب\s+سلام)"),
     "سلام و احوال‌پرسی. کسی برای سلام شنیدن تو فید نیست."),
    (HASHTAG_RE, "هشتگ تو هوک. جای هشتگ، اگه لازم باشه، آخر کپشنه."),
    (EMOJI_RE, "ایموجی تو هوک. متن روی صفحه با این اندازه جای کلمه داره یا ایموجی، نه هر دو."),
]
CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]
CHECK_FA = {"LENGTH": "طول", "SPECIFICITY": "مشخص بودن", "STAKES": "چیزی در خطره", "FRONTLOAD": "حرف اصلی اول", "ADDRESS": "مخاطب"}
VERDICT_FA = {"STRONG": "قوی", "OK": "متوسط", "WEAK": "ضعیف"}


def clamp(n):
    return max(0.0, min(100.0, n))


def is_negated(word):
    w = squash(word)
    return (w.startswith("نمی") and len(w) > 4) or w in NEGATED


def is_stake(word):
    w = squash(word)
    return w in STAKES or is_negated(word)


def check_length(text, wpm=WPM):
    """A hook has to land in about two seconds, before the thumb moves."""
    n = len(words(text))
    chars = len(normalize(text).strip())
    secs = n / (wpm / 60)
    score = 100.0 if 4 <= n <= 11 else clamp(100 - (4 - n) * 22) if n < 4 else clamp(100 - (n - 11) * 11)
    if chars > 55:  # two lines of large on-screen text
        score -= 12
    return clamp(score), f"{n} کلمه، {chars} حرف، حدود {secs:.1f} ثانیه گفتن (۴ تا ۱۱ کلمه خوبه)"


def check_specificity(text):
    """One concrete thing beats three abstract ones: a number, a name, an amount."""
    nums, names, quoted, spoken = concrete_markers(text)
    hits = len(nums) + len(names) + len(quoted) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = "، ".join((nums + names + quoted + spoken)[:3])
    return score, f"{hits} چیز مشخص" + (f": {found}" if found else " - نه عددی، نه اسمی، هیچ چیز قابل‌سنجشی")


def check_stakes(text):
    """Tension, a cost, a negation: something the viewer might lose."""
    ws = words(text)
    markers = sorted({w for w in ws if is_stake(w)})
    if re.search(r"(?:[0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬.]*\s*(?:هزار|میلیون|میلیارد)?\s*(?:تومن|تومان|دلار|ریال))|\$\s?[0-9]", normalize(text)):
        markers.append("یه مبلغ")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    return score, f"{n} نشانهٔ تنش" + (f": {'، '.join(markers[:4])}" if markers else " - هیچی تو این جمله در خطر نیست")


def payload_index(ws):
    for i, w in enumerate(ws):
        nums, names, quoted, spoken = concrete_markers(w)
        if is_stake(w) or nums or names or spoken:
            return i
    return None


def check_frontload(text):
    """The interesting word can't be the ninth one."""
    ws = words(text)
    if not ws:
        return 0.0, "خالیه"
    first, two = squash(ws[0]), squash("".join(ws[:2]))
    weak = next((w for w in WEAK_OPENERS if first == w or two.startswith(w)), None)
    p = payload_index(ws)
    if p is None:
        base, where = 30.0, "هیچ کلمهٔ کلیدی‌ای تو جمله نیست"
    elif p <= 2:
        base, where = 100.0, f"حرف اصلی کلمهٔ {p + 1}"
    elif p <= 5:
        base, where = 70.0, f"حرف اصلی کلمهٔ {p + 1}، می‌شه جلوتر آوردش"
    else:
        base, where = 40.0, f"حرف اصلی کلمهٔ {p + 1}، خیلی دیره"
    return clamp(base - (30 if weak else 0)), where + (f"؛ شروع شل («{ws[0]}»)" if weak else "")


def check_address(text):
    """Aimed at one viewer, or floating in the air."""
    ws = [squash(w) for w in words(text)]
    you_verb = re.compile(rf"^(?:ن?می)[{LETTERS}]+(?:ی|ید|ین)$")
    if any(w in SECOND_PERSON for w in ws) or any(you_verb.match(w) for w in ws):
        return 100.0, "با خود بیننده حرف می‌زنه"
    if ws and (ws[0] in IMPERATIVES or (ws[0].startswith("ن") and ws[0][1:] in IMPERATIVES)):
        return 90.0, f"با فعل امری شروع می‌شه («{words(text)[0]}»)"
    me_verb = re.compile(rf"^(?:(?:ن?می)[{LETTERS}]+(?:م|یم)|[{LETTERS}]+(?:دم|تم))$")
    if any(w in FIRST_PERSON for w in ws) or any(me_verb.match(w) and w not in NOT_VERBS for w in ws):
        return 70.0, "اول شخص، ولی بیننده رو صدا نمی‌زنه"
    return 35.0, "سوم شخص، کسی تو اتاق نیست"


def score(text, wpm=WPM):
    """{overall, verdict, checks: {name: (score, detail)}, flags}"""
    results = {"LENGTH": check_length(text, wpm), "SPECIFICITY": check_specificity(text), "STAKES": check_stakes(text),
               "FRONTLOAD": check_frontload(text), "ADDRESS": check_address(text)}
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(normalize(text))]
    s = [results[c][0] for c in CHECKS]
    # the weakest property caps the hook: one bad property is enough for the thumb to keep moving
    overall = clamp(statistics.mean(s) * 0.6 + min(s) * 0.4 - len(flags) * 15)
    verdict = "STRONG" if overall >= 70 and min(s) >= 55 and not flags else ("OK" if overall >= 50 else "WEAK")
    weakest = min(CHECKS, key=lambda c: results[c][0])
    return {"text": text, "overall": round(overall, 1), "verdict": verdict, "verdict_fa": VERDICT_FA[verdict], "flags": flags,
            "weakest": weakest, "weakest_fa": CHECK_FA[weakest],
            "checks": [{"id": c, "name": CHECK_FA[c], "score": round(results[c][0], 1), "detail": results[c][1]} for c in CHECKS]}


def rank(hooks, wpm=WPM):
    return sorted((score(h, wpm) for h in hooks if str(h).strip()), key=lambda r: -r["overall"])


# ---------- the 26 formulas ----------

def formulas():
    return data("hooks_fa.json")["hooks"]


def formula(fid):
    return next((f for f in formulas() if f["id"] == fid), None)


def classify(hook):
    """(id, name) of the first formula whose pattern matches the hook, or (None, None)."""
    d = data("hooks_fa.json")
    by_id = {f["id"]: f for f in d["hooks"]}
    t = normalize(hook)
    for fid in d.get("classify_order") or sorted(by_id):
        f = by_id.get(fid)
        if f and f.get("match") and re.search(f["match"], t, re.I):
            return fid, f["name"]
    return None, None
