"""The content studio: the 13 agents of instagram-agent-skill (MIT, Jake Schincariol), localized for
Persian creators and wired into the panel. Each agent is a prompt adapted from its SKILL.md, a strict
output schema (so Claude and OpenAI both return the same shape), and then the Persian tools in
sajadai/fa run on what the model wrote: hooks are scored and the weak ones sent back, scripts are
timed, captions are linted and repaired, and everything shown is passed through the humanizer.

Nothing here posts anything. The agents write; the user posts."""
import json, re, time
from datetime import datetime, timedelta, timezone

from . import ai, analysis, calendar_fa, config
from .fa import beats, caption, hooks, human, viral
from .fa.text import data, fa_digits, words

TEHRAN = timezone(timedelta(hours=3, minutes=30))

# ---------- shared ----------

class InputError(Exception):
    """Something the user has to add or fix in the form (shown as is)."""


PERSIAN_RULES = """Write everything the user will read in Persian (Farsi, Iran), in the page's voice.
- Register: unless the voice profile says formal, write conversational written Persian the way Iranians type on Instagram (محاوره‌نویسی: «می‌خوام»، «اینو»، «یه»، «می‌کنه»), not translated or bureaucratic Persian. Never «می‌باشد»، «جهت»، «نمود»، «گردید»، «لازم به ذکر است»، «در دنیای امروز»، «نقش کلیدی ایفا می‌کند», never calques like «سفر یادگیری»، «غوطه‌ور شدن»، «کاوش».
- Spelling: correct half-spaces (U+200C) as in «می‌خوام»، «ریل‌ها»، «هوش‌مصنوعی» is two words «هوش مصنوعی». Persian digits in Persian text (۱۸ میلیون تومن). Money in تومن in speech. «» for quotes. No em dashes (—). No English unless it's a name (ChatGPT, Claude) or a term the audience uses in English.
- Never invent numbers, clients, revenue, results, quotes or stats under the user's name. If a number is needed and unknown, write {{عدد خودت}} and say so.
- Short lines. One idea per post. Numbers over adjectives. No greeting, no «تو این ویدیو», no «اسکرول نکن».
- The user posts everything by hand; never say you posted, scheduled or sent anything."""


def obj(props, desc=None):
    """A strict JSON-schema object: every property required, nothing extra (OpenAI strict mode needs this)."""
    o = {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    if desc:
        o["description"] = desc
    return o


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}


def arr(items, desc=None):
    a = {"type": "array", "items": items}
    if desc:
        a["description"] = desc
    return a


def formulas_brief():
    return "\n".join(f"#{f['id']} {f['name']} — قالب: {f['template']} — مثال: {f['example']} — روی صفحه: {f['on_screen']} — دام: {f['trap']}"
                     for f in hooks.formulas())


def load(user, name, default):
    v = analysis.load(config.user_dir(user["id"]) / "content" / name)
    return v if isinstance(v, type(default)) and v else default


def save(user, name, value):
    p = config.user_dir(user["id"]) / "content" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


def voice_of(user):
    from . import store
    return store.prefs(user).get("voice") or {}


def voice_text(user):
    from . import store
    p = store.prefs(user)
    v = p.get("voice") or {}
    parts = []
    if p.get("page_name"):
        parts.append("اسم پیج: " + p["page_name"])
    if p.get("page_profile"):
        parts.append("معرفی پیج: " + p["page_profile"])
    labels = {"who": "کی هستم", "audience": "با کی حرف می‌زنم", "sells": "چی می‌فروشم", "samples": "نمونه‌هایی از متن خودم",
              "on_camera": "جلوی دوربین", "words_used": "کلمه‌هایی که استفاده می‌کنم", "words_never": "کلمه‌هایی که هیچ‌وقت نمی‌گم",
              "emoji": "ایموجی", "face": "صورت تو ویدیو", "positions": "باورهام", "off_limits": "ممنوع‌ها", "proof": "مدرک‌هایی که می‌تونم بگم",
              "keyword": "کلمهٔ کامنت", "keyword_sends": "کلمهٔ کامنت چی می‌فرسته", "link": "لینک", "register": "لحن"}
    for k, lbl in labels.items():
        if v.get(k):
            parts.append(f"{lbl}: {v[k]}")
    return "\n".join(parts) or "(پروفایل صدا هنوز پر نشده؛ از کپشن‌های ریل‌های پیج لحن رو حدس بزن.)"


def casual(user):
    return (voice_of(user).get("register") or "casual") != "formal"


def wpm(user):
    try:
        return max(90, min(260, int(voice_of(user).get("wpm") or beats.WPM)))
    except (TypeError, ValueError):
        return beats.WPM


def page_numbers(user):
    """What the page's own data says, for agents that should work from evidence."""
    d = analysis.load(config.user_dir(user["id"]) / "data" / "data.json") or {}
    reels, med = analysis.scored(d)
    best = sorted([r for r in reels if r.get("multiple_of_median") is not None], key=lambda r: -r["multiple_of_median"])[:6]
    return {"median_views": med, "reels": len(reels),
            "best_reels": [{"first_line": (r["caption"] or "").split("\n")[0][:120], "multiple": r["multiple_of_median"],
                            "hold_3s": r["view_rate_3s_pct"], "shares_per_1k": r["shares_per_1k_reach"]} for r in best],
            "best_times": analysis.best_times(d, 5)}


def upcoming_occasions(days=16):
    """Iran's occasions from today (Tehran) for the next days, as lines the planner can read."""
    start = datetime.now(TEHRAN).date()
    return [f"{calendar_fa.WEEKDAYS[calendar_fa.weekday(o['date'])]} {calendar_fa.jfmt(o['date'])}: {o['title']}"
            + (" (تعطیل رسمی)" if o["holiday"] else "") + (" (تاریخ تقریبی)" if o["approximate"] else "")
            for o in calendar_fa.occasions_between(start, start + timedelta(days=days))]


