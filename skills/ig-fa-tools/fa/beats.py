"""A timed beat sheet for a Persian Reel script, before it's shot: how long each line takes to say,
stacked into timecodes, with the four things that kill a Reel in the edit flagged: a hook past 3
seconds, a beat long enough to leave on, a run of lines with nothing concrete in them, and no loop
back to the first line. Same idea as beats.py in instagram-agent-skill, counted in Persian: a number
written as digits is said as several words («۱۸,۰۰۰» is «هجده هزار»)."""
import math, re

from .text import NUMBER_RE, concrete_markers, latin_digits, normalize, squash, words

WPM = 150
HOOK_WINDOW = 3.0   # seconds; past this the thumb has already decided
MAX_BEAT = 4.0      # seconds on one idea with no change on screen
ABSTRACT_RUN = 3    # beats in a row with nothing checkable in them
STOP = {squash(w) for w in """
و که از به با در تو این اون آن رو را یه یک هم برای تا ولی اما چی چه من ما شما اگه اگر هست است بود شد کرد کن می
ها های یا هر همه خیلی دیگه باید کنی کنم کنه کنید داره دارم داری بعد قبل وقتی چون پس اینو اونو ازش بهش براش
""".split()}
ASK_RE = re.compile(r"کامنت|ذخیره|سیو|فالو|دایرکت|بفرست|لینک|کلمه|بنویس")


def spoken_count(text):
    """Words as said aloud: digits become the number words they're read as."""
    n = 0
    for w in words(text):
        digits = re.sub(r"\D", "", latin_digits(w))
        if NUMBER_RE.fullmatch(w) and digits:
            v = int(digits)
            n += 1 if v < 100 else 2 if v < 10000 else 3
        else:
            n += 1
    return n


def split_beats(script, wps):
    """One beat per line; a long line with several sentences becomes one beat per sentence."""
    out = []
    for line in [l.strip() for l in normalize(script).split("\n") if l.strip()]:
        if spoken_count(line) / wps <= MAX_BEAT:
            out.append(line)
            continue
        parts = [p.strip() for p in re.findall(r"[^.!?؟]+[.!?؟]*", line) if p.strip()]
        out.extend(parts or [line])
    return out


def content_words(text):
    return {squash(w) for w in words(text) if squash(w) not in STOP and len(squash(w)) >= 3}


def analyse(script, wpm=WPM, target=None):
    wps = wpm / 60.0
    beats, t = [], 0.0
    for i, line in enumerate(split_beats(script, wps)):
        n = spoken_count(line)
        secs = max(n / wps, 0.6)
        nums, names, quoted, spoken = concrete_markers(line)
        beats.append({"start": round(t, 1), "secs": round(secs, 1), "words": n, "text": line,
                      "concrete": bool(nums or names or quoted or spoken)})
        t += secs
    if not beats:
        return {"beats": [], "total": 0, "words": 0, "wpm": wpm, "target": target, "flags": [], "loop": False}
    beats[0]["label"] = "هوک"
    if len(beats) > 1:
        beats[-1]["label"] = "دعوت" if ASK_RE.search(beats[-1]["text"]) else "پایان"
    flags = []
    if beats[0]["secs"] > HOOK_WINDOW:
        flags.append(f"هوک {beats[0]['secs']:.1f} ثانیه طول می‌کشه؛ باید زیر {HOOK_WINDOW:.0f} ثانیه باشه. کوتاهش کن یا نصفش رو بده به متن روی صفحه.")
    for i, b in enumerate(beats[1:], 2):
        if b["secs"] > MAX_BEAT:
            b["long"] = True
            flags.append(f"صحنهٔ {i} {b['secs']:.1f} ثانیه‌ست. یا جمله رو بشکن یا وسطش تصویر رو عوض کن؛ قاب ثابت جاییه که مردم می‌رن.")
    run = 0
    for i, b in enumerate(beats, 1):
        run = 0 if b["concrete"] else run + 1
        if run == ABSTRACT_RUN:
            flags.append(f"صحنه‌های {i - ABSTRACT_RUN + 1} تا {i} هیچ عدد، اسم یا چیز مشخصی ندارن. یه عدد یا مثال واقعی بذار.")
    shared = content_words(beats[0]["text"]) & content_words(beats[-1]["text"]) if len(beats) > 1 else set()
    loop = bool(shared)
    flags.append(f"حلقه: جملهٔ آخر «{sorted(shared)[0]}» هوک رو تکرار می‌کنه؛ دوباره‌دیدن رایگانه." if loop else
                 "حلقه نداره: یه کلمه از هوک رو تو جملهٔ آخر تکرار کن تا ویدیو از اول پخش بشه و تمیز وصل بشه.")
    total = round(t, 1)
    if target:
        gap = target - total
        if gap > 3:
            flags.append(f"{gap:.1f} ثانیه کمتر از هدف. یا {math.ceil(gap * wps)} کلمه اضافه کن یا کوتاه‌تر فیلم بگیر؛ معمولاً کوتاه‌تر درسته.")
        elif gap < -3:
            flags.append(f"{-gap:.1f} ثانیه بیشتر از هدف. حدود {math.ceil(-gap * wps)} کلمه کم کن.")
    return {"beats": beats, "total": total, "words": sum(b["words"] for b in beats), "wpm": wpm, "target": target,
            "flags": flags, "loop": loop}
