"""Read Instagram «Insights» screenshots with a vision model, write a Persian analysis, and feed the
dashboard with zero setup — no Meta app or token. The numbers go in through the «screenshot» source
shape.py already knows: a daily account row in raw/account.json, and (when a reel's link is visible)
reels in raw/norm/screenshot.json. Everything the model can't read stays null; nothing is invented."""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone

from . import ai, config, ig, pipeline
from .agents import S, arr, obj

TEHRAN = timezone(timedelta(hours=3.5))

SN = {"type": ["string", "null"]}
IN = {"type": ["integer", "null"]}
FN = {"type": ["number", "null"]}

SHOT_SCHEMA = obj({
    "account": obj({"followers": IN, "reach": IN, "views": IN, "accounts_engaged": IN, "period": SN},
                   "the account overview numbers if a screenshot shows them, else null"),
    "reels": arr(obj({"caption": SN, "url": SN, "views": IN, "reach": IN, "likes": IN,
                      "comments": IN, "saves": IN, "shares": IN, "watch_seconds": FN, "published": SN}),
                 "one entry per reel/post whose numbers are visible"),
    "best_times": arr(obj({"day": SN, "hour": IN}), "best posting times if shown (day name + hour 0-23)"),
    "audience": obj({"top_countries": arr(S), "top_cities": arr(S), "age_range": SN, "gender_split": SN,
                     "most_active": SN}, "audience breakdown if shown, else empty/null"),
    "analysis": S,
    "suggestions": arr(S),
    "read_notes": S,
})

SHOT_SYS = """تو دادهٔ تصویریِ اینستاگرام رو می‌خونی. چند اسکرین‌شات از بخشِ Insights/آمارِ یک پیجِ اینستاگرام بهت داده می‌شه (ممکنه فارسی یا انگلیسی باشه: «دنبال‌کننده‌ها/Followers»، «دسترسی/Reach»، «بازدیدها/Views»، «حساب‌های درگیرشده/Accounts engaged»، آمارِ یک ریل، بهترین ساعت‌ها، مخاطب‌ها).
قانون‌ها:
- فقط چیزی که واقعاً تو تصویر هست رو بنویس؛ هر چیزی که نیست رو null بذار. هیچ عددی از خودت نساز و حدس نزن.
- عددهای خلاصه‌شده رو کامل کن: «1.2K»=1200، «3.4M»=3400000، «۱۲٫۵ هزار»=12500. ارقامِ فارسی رو به عدد تبدیل کن.
- آمارِ یک ریل رو فقط وقتی در reels بذار که مطمئنی مالِ یک پست مشخصه؛ اگه لینک/شناسهٔ ریل تو تصویر بود در url بذار.
- followers فقط تعدادِ کلِ دنبال‌کننده‌ها (نه دسترسی).
تحلیل (analysis): ۳ تا ۵ جملهٔ کوتاهِ فارسیِ محاوره‌ای و صادقانه دربارهٔ وضعیت (چی خوبه، کجا ضعفه)، بر پایهٔ همین عددها نه کلیات.
پیشنهادها (suggestions): ۳ تا ۵ کارِ مشخص و قابل‌انجام برای همین پیج.
read_notes: اگه چیزی ناخوانا بود یا مطمئن نبودی، کوتاه بگو."""


def _num(v):
    return v if isinstance(v, (int, float)) else None


def to_jpeg(path, max_w=1400):
    """Any uploaded image (PNG/JPEG/WebP) -> downscaled JPEG bytes for the vision model (ffmpeg reads
    the real format by content, so the file extension doesn't matter)."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale='min({max_w},iw)':-2",
                        "-frames:v", "1", "-f", "mjpeg", "-q:v", "4", "pipe:1"],
                       capture_output=True, timeout=60)
    if p.returncode != 0 or not p.stdout:
        raise ValueError("این فایل عکسِ معتبری نیست")
    return p.stdout


def analyze(user, images):
    """images: list of JPEG bytes. Returns the extracted + written dict (strict schema)."""
    msg = [{"role": "user", "content": "این‌ها اسکرین‌شات‌های اینستاگرامِ منن. طبق قانون‌ها بخون و پر کن."}]
    return ai.ask(user, SHOT_SYS, msg, schema=SHOT_SCHEMA, max_tokens=4000, images=images)


def _apply(user, ex):
    """Write what the dashboard can use, through shape.py's «screenshot» source. Returns a summary."""
    raw = config.user_dir(user["id"]) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    filled = {"followers": None, "reels": 0}

    acc = ex.get("account") or {}
    if any(_num(acc.get(k)) is not None for k in ("followers", "reach", "views", "accounts_engaged")):
        today = datetime.now(TEHRAN).strftime("%Y%m%d")
        path = raw / "account.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": []}
        except Exception:  # noqa: BLE001
            data = {"rows": []}
        rows = [r for r in (data.get("rows") or []) if not (r and str(r[-1]) == today)]  # replace today's
        # columns shape.py expects: followers, gained, lost, reels, reels_views, reels_reach, reels_shares, views, reach, engaged, DATE
        rows.append([_num(acc.get("followers")), None, None, None, None, None, None,
                     _num(acc.get("views")), _num(acc.get("reach")), _num(acc.get("accounts_engaged")), today])
        path.write_text(json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
        filled["followers"] = _num(acc.get("followers"))

    reels = []
    for r in ex.get("reels") or []:
        code = ig_shortcode(r.get("url"))
        if not code:
            continue  # without a link we can't place a reel on the right post
        rec = {"shortcode": code}
        for k in ("views", "reach", "likes", "comments", "saves", "shares"):
            if _num(r.get(k)) is not None:
                rec[k] = _num(r.get(k))
        if _num(r.get("watch_seconds")) is not None:
            rec["avg_watch"] = _num(r.get("watch_seconds"))
        if r.get("caption"):
            rec["caption"] = str(r["caption"])[:400]
        if len(rec) > 1:
            reels.append(rec)
    if reels:
        norm = raw / "norm"
        norm.mkdir(parents=True, exist_ok=True)
        (norm / "screenshot.json").write_text(json.dumps({"source": "screenshot", "reels": reels}, ensure_ascii=False), encoding="utf-8")
        filled["reels"] = len(reels)

    if filled["followers"] is not None or filled["reels"]:
        pipeline.run_script(user["id"], "shape.py", {})  # rebuild data.json so the dashboard shows it
    return filled


def ig_shortcode(url):
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]+)", str(url or ""))
    return m[1] if m else None


def run(user, images):
    """Full pass: read the screenshots, write the analysis to history, feed the dashboard."""
    ex = analyze(user, images)
    filled = _apply(user, ex)
    rec = {"at": int(time.time()), "analysis": ex.get("analysis", ""), "suggestions": ex.get("suggestions", []),
           "read_notes": ex.get("read_notes", ""), "account": ex.get("account"), "reels": ex.get("reels"),
           "best_times": ex.get("best_times"), "audience": ex.get("audience"), "filled": filled}
    d = config.user_dir(user["id"]) / "content"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "screenshot.json"
    try:
        hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        hist = hist if isinstance(hist, list) else []
    except Exception:  # noqa: BLE001
        hist = []
    hist.insert(0, rec)
    path.write_text(json.dumps(hist[:20], ensure_ascii=False), encoding="utf-8")
    return rec