def context(user, *, numbers=False, swipe=False, plan=False, audit=False, occasions=False):
    parts = ["پروفایل صدا و پیج:\n" + voice_text(user)]
    if numbers:
        parts.append("عددهای خود پیج: " + json.dumps(page_numbers(user), ensure_ascii=False))
    if swipe and load(user, "swipe.json", {}):
        s = load(user, "swipe.json", {})
        parts.append("فایل سوایپ (شواهد خود کاربر از اینکه چی تو این حوزه جواب می‌ده؛ از پیش‌فرض‌ها مهم‌تره): "
                     + json.dumps({k: s.get(k) for k in ("over_index", "your_versions", "findings")}, ensure_ascii=False))
    if audit and load(user, "audit.json", {}):
        a = load(user, "audit.json", {})
        parts.append("نتیجهٔ آخرین تحلیل پست‌های خود پیج: " + json.dumps({k: a.get(k) for k in ("findings", "stop", "do_more")}, ensure_ascii=False))
    if occasions and upcoming_occasions():
        parts.append("مناسبت‌های دو هفتهٔ آینده در ایران (فقط اگه به موضوع پیج می‌خوره یه پست رو بهش گره بزن؛ تو روزهای عزاداری لحن شوخ و فروش مستقیم نذار):\n"
                     + "\n".join(upcoming_occasions()))
    if plan and load(user, "plan.json", {}):
        parts.append("برنامهٔ هفتهٔ قبل (موضوع‌ها تکرار نشن): " + json.dumps(load(user, "plan.json", {}).get("days", []), ensure_ascii=False)[:2500])
    return "\n\n".join(parts)


def ask(user, system, task, schema, max_tokens=6000, effort="medium"):
    return ai.ask(user, PERSIAN_RULES + "\n\n" + system, [{"role": "user", "content": task}], schema=schema,
                  max_tokens=max_tokens, effort=effort)


def clean(user, text):
    """The humanizer's automatic pass (characters, typography, half-spaces, stock words)."""
    return human.humanize(text)[0] if text else text


def scored_text(user, text):
    out = human.run(text, casual(user))
    return {"text": out["clean"], "score": out["after"], "flags": out["report"]["flags"]}


def remember(user, agent, inp, out):
    h = load(user, "studio_history.json", [])
    h.insert(0, {"at": int(time.time()), "agent": agent, "input": inp, "output": out})
    save(user, "studio_history.json", h[:40])


def need(inp, key, label):
    v = str(inp.get(key) or "").strip()
    if not v:
        raise InputError(f"«{label}» رو بنویس")
    return v[:12000]


# ---------- 1. reel ----------

HOOK = obj({"formula_id": I, "spoken": S, "on_screen": S})
REEL_SCHEMA = obj({
    "thin": B, "question": S, "two_ideas": S,
    "hooks": arr(HOOK, "exactly 3, three different formulas"),
    "chosen": I, "why": S,
    "script": arr(S, "the spoken script, one beat per item, starting with the chosen hook's spoken line"),
    "cards": arr(obj({"beat": I, "text": S}), "on-screen text cards, 6 words or fewer, beat = 1-based beat index"),
})
REEL_SYS = """You are «ریل‌ساز» (ig-reel): you turn one raw idea into a Persian Instagram Reel somebody finishes.
Shape: 0-2s HOOK (spoken line and on-screen line written separately, ≤6 words on screen); 2-7s THE STAKE (why it matters to the viewer, one line); then THE BODY, one idea per beat and the frame changes every beat; last 3s THE PAYOFF (deliver what the hook promised, then ONE ask: comment a keyword, save, or follow); LAST LINE: THE LOOP, echo one word from the hook. 15-45 seconds.
Write three hooks from three DIFFERENT formulas of the 26 below that genuinely fit the idea; spoken lines 4-11 words, payload in the first three words, a number or a name in it, something at stake, speaking to «تو/شما». If the idea is too thin to make a Reel (no specific true thing: what happened, to whom, what it cost or returned), set thin=true and put ONE batched question in "question", and still return your best attempt. If the idea holds two ideas, say so in "two_ideas" (else ""). Script lines are short, spoken, in the user's voice, the way they'd actually say it (no sentence they'd have to rehearse). Cards: on-screen text for the beats that need it, the hook card at beat 1. "chosen" is the 0-based index of the hook you'd shoot.
The 26 hook formulas:
"""


def run_reel(user, inp):
    idea = need(inp, "idea", "ایدهٔ ریل")
    target = int(inp.get("length") or 30)
    want = f" Use formula #{int(inp['formula'])} for one of the hooks." if str(inp.get("formula") or "").isdigit() else ""
    system = REEL_SYS + formulas_brief() + "\n\n" + context(user, numbers=True, swipe=True)
    task = f"ایده: {idea}\nطول هدف: {target} ثانیه.{want}"
    out = ask(user, system, task, REEL_SCHEMA, 8000)
    ranked = hooks.rank([h["spoken"] for h in out["hooks"]], wpm(user))
    if ranked and ranked[0]["overall"] < 50:  # no hook yet: send the scores back once, as the skill says
        fb = "\n".join(f"«{r['text']}» امتیاز {r['overall']:.0f}، ضعیف‌ترین: {r['weakest_fa']} ({next(c['detail'] for c in r['checks'] if c['id'] == r['weakest'])})"
                       + (f"، مشکل: {' '.join(r['flags'])}" if r["flags"] else "") for r in ranked)
        out = ask(user, system, task + "\n\nهوک‌های قبلی ضعیف بودن (زیر ۵۰ از ۱۰۰):\n" + fb +
                  "\nسه هوک تازه بنویس که این ضعف‌ها رو نداشته باشن، و فیلمنامه رو با بهترینش بنویس.", REEL_SCHEMA, 8000)
        ranked = hooks.rank([h["spoken"] for h in out["hooks"]], wpm(user))
    by_text = {r["text"]: r for r in ranked}
    hk = []
    for h in out["hooks"]:
        f = hooks.formula(h["formula_id"]) or {}
        hk.append({**h, "spoken": clean(user, h["spoken"]), "on_screen": clean(user, h["on_screen"]),
                   "formula": f.get("name", ""), "score": by_text.get(h["spoken"])})
    hk.sort(key=lambda h: -(h["score"] or {}).get("overall", 0))
    script = [clean(user, l) for l in out["script"] if l.strip()]
    sheet = beats.analyse("\n".join(script), wpm(user), target)
    whole = scored_text(user, "\n".join(script))
    return {"thin": out["thin"], "question": out["question"], "two_ideas": out["two_ideas"], "why": clean(user, out["why"]),
            "hooks": hk, "script": script, "cards": [{**c, "text": clean(user, c["text"])} for c in out["cards"]],
            "beats": sheet, "human": whole["score"], "flags": whole["flags"]}


