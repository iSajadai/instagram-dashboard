#!/usr/bin/env python3
"""Verify hooks_fa.json: structure, regex compile, and classification tests (stdlib only)."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "sajadai", "fa", "data", "hooks_fa.json")

FIELDS = ["id", "name", "name_en", "template", "example", "on_screen", "best_for", "trap", "match"]
TEXT_FIELDS = ["name", "template", "example", "on_screen", "best_for", "trap"]


def normalize(text):
    # Same normalization the panel applies before matching. Digits are left as-is.
    return text.replace("ي", "ی").replace("ك", "ک")


def classify(text, compiled, order):
    t = normalize(text)
    for hid in order:
        if compiled[hid].search(t):
            return hid
    return None


# (hook text, expected id). At least one extra per formula, different wording, formal and colloquial.
EXTRA = [
    ("پنجاه میلیون تومان ضرر کردم، فقط چون قرارداد ننوشتم.", 1),
    ("۲۰۰۰ دلار پولم سوخت سر یه اشتباه ساده.", 1),
    ("هیچ‌وقت قیمت رو توی کامنت نگو.", 2),
    ("لطفاً دیگر پرامپت‌های طولانی ننویسید.", 2),
    ("پست روزانه نذار، این کارو بکن.", 2),
    ("هیچکس به شما نمی‌گوید که یادگیری هوش مصنوعی چقدر ساده است.", 3),
    ("چیزی که کسی بهت نمیگه اینه که ChatGPT همیشه درست نمی‌گه.", 3),
    ("این اپ ۵ دلاری جای فتوشاپ رو برام گرفت.", 4),
    ("به‌جای استخدام گرافیست، از این ابزار رایگان استفاده کنید.", 4),
    ("این کار قبلاً ۳ ساعت طول می‌کشید، حالا ۵ دقیقه.", 5),
    ("با این روش ادیت ویدیو فقط 10 دقیقه طول میکشه.", 5),
    ("به مدت ۳۰ روز هر روز با ChatGPT کار کردم؛ این نتایج واقعی است.", 6),
    ("یه ماه تمام فقط استوری گذاشتم. این آمار واقعیشه.", 6),
    ("بزرگ‌ترین اشتباهی که توی پرامپت‌نویسی می‌کنید اینه.", 7),
    ("شما دارید از ChatGPT اشتباه استفاده می‌کنید.", 7),
    ("۱۰ سال توی بانک کار کردم و اینا رو هیچ‌وقت به مشتری نمی‌گفتیم.", 8),
    ("من هشت سال در یک شرکت تبلیغاتی کار کردم؛ این‌ها حرف‌هایی است که هیچ‌وقت نمی‌گفتیم.", 8),
    ("اینو کش برو، پرامپتیه که سه ماه روش کار کردم.", 9),
    ("این قالب رو ذخیره کنید.", 9),
    ("اگر هنوز با ChatGPT فقط چت می‌کنی، این ویدیو برای توئه.", 10),
    ("۳ تا سایت هوش مصنوعی که باید بشناسی؛ سومی از همه بهتره.", 11),
    ("هفت ابزار رایگان برای ساخت ویدیو، شماره ۵ رو حتماً ببین.", 11),
    ("«من وقت ندارم هر روز محتوا بسازم.» قبول، اینم راه‌حلش.", 12),
    ('"هوش مصنوعی برای من سخته." باشه، این نسخه‌ی ساده‌شه.', 12),
    ("قبل و بعد از اینکه پرامپتمو درست کنم.", 13),
    ("این لوگوی من پارسال بود. اینم الانش با Midjourney.", 13),
    ("فریلنسرهای ایرانی، این ویدیو مخصوص شماست.", 14),
    ("همه‌ی معلم‌هایی که هنوز از ChatGPT می‌ترسن:", 14),
    ("اولین ۲۰ تا ویدیوم هیچ بازدیدی نگرفت.", 15),
    ("۱۰ پست اول من هیچ نتیجه‌ای نداشت.", 15),
    ("میشه با ChatGPT پول درآورد؟ این سؤالیه که هر روز ازم می‌پرسید.", 16),
    ("چگونه می‌توان با هوش مصنوعی کسب درآمد کرد؟", 16),
    ("ChatGPT در برابر Claude: کدوم برای فارسی بهتره؟", 17),
    ("فرق Gemini با ChatGPT چیه؟", 17),
    ("بذار بهت نشون بدم این ابزار در ۱۰ ثانیه چی کار می‌کنه.", 18),
    ("ببینید وقتی این پرامپت را وارد می‌کنم چه اتفاقی می‌افتد.", 18),
    ("تا آخر این ماه وقت دارید ثبت‌نام کنید، بعدش قیمت دو برابر می‌شه.", 19),
    ("از اول مهر قوانین اینستاگرام عوض می‌شه، قبلش این کارو بکن.", 19),
    ("نیازی نیست برنامه‌نویسی بلد باشید.", 20),
    ("برای شروع یادگیری هوش مصنوعی، لپ‌تاپ گرون لازم نیست.", 20),
    ("و اینجا بود که فهمیدم همه‌چی رو باختم.", 21),
    ("…خلاصه برگشت گفت این کارو قبول نمی‌کنم.", 21),
    ("جوینده یابنده نیست.", 22),
    ("ماهی رو هر وقت از آب بگیری تازه نیست.", 22),
    ("۹۰٪ کاربرای ChatGPT فقط از ۱۰ درصد قابلیت‌هاش استفاده می‌کنن.", 23),
    ("از هر ۱۰ نفر، ۸ نفر پرامپت رو اشتباه می‌نویسن.", 23),
    ("این جدیدترین مدل گوگله و رایگانه.", 24),
    ("اینم ابزار تازه‌ی OpenAI که همه دارن درباره‌ش حرف می‌زنن.", 24),
    ("یکی از شاگردام با همین روش تو دو ماه ۵۰ میلیون درآورد.", 25),
    ("فردی را می‌شناسم که در سه ماه صد هزار دنبال‌کننده جذب کرد.", 25),
    ("بهترین راه برای یادگیری پرامپت‌نویسی اینه.", 26),
    ("تنها چیزی که برای شروع لازم دارید یه گوشیه.", 26),
    # variant spellings: no half-space, Arabic ي/ك, Arabic-Indic and Latin digits
    ("هيچكس بهت نميگه که ٣٠ تا ريل اولت ديده نميشه.", 3),
    ("18 میلیون تومن برام آب خورد.", 1),
    ("٣٣ درصد آدما دیگه کتاب نمی‌خونن.", 23),
]

NEUTRAL = [
    "امروز درباره‌ی هوش مصنوعی حرف می‌زنیم.",
    "سلام به همگی، خوش اومدید.",
    "توی این ویدیو با هم یه پرامپت ساده می‌نویسیم.",
    "ChatGPT یه ابزار هوش مصنوعیه.",
    "امروز می‌خوام یه سایت رو معرفی کنم.",
    "این قسمت دوم آموزش میدجرنیه.",
    "یه پرامپت نوشتم و نتیجه‌ش جالب بود.",
    "خب بریم سراغ آموزش امروز.",
    "با هم یاد بگیریم چطور از Claude استفاده کنیم.",
    "قراره در مورد ابزارهای تولید ویدیو صحبت کنیم.",
    "یادگیری هوش مصنوعی مثل آب خوردنه.",
]


def main():
    failures = []
    passes = 0

    def check(cond, msg):
        nonlocal passes
        if cond:
            passes += 1
        else:
            failures.append(msg)

    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)

    for key in ("version", "note", "rules", "hooks", "classify_order"):
        check(key in data, f"missing top-level key {key}")
    hooks = data["hooks"]
    check(len(hooks) == 26, f"expected 26 hooks, got {len(hooks)}")
    ids = [h.get("id") for h in hooks]
    check(sorted(ids) == list(range(1, 27)), f"ids not 1..26: {ids}")
    order = data["classify_order"]
    check(sorted(order) == list(range(1, 27)), f"classify_order not a permutation of 1..26: {order}")

    compiled = {}
    for h in hooks:
        hid = h.get("id")
        for fld in FIELDS:
            check(fld in h and h[fld] not in ("", None), f"hook {hid}: missing field {fld}")
        try:
            compiled[hid] = re.compile(h["match"], re.IGNORECASE)
            passes += 1
        except re.error as e:
            failures.append(f"hook {hid}: regex does not compile: {e}")
        # text hygiene
        for fld in TEXT_FIELDS:
            v = h.get(fld, "")
            check("ي" not in v and "ك" not in v, f"hook {hid}.{fld}: Arabic ي/ك present")
            check("—" not in v, f"hook {hid}.{fld}: em dash present")
            check(not re.search(r"(?<![؀-ۿ])ن?می (?=[؀-ۿ])", v),
                  f"hook {hid}.{fld}: «می» with a plain space instead of half-space")
        for fld in ("example", "on_screen"):
            check(not re.search(r"[0-9]", h.get(fld, "")), f"hook {hid}.{fld}: Latin digits")
        words = len(h.get("on_screen", "").split())
        check(words <= 6, f"hook {hid}.on_screen has {words} words (>6)")

    if len(compiled) != 26:
        report(passes, failures)
        return

    for h in hooks:
        got = classify(h["example"], compiled, order)
        check(got == h["id"], f"example of {h['id']} classified as {got}: {h['example']}")

    covered = set()
    for text, exp in EXTRA:
        got = classify(text, compiled, order)
        covered.add(exp)
        check(got == exp, f"extra expected {exp}, got {got}: {text}")
    check(covered == set(range(1, 27)), f"extra tests do not cover all formulas: missing {set(range(1, 27)) - covered}")
    check(len(EXTRA) >= 26, "need at least 26 extra tests")

    for text in NEUTRAL:
        got = classify(text, compiled, order)
        check(got is None, f"neutral classified as {got}: {text}")
    check(len(NEUTRAL) >= 8, "need at least 8 neutral tests")

    report(passes, failures)


def report(passes, failures):
    for f in failures:
        print("FAIL:", f)
    print(f"passed: {passes}  failed: {len(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
