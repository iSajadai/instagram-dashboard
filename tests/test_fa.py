"""The Persian tools on real Persian text. Run: python -m pytest tests/test_fa.py  (or python tests/test_fa.py)"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sajadai.fa import beats, caption, hooks, human, viral  # noqa: E402
from sajadai.fa.text import ZWNJ, words  # noqa: E402

GOOD_HOOKS = [
    "هیچ‌کس بهت نمی‌گه ۳۰ ریل اولت قراره شکست بخوره.",
    "۱۸ میلیون تومن پای یه بند قرارداد دادم.",
    "پروپوزال‌هام ۵ ساعت طول می‌کشید. الان ۲۰ دقیقه.",
    "دیگه با ChatGPT اینجوری پرامپت ننویس.",
]
WEAK_HOOKS = [
    "سلام بچه‌ها، امروز می‌خوام درباره‌ی استراتژی محتوا صحبت کنم",
    "تو این ویدیو قراره بهتون یه چیز جالب نشون بدم",
    "اسکرول نکن! این ویدیو رو تا آخر ببین 🔥",
    "خب، یه نکته‌ی خیلی مهم درباره‌ی موفقیت",
]
HUMAN_CAPTION = """دیروز سه ساعت با ChatGPT ور رفتم که یه پرامپت درست برای خلاصه کردن جلسه‌هام بنویسم.
آخرش فهمیدم مشکل از خودم بود: بهش نگفته بودم خلاصه رو برای کی می‌خوام.
یه خط اضافه کردم «برای مدیری که ۳۰ ثانیه وقت داره» و جوابش کلاً عوض شد.
تو هم امتحانش کن و بگو چی شد. اگه نسخه‌ی کاملش رو می‌خوای، کلمه‌ی «پرامپت» رو کامنت کن."""
AI_TEXT = """در دنیای پرشتاب امروز، هوش مصنوعی نقش کلیدی در زندگی ما ایفا می‌کند. لازم به ذکر است که این فناوری انقلابی نه تنها بهره‌وری را افزایش می‌دهد بلکه خلاقیت را نیز متحول می‌سازد.
بیایید با هم نگاهی عمیق‌تر به این موضوع بیندازیم. این فقط یک ابزار نیست، بلکه یک همراه هوشمند است.
نتیجه؟ تجربه‌ای بی‌نظیر، سریع و کاربردی. در نهایت می‌توان گفت که آینده متعلق به کسانی است که از این فرصت بهره‌گیری نمایند.
امیدوارم این مطلب برای شما مفید بوده باشد."""


def test_words_keep_halfspace():
    ws = words("می‌خوام ریل‌هام رو ببینم")
    assert ws[0] == "می" + ZWNJ + "خوام" and len(ws) == 4


def test_good_hooks_beat_weak_ones():
    good = [hooks.score(h)["overall"] for h in GOOD_HOOKS]
    weak = [hooks.score(h)["overall"] for h in WEAK_HOOKS]
    assert min(good) > max(weak), (good, weak)
    assert all(hooks.score(h)["verdict"] == "WEAK" for h in WEAK_HOOKS[:3])
    assert all(hooks.score(h)["flags"] for h in WEAK_HOOKS[:3])


def test_negation_is_a_stake_but_not_every_noon_word():
    assert hooks.is_stake("نمی‌گه") and hooks.is_stake("نکن") and hooks.is_stake("نداره")
    assert not hooks.is_stake("نکته") and not hooks.is_stake("نتیجه") and not hooks.is_stake("نوشتم")


def test_beats_count_persian_digits_and_flag_long_hook():
    s = beats.analyse("۱۸ میلیون تومن پای یه بند قرارداد دادم.\nبند چهار: پرداخت با تحویل، نه با تأیید.\nتأیید یه حسه، تحویل یه تاریخه.\nهمین یه کلمه ۱۸ میلیون برام ارزش داشت.")
    assert len(s["beats"]) == 4 and s["loop"] and s["beats"][0]["secs"] < 3.5
    long = beats.analyse("سلام به همه‌ی دوستای عزیزم که دارن این ویدیو رو می‌بینن امروز می‌خوام یه موضوع خیلی خیلی مهم رو با هم بررسی کنیم")
    assert any("هوک" in f for f in long["flags"])


def test_caption_linter():
    ok = caption.analyse(HUMAN_CAPTION, ["پرامپت", "خلاصه کردن جلسه"])
    assert ok["verdict"] in ("READY", "REVIEW") and ok["asks"] == ["کامنت"], ok
    assert next(c for c in ok["checks"] if c["check"] == "کلمهٔ کامنت")["status"] == "PASS"
    bad = caption.analyse("سلام دوستان 😍😍\nلینک: https://example.com\nفالو کن و کامنت بذار و سیوش کن\n" + " ".join(f"#تگ{i}" for i in range(9)))
    status = {c["check"]: c["status"] for c in bad["checks"]}
    assert bad["verdict"] == "FIX" and status["خط اول"] == "FAIL" and status["هشتگ"] == "FAIL" and status["لینک"] == "WARN"
    assert len(bad["asks"]) == 3
    spaced = caption.analyse("من می خوام ریل ها رو ببینم و بهترینش رو ذخیره کن")
    assert next(c for c in spaced["checks"] if c["check"] == "نیم‌فاصله")["status"] == "WARN"


def test_humanizer_keeps_and_fixes_halfspaces():
    clean, rep = human.humanize("من می خوام ریل ها رو​ ببینم — ولی “اول” بگو…")
    assert "می" + ZWNJ + "خوام" in clean and "ریل" + ZWNJ + "ها" in clean
    assert "​" not in clean and "—" not in clean and "«اول»" in clean and "..." in clean
    assert rep["halfspace"] == 2 and rep["invisible"] == 1
    kept, _ = human.humanize("می‌خوام کتاب‌هام رو بفروشم")
    assert kept == "می‌خوام کتاب‌هام رو بفروشم"


def test_humanizer_persian_digits_but_not_in_names_or_links():
    assert human.humanize("من 47 تا ریل گذاشتم، قیمت 18,000 تومن و 2.5 برابر")[0] == "من ۴۷ تا ریل گذاشتم، قیمت ۱۸٬۰۰۰ تومن و ۲٫۵ برابر"
    kept = human.humanize("با GPT-4 کار کن و لینک https://a.com/2024 و @user_12 رو تو ساعت 19:30 ببین")[0]
    assert "GPT-4" in kept and "https://a.com/2024" in kept and "@user_12" in kept and "19:30" in kept


def test_humanizer_replaces_bureaucratic_words():
    clean, rep = human.humanize("این ابزار بسیار کاربردی می‌باشد و جهت یادگیری استفاده می‌شود.")
    assert "می‌باشد" not in clean and "جهت" not in clean and rep["replaced"]


def test_detector_separates_ai_from_human():
    h, a = human.detect(HUMAN_CAPTION), human.detect(AI_TEXT)
    assert h["overall"] > a["overall"] + 20, (h, a)
    assert a["verdict"] != "PASS"
    assert human.slop_hits(AI_TEXT) and not human.slop_hits(HUMAN_CAPTION)
    assert {f["id"] for f in human.structure_flags(AI_TEXT)} >= {"not-only"}


def test_slop_spelling_variants_count_once():
    assert sum(n for _, n in human.slop_hits("این ابزار مفید می‌باشد.")) == 1
    assert sum(n for _, n in human.slop_hits("این ابزار مفید می باشد.")) == 1


def test_formula_classification():
    assert hooks.classify("هیچ‌کس بهت نمی‌گه که ۳۰ ریل اولت شکست می‌خوره")[0] == 3
    assert hooks.classify("امروز درباره‌ی هوش مصنوعی حرف می‌زنیم")[0] is None
    assert hooks.classify("۱۸ میلیون تومن پای یه بند قرارداد دادم.")[0] == 1  # «پای چیزی دادن» is a cost confession
    for f in hooks.formulas():
        assert hooks.classify(f["example"])[0] == f["id"], (f["id"], f["example"], hooks.classify(f["example"]))


def test_swipe_ranks_by_multiple_not_views():
    rows = viral.read_rows("حساب\tفالوئر\tمیانه\tبازدید\tهوک\n@big\t2000000\t500000\t400000\tاین ویدیو رو ببینید\n"
                           "@small\t4000\t2000\t80000\tهیچ‌کس بهت نمی‌گه ریل اول شکست می‌خوره\n@mid\t20000\t5000\t6000\tسلام دوستان")
    s = viral.swipe(rows)
    assert [r["account"] for r in s["ranked"]] == ["@small", "@mid", "@big"]
    assert s["ranked"][0]["multiple"] == 40 and s["outliers"][0]["formula_id"] == 3


def test_skill_copy_matches_the_package():
    """skills/ig-fa-tools/fa is a copy of sajadai/fa; rebuild with `python -m sajadai build-skills` after a change."""
    import filecmp
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src, dst = os.path.join(root, "sajadai", "fa"), os.path.join(root, "skills", "ig-fa-tools", "fa")
    for sub in ("", "data"):
        names = [n for n in os.listdir(os.path.join(src, sub)) if n.endswith((".py", ".json"))]
        _, mismatch, errors = filecmp.cmpfiles(os.path.join(src, sub), os.path.join(dst, sub), names, shallow=False)
        assert not mismatch and not errors, (mismatch, errors)

if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e)[:600])
    sys.exit(1 if fails else 0)