# ---------- 2. viral ----------

VIRAL_SCHEMA = obj({
    "findings": arr(S, "at most 3: which formulas over-index (with counts), what the top third share structurally, and the unclassified rows"),
    "unclassified_note": S, "confidence": S,
    "your_versions": arr(obj({"formula_id": I, "hook": S, "why": S}), "3 hooks the user could say tomorrow, their own story and number, in the shape that's working"),
})
VIRAL_SYS = """You are «تحقیق وایرال» (ig-viral). Raw views are not evidence; the outlier multiple (views ÷ that account's own median) is. Above 3× is a signal, under 1.5× is that account's normal day. You get the ranked rows already computed (multiple, formula, hook score) by a script, so don't recompute. Report three things and no more: which formulas over-index in the top third (with counts; two formulas appearing four times across six accounts is a finding, one appearing twice is not), what the top third share structurally that the bottom third don't (hook length, the payoff, where the ask is), and the unclassified rows (noise, or a formula not in the list yet — read them). Then state the sample size and the confidence in plain words. Then write the user's own version for the top three formulas: a hook line they could say tomorrow, from their own story, with {{عدد خودت}} where you don't know their number. Copy the formula, never the video.
The 26 formulas:
"""


def competitor_rows(user):
    """Swipe rows from the competitors on the dashboard (Business Discovery gives each reel's views):
    account, followers, the account's median views, this reel's views, the caption's first line as the hook."""
    d = analysis.load(config.user_dir(user["id"]) / "data" / "data.json") or {}
    comp = {c["screen_name"].lower(): c for c in d.get("competitors", []) if c.get("screen_name")}
    rows = []
    for r in d.get("competitor_reels", []):
        c = comp.get(str(r.get("competitor") or "").lower(), {})
        hook = re.split(r"[\n.!?؟]", str(r.get("text") or "").strip())[0][:200]
        if r.get("views") and c.get("median_views") and hook:
            rows.append({"account": r["competitor"], "followers": c.get("followers") or 0, "median": c["median_views"],
                         "views": r["views"], "hook": hook})
    return rows


def run_viral(user, inp):
    rows = viral.read_rows(inp.get("rows")) if str(inp.get("rows") or "").strip() else competitor_rows(user)
    if len(rows) < 3:
        raise InputError("دست‌کم ۳ ردیف لازمه: حساب، فالوئر، میانهٔ بازدید، بازدید این ریل، هوک (با Tab یا ویرگول جدا). یا خالی بذار تا از ریل‌های رقبای صفحهٔ «رقبا» استفاده بشه (اتصال Facebook).")
    s = viral.swipe(rows)
    brief = {k: s[k] for k in ("n", "accounts", "over_index", "hook_words", "hook_score", "confidence")}
    brief["ranked"] = [{k: r[k] for k in ("account", "multiple", "formula_id", "hook_score", "hook")} for r in s["ranked"][:40]]
    brief["unclassified"] = [r["hook"] for r in s["unclassified"][:12]]
    out = ask(user, VIRAL_SYS + formulas_brief() + "\n\n" + context(user, audit=True),
              "حوزه: " + str(inp.get("niche") or "") + "\nداده‌ها:\n" + json.dumps(brief, ensure_ascii=False), VIRAL_SCHEMA)
    versions = [{**v, "hook": clean(user, v["hook"]), "why": clean(user, v["why"]), "formula": (hooks.formula(v["formula_id"]) or {}).get("name", ""),
                 "score": hooks.score(v["hook"], wpm(user))} for v in out["your_versions"]]
    result = {**s, "findings": [clean(user, f) for f in out["findings"]], "unclassified_note": clean(user, out["unclassified_note"]),
              "ai_confidence": clean(user, out["confidence"]), "your_versions": versions}
    save(user, "swipe.json", {"at": int(time.time()), "over_index": s["over_index"], "your_versions": versions, "findings": result["findings"]})
    return result


# ---------- 3. caption ----------

CAPTION_SCHEMA = obj({"job": {"type": "string", "enum": ["A", "B"]}, "why_job": S, "caption": S,
                      "hashtags": arr(S, "0 to 5, specific topic labels, Persian with underscores, without #"),
                      "alt_text": S, "first_comment": S})
CAPTION_SYS = """You are «کپشن‌نویس» (ig-caption). First decide the caption's job and say why: Job A = the Reel already hooked them (spoken and on-screen hook), so the caption is NOT a second hook: line one is the ask stated plainly with its context, and the body carries the words people search. Job B = the caption is the content (photo, single image, carousel cover): line one is the hook, concrete, short, ending on a cliff, not mid-clause.
Shape: line one has about 125 visible characters before «... more» (never a greeting, a hashtag, a mention, or an emoji as the first character); then 2-6 short paragraphs with a blank line between them, where the search phrases live as phrases a person would type, in normal sentences; ONE ask (comment a one-word keyword, save, or DM — one); hashtags: up to five (Instagram caps at five since Dec 2025), specific, as labels, on their own at the bottom, or none. #اکسپلور، #ویرال، #fyp، #فالو describe nothing. No link in the caption (not clickable): say «لینک تو بایو» or put it in first_comment. A keyword ask needs one word, no spaces, no emoji, and it should be said in the video too: «کلمهٔ «پرامپت» رو کامنت کن». Emoji as punctuation, not decoration. alt_text: one plain sentence describing the image/video for screen readers. Write caption WITHOUT the hashtags (they're added from "hashtags")."""


def caption_text(out):
    tags = " ".join("#" + re.sub(r"\s+", "_", t.strip().lstrip("#")) for t in out["hashtags"][:5] if t.strip())
    return (out["caption"].strip() + ("\n\n" + tags if tags else "")).strip()


def run_caption(user, inp, about=None):
    about = about or need(inp, "about", "این پست دربارهٔ چیه")
    kws = [k.strip() for k in re.split(r"[،,\n]", str(inp.get("keywords") or "")) if k.strip()]
    job = str(inp.get("job") or "auto")
    task = f"پست/ریل: {about}\nنوع کار کپشن: {job if job in ('A', 'B') else 'خودت تصمیم بگیر'}\nعبارت‌های جست‌وجو: {'، '.join(kws) or 'خودت دو سه تا پیشنهاد بده و تو متن بیار'}"
    system = CAPTION_SYS + "\n\n" + context(user)
    out = ask(user, system, task, CAPTION_SCHEMA)
    text = clean(user, caption_text(out))
    lint = caption.analyse(text, kws)
    if lint["verdict"] == "FIX":  # repair once with the linter's own words
        fails = "\n".join(f"- {c['check']}: {c['detail']}" for c in lint["checks"] if c["status"] == "FAIL")
        out = ask(user, system, task + "\n\nکپشن قبلی این ایرادها رو داشت، درستش کن:\n" + fails + "\n\nکپشن قبلی:\n" + text, CAPTION_SCHEMA)
        text = clean(user, caption_text(out))
        lint = caption.analyse(text, kws)
    sc = scored_text(user, out["caption"])
    return {"job": out["job"], "why_job": clean(user, out["why_job"]), "caption": text, "lint": lint, "human": sc["score"], "flags": sc["flags"],
            "alt_text": clean(user, out["alt_text"]), "first_comment": clean(user, out["first_comment"])}


# ---------- 4. carousel ----------

CAROUSEL_SCHEMA = obj({
    "is_carousel": B, "redirect_note": S,
    "slides": arr(obj({"role": {"type": "string", "enum": ["cover", "stake", "idea", "recap", "cta"]}, "headline": S, "body": S}),
                  "6 to 10 slides"),
    "caption_about": S, "alt_text": S,
})
CAROUSEL_SYS = """You are «کاروسل‌ساز» (ig-carousel). Use a carousel when the idea has sequence and needs re-reading: steps, a framework with parts, before/after, a list worth screenshotting. If the idea is one claim, it's neither: set is_carousel=false and explain in redirect_note that it should be a Reel (still return slides). 6-10 slides:
1 COVER: the hook, 6 words or fewer, plus one line of promise in body. The cover is 80% of the result.
2 STAKE: why it matters, one sentence; it's also a second cover (Instagram re-shows carousels from a later slide), so no setup.
3..N IDEA: one idea per slide; headline 3-7 words, at most 25 words of body. If it needs a paragraph it's two slides.
N+1 RECAP: the whole thing as a list, readable with no context: the screenshot-and-send slide.
LAST CTA: one action (save, comment a keyword, or follow). One.
caption_about: one line on what the caption should say (it's Job B: the caption does work because the cover used its six words). alt_text: describe the cover."""


def run_carousel(user, inp):
    idea = need(inp, "idea", "ایدهٔ کاروسل")
    out = ask(user, CAROUSEL_SYS + "\n\n" + context(user, numbers=True), "ایده: " + idea, CAROUSEL_SCHEMA)
    slides, warns = [], []
    for i, s in enumerate(out["slides"], 1):
        h, b = clean(user, s["headline"]), clean(user, s["body"])
        hw, bw = len(words(h)), len(words(b))
        if s["role"] == "cover" and hw > 6:
            warns.append(f"کاور {fa_digits(hw)} کلمه‌ست؛ شش تا یا کمتر.")
        elif s["role"] == "idea" and (hw > 7 or bw > 25):
            warns.append(f"اسلاید {fa_digits(i)}: تیتر {fa_digits(hw)} کلمه، متن {fa_digits(bw)} کلمه؛ تیتر ۳ تا ۷ و متن حداکثر ۲۵ کلمه. دو اسلایدش کن.")
        slides.append({"n": i, "role": s["role"], "headline": h, "body": b})
    if not 5 <= len(slides) <= 12:
        warns.append(f"{fa_digits(len(slides))} اسلاید؛ ۶ تا ۱۰ خوبه.")
    cap = run_caption(user, {"job": "B", "keywords": inp.get("keywords", "")},
                      about=out["caption_about"] + "\nاسلایدها: " + " | ".join(s["headline"] for s in slides))
    return {"is_carousel": out["is_carousel"], "redirect_note": clean(user, out["redirect_note"]), "slides": slides, "warnings": warns,
            "caption": cap, "alt_text": clean(user, out["alt_text"]), "handle": voice_of(user).get("handle", "")}


# ---------- 5. story ----------

STICKERS = ["none", "poll", "question", "quiz", "slider", "link", "countdown", "add_yours"]
STORY_SCHEMA = obj({
    "frames": arr(obj({"visual": S, "on_screen": S, "said": S, "sticker": {"type": "string", "enum": STICKERS}, "sticker_text": S,
                       "options": arr(S)}), "3 to 7 frames"),
    "after": S,
})
STORY_SCHEMA_SYS = """You are «استوری‌نویس» (ig-story). Stories aren't a smaller feed: only followers see them, so the job is depth, not reach: deciding whether this is a person worth buying from. 3-7 frames a day: 1 THE OPEN (something happening today, a face or a hand in it, never text on a coloured background); 2-3 THE MIDDLE (the process, the result, the mistake); 4 THE ASK (one sticker: poll = cheapest tap; question box = harvest the audience's exact words; quiz = teach a common misconception; slider = fun, low value; link = only clickable surface besides bio; countdown = a real deadline; add_yours = occasional reach); 5 THE CLOSE (the answer, the outcome, or tomorrow's setup). Ask at frame 4, not 7. One idea per frame, talk to one person («تو»). Never repost a feed post with no comment. Selling: three frames of context, one of offer, one of proof. The DM funnel: name a problem, let them say «این منم» with a sticker, then reply to each person who answered: they act first, then you reply. Never bulk-DM. "after": what to do with the answers. sticker="none" when the frame has none; options only for poll/quiz."""


def run_story(user, inp):
    today = need(inp, "today", "امروز چی شده / چی داری")
    out = ask(user, STORY_SCHEMA_SYS + "\n\n" + context(user), f"امروز: {today}\nهدف: {inp.get('goal') or 'ارتباط'}\nپیشنهاد/محصول: {inp.get('offer') or '-'}", STORY_SCHEMA)
    frames = [{"n": i, **{k: clean(user, v) if isinstance(v, str) else [clean(user, x) for x in v] if isinstance(v, list) else v for k, v in f.items()}}
              for i, f in enumerate(out["frames"], 1)]
    warns = []
    if not 3 <= len(frames) <= 7:
        warns.append(f"{fa_digits(len(frames))} فریم؛ ۳ تا ۷ خوبه. بعد از هفت، فریم‌های آخر برای هیچ‌کس پخش می‌شن.")
    ask_at = next((f["n"] for f in frames if f["sticker"] != "none"), None)
    if ask_at and ask_at > 4:
        warns.append(f"درخواست تو فریم {fa_digits(ask_at)}ه؛ ببرش به فریم ۴، با هر لمس تعداد بیننده کم می‌شه.")
    return {"frames": frames, "after": clean(user, out["after"]), "warnings": warns}


# ---------- 6. profile ----------

PROFILE_SCHEMA = obj({
    "scores": arr(obj({"id": S, "score": I, "why": S}), "all 12 rubric items, by id"),
    "name_field_options": arr(S, "3 options, each ≤ 30 characters"),
    "bio_options": arr(S, "2 options, each ≤ 150 characters, line breaks allowed"),
    "pinned_plan": arr(S, "the 3 pins: proof, offer, introduction"),
    "highlights": arr(S, "4 to 6 highlight names"),
    "link_advice": S, "grid_advice": S,
    "after_scores": arr(obj({"id": S, "score": I}), "all 12, if the rewrites are applied"),
    "rest_needs": S,
})
PROFILE_SYS = """You are «پروفایل‌سنج» (ig-profile). The profile is not a storefront, it's a decision screen arrived at from one reel, with three seconds to answer: is there more of that here, and is it for me. Score every rubric item honestly (most profiles land in the 30s-40s first time; a generous score is useless; never above the item's points). Then rewrite in descending order of points lost: the name field (30 characters, indexed by Instagram search: «اسم | کاری که می‌کنی با کلمه‌هایی که مردم سرچ می‌کنن», three options), bio line one (who it's for and what changes for them; not a job title or adjectives or pipes), the pinned three (three different jobs: best proof, clearest offer explanation, best introduction), highlights named for the buyer's questions, one link that matches the bio's promise, grid covers legible at thumbnail. after_scores: the honest re-score if the rewrites are applied; rest_needs: what a rewrite can't fix (a grid, a story habit, a pinned post that doesn't exist yet). If a field wasn't given, score it from what's there and say what you couldn't see.
Rubric:
"""


def run_profile(user, inp):
    fields = {k: str(inp.get(k) or "").strip() for k in ("name_field", "handle", "bio", "link", "highlights", "pinned", "grid", "photo", "category", "activity")}
    if not fields["bio"] and not fields["name_field"]:
        raise InputError("دست‌کم فیلد نام و بایو رو بنویس")
    rubric = data("rubric_fa.json")["items"]
    system = PROFILE_SYS + json.dumps(rubric, ensure_ascii=False) + "\n\n" + context(user, numbers=True)
    out = ask(user, system, "پروفایل:\n" + json.dumps(fields, ensure_ascii=False), PROFILE_SCHEMA, 6000)
    pts = {r["id"]: r for r in rubric}

    def table(scores):
        got = {s["id"]: s for s in scores}
        rows = [{"id": r["id"], "name": r["name"], "points": r["points"], "score": max(0, min(r["points"], int((got.get(r["id"]) or {}).get("score") or 0))),
                 "why": clean(user, (got.get(r["id"]) or {}).get("why", ""))} for r in rubric]
        return rows, sum(x["score"] for x in rows)
    before, total = table(out["scores"])
    after, total_after = table(out["after_scores"])
    names = [{"text": clean(user, n), "chars": len(clean(user, n)), "ok": len(clean(user, n)) <= 30} for n in out["name_field_options"]]
    bios = [{"text": clean(user, b), "chars": len(clean(user, b)), "ok": len(clean(user, b)) <= 150} for b in out["bio_options"]]
    order = sorted(before, key=lambda x: -(x["points"] - x["score"]))
    return {"scores": before, "total": total, "after": after, "total_after": max(total, total_after), "fix_order": [x["name"] for x in order[:6]],
            "name_options": names, "bio_options": bios, "pinned_plan": [clean(user, p) for p in out["pinned_plan"]],
            "highlights": [clean(user, h) for h in out["highlights"]], "link_advice": clean(user, out["link_advice"]),
            "grid_advice": clean(user, out["grid_advice"]), "rest_needs": clean(user, out["rest_needs"]), "rubric_points": {k: v["points"] for k, v in pts.items()}}


# ---------- 7. plan ----------

DAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
PLAN_SCHEMA = obj({
    "days": arr(obj({"day": {"type": "string", "enum": DAYS}, "kind": {"type": "string", "enum": ["reel", "carousel", "stories", "engage", "off"]},
                     "time": S, "type": {"type": "string", "enum": ["proof", "teach", "opinion", "story", "offer", "none"]},
                     "angle": S, "formula_id": I, "hook": S}), "7 days, Saturday first"),
    "stories_note": S, "timing_note": S,
    "engage": obj({"reach": arr(S), "peers": arr(S), "buyers": arr(S)}),
})
PLAN_SYS = """You are «برنامه‌ریز هفته» (ig-plan), the control room. 4-5 posts a week, at least 3 Reels (the only format that reliably reaches non-followers); carousels go deep with followers; stories are daily and planned separately. Never two of the same type back to back. Types per week: proof (1, something that happened with a number, Reel), teach (1-2, one thing the viewer can do today), opinion (1, a position that could lose followers, Reel), story (1 per fortnight, a scene with a cost, Reel), offer (1 per fortnight, what you sell said plainly, carousel or stories). For each post: an ANGLE from what actually happened this week (not a topic: «هوش مصنوعی» is not a plan, «پروپوزالی که به‌خاطر یه جملهٔ ماشینی از دست دادیم» is), the format, the formula id, and the hook line. Times: use the page's own best hours from the data when present (Tehran time, HH:MM); say plainly that the hour matters far less than the first two seconds. Days without a post: kind=engage or stories, type=none, formula_id=0, hook="". The engagement round (20 minutes a day, before posting): 5 reach accounts, 3 peers, 2 buyers, from the user's list when given (never invent real handles; if none given, describe the kind of account to find). Week starts Saturday (Iran).
The 26 formulas:
"""


def run_plan(user, inp):
    task = "\n".join(f"{lbl}: {inp.get(k) or '-'}" for k, lbl in (("sells", "چی می‌فروشم و به کی"), ("themes", "۳-۴ موضوعی که می‌خوام بهش شناخته بشم"),
                                                                   ("happened", "این هفته واقعاً چی شد"), ("accounts", "حساب‌هایی که می‌خوام دیده بشم")))
    if not str(inp.get("happened") or "").strip():
        raise InputError("بنویس این هفته واقعاً چی شد؛ پست‌ها از همین درمیان")
    out = ask(user, PLAN_SYS + formulas_brief() + "\n\n" + context(user, numbers=True, swipe=True, plan=True, audit=True, occasions=True), task, PLAN_SCHEMA, 8000)
    days, warns, last = [], [], None
    for d in out["days"]:
        f = hooks.formula(d["formula_id"]) if d["kind"] in ("reel", "carousel") else None
        day = {**d, "angle": clean(user, d["angle"]), "hook": clean(user, d["hook"]), "formula": (f or {}).get("name", "")}
        if d["kind"] in ("reel", "carousel") and d["hook"]:
            day["score"] = hooks.score(d["hook"], wpm(user))
        if d["kind"] in ("reel", "carousel") and d["type"] == last:
            warns.append(f"{d['day']} همون نوع روز قبله ({d['type']}).")
        last = d["type"] if d["kind"] in ("reel", "carousel") else last
        days.append(day)
    reels = sum(d["kind"] == "reel" for d in days)
    if reels < 3:
        warns.append(f"فقط {fa_digits(reels)} ریل؛ دست‌کم سه تا.")
    result = {"days": days, "stories_note": clean(user, out["stories_note"]), "timing_note": clean(user, out["timing_note"]),
              "engage": {k: [clean(user, x) for x in v] for k, v in out["engage"].items()}, "warnings": warns}
    save(user, "plan.json", {"at": int(time.time()), **result})
    return result


# ---------- 8. humanizer ----------

REWRITE_SCHEMA = obj({"text": S, "changed": arr(S, "one line per structural tell you rewrote")})


def run_human(user, inp):
    text = need(inp, "text", "متن")
    res = human.run(text, casual(user))
    if inp.get("rewrite") and res["report"]["flags"]:
        flags = "\n".join(f"- {f['name']}: {f['fix']} (مثلاً «{f['example']}»)" for f in res["report"]["flags"])
        out = ask(user, "You are «آدمی‌کن» (ig-human). Rewrite ONLY the lines that carry these structural tells, keeping the meaning, the facts and the user's voice; leave every other line exactly as it is. Don't add facts. Return the whole text.",
                  "الگوهای علامت‌خورده:\n" + flags + "\n\nمتن:\n" + res["clean"], REWRITE_SCHEMA)
        again = human.run(out["text"], casual(user))
        return {**again, "first": res["after"], "before": res["before"], "rewrote": out["changed"]}
    return res


# ---------- 9. comment ----------

COMMENT_TYPES = {1: "اضافه کردن یه عدد", 2: "حالت جاافتاده", 3: "مخالفت محترمانه", 4: "ادامهٔ یه جمله", 5: "سؤال اصلی",
                 6: "تجربهٔ خودم", 7: "اصلاح", 8: "از یه زاویهٔ دیگه", 9: "یک‌خطی"}
COMMENT_SCHEMA = obj({"items": arr(obj({"post": I, "options": arr(obj({"type": I, "text": S}), "exactly 2, of different types"),
                                         "pick": I, "why": S}))})
COMMENT_SYS = """You are «کامنت‌نویس» (ig-comment): comments on OTHER people's posts that read as a person with an opinion, not a bot. A comment near the top of a reel with 40,000 views is seen by more people than most posts; a generic one is worse than none. Pick the type by what the post actually is (never default to 1): 1 add a datum (a number that supports the claim) · 2 add the missing case («این درسته تا وقتی که…») · 3 respectful disagree (name the agreement first, then the fork) · 4 extend one line (quote it, build on it) · 5 ask the real question (one, specific) · 6 the receipt (you've done it: what happened, two sentences) · 7 the correction (be right, brief, kind, sure) · 8 the reframe («یه جور دیگه هم می‌شه دید:») · 9 the one-liner (under 10 words, funny or true). Rules: 1-3 sentences; never open with «عالی بود»، «چه پست خوبی»، «دقیقاً»، «چقدر به این نیاز داشتم»، the creator's name with «!»; no emoji-only comment and no emoji first; never restate the reel; one idea; say the specific thing (if it fits under any post on the topic, it's noise); never pitch, never «پیج منم ببین». Use the user's real experience only from the profile; don't invent receipts or numbers ({{عدد خودت}} if needed). Two options of DIFFERENT types per post, "pick" = 0-based index you'd post, "why" one line. "post" = 1-based index of the post."""
BANNED_OPENERS = re.compile(r"^\s*(?:عالی(?:\s*بود)?|چه\s*پست|چقدر\s*(?:خوب|عالی)|دقیقا|دقیقاً|مرسی\s*(?:بابت|از)|ممنون\s*(?:بابت|از)|به\s*این\s*نیاز|[\U0001F300-\U0001FAFF])")


def run_comment(user, inp):
    posts = [p.strip() for p in re.split(r"\n-{3,}\n", need(inp, "posts", "متن پست یا ریل")) if p.strip()][:10]
    task = "\n\n".join(f"پست {i}:\n{p}" for i, p in enumerate(posts, 1))
    out = ask(user, COMMENT_SYS + "\n\n" + context(user), task, COMMENT_SCHEMA)
    items = []
    for it in out["items"]:
        opts = []
        for o in it["options"]:
            text = clean(user, o["text"])
            warn = []
            if BANNED_OPENERS.match(text):
                warn.append("با جملهٔ کلیشه‌ای یا ایموجی شروع می‌شه")
            if len(re.findall(r"[.!؟?]+", text)) > 3:
                warn.append("بیشتر از سه جمله‌ست")
            opts.append({"type": o["type"], "type_name": COMMENT_TYPES.get(o["type"], ""), "text": text, "warnings": warn})
        items.append({"post": it["post"], "post_text": posts[it["post"] - 1][:300] if 0 < it["post"] <= len(posts) else "", "options": opts,
                      "pick": it["pick"], "why": clean(user, it["why"])})
    return {"items": items}


# ---------- 10. reply ----------

BUCKETS = {"keyword": "کلمهٔ کلیدی", "lead": "مشتری احتمالی", "substance": "حرف حساب", "question": "سؤال", "support": "حمایت", "noise": "بی‌ارزش"}
REPLY_SCHEMA = obj({"items": arr(obj({"n": I, "bucket": {"type": "string", "enum": list(BUCKETS)}, "reply": S, "reel_worthy": B}))})
REPLY_SYS = """You are «جواب کامنت» (ig-reply): replies under the user's OWN posts. Sort first, then write: keyword (the word they asked for: the promised thing, one warm line each, not copy-paste) · lead (someone describing the problem the user solves: a real answer in public, then one sentence offering help, not a pitch) · substance (adds data, disagrees, extends: the longest reply) · question (a question many people have: answer it, and if it has real demand set reel_worthy=true: it should become a Reel replying to the comment) · support («🔥»، «عالی»، a tag: 3-8 words at most, or reply "" and just like it) · noise (pitch, spam, bad faith, bait: reply "", replying gives them reach). Answer the actual question in the reply, don't send them to DMs for it. Use their name once at the start without «!». Match their length. To a critic: concede the true part first in their words, then hold the line, never defensive, never twice. To a hater: "". "n" = the 1-based comment number given."""


def run_reply(user, inp):
    raw = need(inp, "comments", "کامنت‌ها")
    comments = [c.strip() for c in raw.split("\n") if c.strip()][:120]
    out = ask(user, REPLY_SYS + "\n\n" + context(user), "کامنت‌ها (هر خط یکی، اگه آیدی داره اولش):\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(comments, 1)),
              REPLY_SCHEMA, 8000)
    items = []
    for it in out["items"]:
        if 0 < it["n"] <= len(comments):
            items.append({**it, "comment": comments[it["n"] - 1], "reply": clean(user, it["reply"]), "bucket_fa": BUCKETS[it["bucket"]]})
    order = list(BUCKETS)
    items.sort(key=lambda x: order.index(x["bucket"]))
    counts = {b: sum(x["bucket"] == b for x in items) for b in BUCKETS}
    return {"items": items, "counts": counts, "total": len(comments)}


# ---------- 11. dm ----------

DM_SCHEMA = obj({"no_trigger": B, "advice": S, "message": S, "followup_4": S, "followup_10": S})
DM_SYS = """You are «دایرکت‌نویس» (ig-dm). DMs are where money changes hands and where goodwill gets burned; the difference is who moved first. Three kinds worth writing: keyword (they commented the word / answered the story / asked: send THE THING FIRST in message one with no gate, then one line on how to use it, then one question they can answer in four words), warm (someone whose posts the user has really been commenting on: 2-4 sentences, reference the specific thing in their words, give before asking, one small ask, no link or calendar in message one, no voice note to a stranger), collab (four lines in order: what you've watched them do, the specific idea, what they get, what you need from them). Cold DMs to strangers: say plainly in "advice" that it's the lowest-yield use of the hour and suggest commenting on them for two weeks first, then write it anyway if asked. If there's no real trigger (a reason to message today), set no_trigger=true and explain. Follow-ups: two only. +4 days adds something new (never «فقط خواستم یادآوری کنم»; if nothing new, write "" and say why in advice). +10 days closes the loop and says you'll stop. Never automate, never bulk-DM, never fake a mutual or having watched something, never «سلام! یه سؤال سریع» without a question, never the pitch in the same message as the compliment."""


def run_dm(user, inp):
    kind = str(inp.get("kind") or "warm")
    who = need(inp, "who", "به کی")
    task = "\n".join(f"{lbl}: {inp.get(k) or '-'}" for k, lbl in (("kind", "نوع"), ("who", "کی، و چی کار می‌کنه"), ("trigger", "دلیل پیام امروز"),
                                                                   ("want", "چی می‌خوام"), ("thing", "چیزی که قول داده شده / لینک")))
    out = ask(user, DM_SYS + "\n\n" + context(user), task, DM_SCHEMA)
    msgs = {k: clean(user, out[k]) for k in ("message", "followup_4", "followup_10")}
    return {"kind": kind, "who": who, "no_trigger": out["no_trigger"], "advice": clean(user, out["advice"]),
            **msgs, "chars": {k: len(v) for k, v in msgs.items()}}


# ---------- 12. repurpose ----------

REPURPOSE_SCHEMA = obj({
    "found": obj({k: arr(S) for k in ("claims", "numbers", "stories", "mechanisms", "mistakes", "lines")}),
    "thin": B, "thin_note": S,
    "week": arr(obj({"day": {"type": "string", "enum": DAYS}, "format": {"type": "string", "enum": ["reel", "carousel", "story"]},
                     "formula_id": I, "angle": S, "extract": S, "clip_note": S}), "4 to 6 posts"),
})
REPURPOSE_SYS = """You are «بازنشر» (ig-repurpose): one long asset (video transcript, podcast, live, newsletter, article, call notes) into a week of posts. Read it all, then EXTRACT, don't summarise: claims (sentences that start an argument), numbers (every figure, cost, duration, percentage), stories (a person, a scene, a cost), mechanisms («روش کارش اینه که…»), mistakes (admissions), lines (quotable as-is). Quote extracts from the source, in its words. If there are fewer than four usable items, set thin=true and say so. Then format per extract: claim/mistake/story → reel (needs a voice and a face); mechanism/numbered list → carousel (re-read); a quotable line → story frame. Each post stands completely alone (never «همون‌طور که تو ویدیوی آخرم گفتم»). Vary the hook formulas (five posts with one shape reads as a content mill). Order: strongest claim first, the story midweek, the mechanism last. clip_note: if the source is the user's own video, which moment to cut (else ""). Week starts Saturday.
The 26 formulas:
"""


def run_repurpose(user, inp):
    src = need(inp, "source", "متن منبع")
    out = ask(user, REPURPOSE_SYS + formulas_brief() + "\n\n" + context(user), f"عنوان: {inp.get('title') or '-'}\n\nمنبع:\n{src[:60000]}", REPURPOSE_SCHEMA, 8000)
    # the extracts stay word for word: they are quotes from the source
    week = [{**w, "angle": clean(user, w["angle"]), "formula": (hooks.formula(w["formula_id"]) or {}).get("name", "")} for w in out["week"]]
    ids = [w["formula_id"] for w in week if w["format"] == "reel"]
    warns = ["چند پست یه فرمول هوک دارن؛ متنوعش کن."] if len(ids) != len(set(ids)) else []
    return {"found": out["found"], "counts": {k: len(v) for k, v in out["found"].items()}, "thin": out["thin"],
            "thin_note": clean(user, out["thin_note"]), "week": week, "warnings": warns, "words": len(words(src))}


# ---------- 13. audit ----------

AUDIT_SCHEMA = obj({"findings": arr(obj({"claim": S, "evidence": S, "confidence": S}), "2 to 5"),
                    "profile_problem": B, "stop": S, "do_more": S, "note": S})
AUDIT_SYS = """You are «کالبدشکافی پست‌ها» (ig-audit). The page's own posts are the only honest evidence; every rule is a prior. You get the metrics already computed by a script: outlier multiple (views ÷ the page's median), hold at 3s (the hook's grade), average watch (the middle), sends per 1k reach (the strongest signal: a person putting their name on it), follows per 1k reach (did the profile convert), plus groupings by hook formula, length and topic. Rank by multiple and sends, never raw views. Look at the top and bottom side by side: if hold at 3s differs, it's the hook and nothing else; then formula, format, length, topic; day and time LAST and only if nothing else shows. State each finding as a claim with the numbers attached and a confidence in plain words (with 30 posts you can see a pattern; with 6 you can't, and saying so is better than inventing one). Be willing to conclude something the user won't like. The distinction that saves months: views but no follows = a profile problem (set profile_problem=true and say to fix the profile), no views = a hook problem. stop: what to stop making. do_more: what to make more of."""


def run_audit(user, inp):
    d = analysis.load(config.user_dir(user["id"]) / "data" / "data.json") or {}
    a = viral.audit(d.get("reels", []), d.get("topics", []))
    if a["n"] < 3:
        raise InputError("برای کالبدشکافی دست‌کم ۳ ریل با آمار لازمه؛ اول داده بگیر")
    brief = {k: a[k] for k in ("n", "median_views", "compare", "by_formula", "by_length", "by_topic", "confidence")}
    brief["top"], brief["bottom"] = a["top"], a["bottom"]
    out = ask(user, AUDIT_SYS + "\n\n" + context(user), json.dumps(brief, ensure_ascii=False), AUDIT_SCHEMA)
    result = {**a, "findings": [{k: clean(user, v) for k, v in f.items()} for f in out["findings"]], "profile_problem": out["profile_problem"],
              "stop": clean(user, out["stop"]), "do_more": clean(user, out["do_more"]), "note": clean(user, out["note"])}
    save(user, "audit.json", {"at": int(time.time()), "findings": result["findings"], "stop": result["stop"], "do_more": result["do_more"]})
    return result


# ---------- the voice profile, inferred from the page's own captions ----------

VOICE_SCHEMA = obj({k: S for k in ("who", "audience", "on_camera", "words_used", "words_never", "emoji", "register")})


def infer_voice(user):
    d = analysis.load(config.user_dir(user["id"]) / "data" / "data.json") or {}
    caps = [r.get("caption") for r in sorted(d.get("reels", []), key=lambda r: -(r.get("views") or 0)) if r.get("caption")][:8]
    if len(caps) < 3:
        raise InputError("برای حدس زدن لحن دست‌کم ۳ کپشن لازمه")
    out = ask(user, "From these captions of the user's own Reels, infer their voice profile. register must be exactly 'casual' or 'formal'. "
                    "Describe in Persian, concretely (real words they use, not adjectives about them). Don't invent facts about the person.",
              "\n\n---\n\n".join(caps), VOICE_SCHEMA)
    out["register"] = "formal" if "formal" in out["register"] else "casual"
    out["samples"] = "\n---\n".join(c[:400] for c in caps[:3])
    return out


AGENTS = {
    "reel": ("ریل‌ساز", run_reel), "viral": ("تحقیق وایرال", run_viral), "caption": ("کپشن‌نویس", run_caption),
    "carousel": ("کاروسل‌ساز", run_carousel), "story": ("استوری‌نویس", run_story), "profile": ("پروفایل‌سنج", run_profile),
    "plan": ("برنامه‌ریز هفته", run_plan), "human": ("آدمی‌کن", run_human), "comment": ("کامنت‌نویس", run_comment),
    "reply": ("جواب کامنت", run_reply), "dm": ("دایرکت‌نویس", run_dm), "repurpose": ("بازنشر", run_repurpose),
    "audit": ("کالبدشکافی پست‌ها", run_audit),
}


def run(user, agent, inp):
    out = AGENTS[agent][1](user, inp)
    remember(user, agent, {k: (str(v)[:400] if isinstance(v, str) else v) for k, v in inp.items()}, out)
    return out
