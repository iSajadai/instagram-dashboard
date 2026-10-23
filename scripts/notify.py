#!/usr/bin/env python3
"""Telegram alerts and the Saturday weekly report, from data/data.json.

Run for each user by the panel's scheduler (sajadai/pipeline.py), or by cron. Each alert goes out once (state is kept
outside the repo, because sync resets the checkout):
  - a reel 3-72 hours old is running 1.5x ahead of / 2x behind other reels at the same age
  - the follower count dropped
  - data hasn't been refreshed for more than 12 hours (and a note when it's back)
  - Saturday from 09:00 Tehran: the weekly report, once per week

Config: /etc/sajadai-dashboard/telegram.env (or $SAJADAI_NOTIFY_ENV), KEY=value lines:
  TG_CHAT_ID=123456789
  TG_BOT_TOKEN=...            or  TG_BOT_TOKEN_FILE=/path/to/file/containing/the/token
  DASH_URL=https://dash.example.com       (optional, linked at the end of messages)
No config file means nothing is sent and the script exits quietly.

Usage: python3 scripts/notify.py [--dry-run] [--weekly-now] [--state PATH]
  --dry-run     print the messages instead of sending; don't touch the state file
  --weekly-now  send the weekly report now, whatever the day
"""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from statistics import median

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STANDALONE = bool(os.environ.get("SAJADAI_STATE"))  # set by the panel: each user's data folder
DATA = os.path.join(os.environ.get("SAJADAI_STATE") or ROOT, "data", "data.json")
ENV = os.environ.get("SAJADAI_NOTIFY_ENV", "/etc/sajadai-dashboard/telegram.env")
STATE = "/var/lib/sajadai-dashboard/notify-state.json"
TEH = timezone(timedelta(hours=3, minutes=30))
STALE_H = 12
RISING, WEAK = 1.5, 0.5
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x, digits=0):
    if x is None:
        return "—"
    s = f"{x:,.{digits}f}" if digits else f"{round(x):,}"
    return s.replace(",", "٬").translate(FA)


def pct(x):
    return "—" if x is None else fa(x, 1) + "٪"


def parse_pub(s):
    # reel times from Metricool are Tehran wall-clock without an offset
    try:
        return datetime.fromisoformat(str(s)[:19]).replace(tzinfo=TEH)
    except ValueError:
        return None


def parse_at(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def hook(r, n=60):
    t = (r.get("caption") or "").strip().split("\n")[0]
    return t[:n] + ("…" if len(t) > n else "")


def curve(reel, snaps):
    """[(hours since publishing, views)] from the reel's snapshots, starting at (0, 0)."""
    pub = parse_pub(reel.get("published"))
    if not pub:
        return []
    pts = [(0.0, 0)]
    for s in snaps:
        at = parse_at(s.get("at"))
        if s.get("url") == reel["url"] and s.get("views") is not None and at:
            h = (at - pub).total_seconds() / 3600
            if h > 0:
                pts.append((h, s["views"]))
    return sorted(pts)


def views_at(pts, h):
    """Views at age h, interpolated between two points no more than max(12h, h) apart; else None."""
    for (h0, v0), (h1, v1) in zip(pts, pts[1:]):
        if h0 <= h <= h1 and h1 - h0 <= max(12, h):
            return v0 + (v1 - v0) * (h - h0) / (h1 - h0) if h1 > h0 else v1
    return None


def pace(reel, reels, snaps, now):
    """(ratio, basis) of a fresh reel's views against other reels at the same age, or None.
    basis 'age' compares with other reels' curves at the same age (needs 3 of them);
    from 24h on, 'median' falls back to the median of other reels' current views."""
    pub = parse_pub(reel.get("published"))
    if not pub or reel.get("views") is None:
        return None
    age = (now - pub).total_seconds() / 3600
    if not 3 <= age <= 72:
        return None
    others = [r for r in reels if r["url"] != reel["url"] and r.get("views") is not None]
    ref = [v for v in (views_at(curve(r, snaps), age) for r in others) if v]
    if len(ref) >= 3:
        return reel["views"] / median(ref), "age", age
    if age >= 24 and len(others) >= 3:
        m = median(r["views"] for r in others)
        return (reel["views"] / m, "median", age) if m else None
    return None


def follower_drop(account):
    rows = [d for d in account if d.get("followers") is not None]
    if len(rows) < 2:
        return None
    last = rows[-1]
    peak = max(rows[-4:-1], key=lambda d: d["followers"])
    drop = peak["followers"] - last["followers"]
    if drop >= max(2, peak["followers"] * 0.02):
        return last, peak, drop
    return None


def window_stats(reels, account, start, end):
    """Totals for reels published in [start, end) Tehran days, the same way the page counts them."""
    rs = [r for r in reels if start <= str(r.get("published") or "")[:10] < end]
    views = sum(r.get("views") or 0 for r in rs)
    reach = sum(r.get("reach") or 0 for r in rs)
    vr = [r["view_rate"] for r in rs if r.get("view_rate") is not None]
    fols = [d for d in account if d.get("followers") is not None and d["day"] < end]
    before = [d for d in fols if d["day"] < start]
    inside = [d for d in fols if d["day"] >= start]
    last = fols[-1]["followers"] if fols else None
    base = (before[-1] if before else inside[0] if inside else None)
    return {
        "reels": len(rs), "views": views, "list": rs,
        "view_rate": sum(vr) / len(vr) if vr else None,
        "save_rate": sum(r.get("saves") or 0 for r in rs) / views * 100 if views else None,
        "shares_1k": sum(r.get("shares") or 0 for r in rs) / reach * 1000 if reach else None,
        "followers": last, "net": last - base["followers"] if last is not None and base else None,
    }


def arrow(cur, prev, rel=True):
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if rel and not prev:
        return ""  # nothing the week before: a percentage would mean nothing
    if not d:
        return " (بدون تغییر)"
    if rel and prev:
        t = fa(abs(d) / prev * 100) + "٪"
    else:
        t = fa(abs(d), 1 if not rel and abs(d) < 10 and d != int(d) else 0)
    return f" ({'↑' if d > 0 else '↓'} {t})"


def goal_lines(goals, reels, account, today):
    wk = (today - timedelta(days=6)).isoformat()
    fols = [d for d in account if d.get("followers") is not None]
    out = []
    for g in goals:
        cur = None
        if g.get("metric") == "followers" and fols:
            cur = fols[-1]["followers"]
        elif g.get("metric") == "reels_7d":
            cur = sum(1 for r in reels if str(r.get("published") or "")[:10] >= wk)
        elif g.get("metric") == "views_7d":
            cur = sum(d.get("reels_views") or 0 for d in account if d["day"] >= wk)
        if cur is None or not g.get("target"):
            continue
        p = min(100, round(cur / g["target"] * 100))
        tail = " ✓" if p >= 100 else ""
        if g.get("deadline") and p < 100:
            left = (datetime.fromisoformat(g["deadline"]).date() - today).days
            tail = f" · {fa(left)} روز مونده" if left > 0 else " · مهلت تموم شده"
        out.append(f"• {g.get('label')}: {fa(cur)} از {fa(g['target'])} ({fa(p)}٪){tail}")
    return out


def weekly(d, today):
    """Saturday-to-Friday week that ended yesterday, against the week before."""
    end = today.isoformat()
    start = (today - timedelta(days=7)).isoformat()
    pstart = (today - timedelta(days=14)).isoformat()
    reels, account = d.get("reels", []), d.get("account", [])
    cur, prev = window_stats(reels, account, start, end), window_stats(reels, account, pstart, start)
    allv = sorted(r["views"] for r in reels if r.get("views") is not None)
    med = median(allv) if allv else None
    lines = [f"📊 گزارش هفتگی پیج ({fa_date(start)} تا {fa_date((today - timedelta(days=1)).isoformat())})", ""]
    lines.append(f"ریل‌ها: {fa(cur['reels'])}{arrow(cur['reels'], prev['reels'], rel=False)}")
    lines.append(f"بازدید ریل‌ها: {fa(cur['views'])}{arrow(cur['views'], prev['views'])}")
    lines.append(f"فالوئر: {fa(cur['followers'])}" + (f" (خالص هفته {'+' if (cur['net'] or 0) > 0 else ''}{fa(cur['net'])})" if cur["net"] is not None else ""))
    lines.append(f"ماندن بعد از ۳ ثانیه: {pct(cur['view_rate'])}{arrow(cur['view_rate'], prev['view_rate'], rel=False)}")
    lines.append(f"نرخ ذخیره: {pct(cur['save_rate'])} · اشتراک در هر ۱۰۰۰ نفر: {fa(cur['shares_1k'], 1)}")
    scored = [r for r in cur["list"] if r.get("views") is not None]
    if med and scored:
        best = max(scored, key=lambda r: r["views"])
        worst = min(scored, key=lambda r: r["views"])
        lines += ["", f"🏆 بهترین: «{hook(best)}» — {fa(best['views'])} بازدید ({fa(best['views'] / med, 1)} برابر میانه)"]
        if worst is not best:
            lines.append(f"🔻 ضعیف‌ترین: «{hook(worst)}» — {fa(worst['views'])} بازدید ({fa(worst['views'] / med, 1)} برابر میانه)")
    elif not scored:
        lines += ["", "این هفته ریلی منتشر نشد."]
    g = goal_lines(d.get("goals", []), reels, account, today)
    if g:
        lines += ["", "🎯 هدف‌ها:"] + g
    ins = [i for i in d.get("insights", []) if i.get("action")]
    if ins:
        lines += ["", "کار این هفته: " + ins[0]["action"]]
    return "\n".join(lines)


def jalali(gy, gm, gd):
    """Gregorian date to Jalali (y, m, d)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


def fa_date(iso):
    _, m, d = jalali(int(iso[:4]), int(iso[5:7]), int(iso[8:10]))
    return f"{d} {MONTHS[m - 1]}".translate(FA)


def alerts(d, state, now):
    out = []
    reels, snaps = d.get("reels", []), d.get("reel_snapshots", [])
    sent = state.setdefault("reels", {})
    for r in reels:
        p = pace(r, reels, snaps, now)
        if not p:
            continue
        ratio, basis, age = p
        kind = "rising" if ratio >= RISING else "weak" if ratio <= WEAK else None
        if not kind or sent.get(r["url"]) == kind:
            continue
        sent[r["url"]] = kind
        ref = "ریل‌های قبلی در همین سن" if basis == "age" else "میانهٔ بازدید ریل‌های قبلی"
        if kind == "rising":
            head = f"🚀 ریل «{hook(r)}» داره اوج می‌گیره"
            tip = "الان وقت خوبیه یه استوری ازش بذاری یا تو کامنت‌ها فعال باشی."
        else:
            head = f"🐢 ریل «{hook(r)}» عقب مونده"
            tip = "هوک یا کاورش رو با ریل‌های موفق مقایسه کن؛ یه استوری هم می‌تونه کمکش کنه."
        out.append(f"{head}\n{fa(r['views'])} بازدید بعد از {fa(age)} ساعت، {fa(ratio, 1)} برابر {ref}.\n{tip}\n{r['url']}")
    fd = follower_drop(d.get("account", []))
    if fd:
        last, peak, drop = fd
        key = f"{last['day']}:{last['followers']}"
        if state.get("followers_drop") != key:
            state["followers_drop"] = key
            out.append(f"📉 فالوئرها کم شدن: {fa(peak['followers'])} ← {fa(last['followers'])} ({fa(drop)} نفر، {fa_date(peak['day'])} تا {fa_date(last['day'])}).")
    gen = parse_at(d.get("generated_at"))
    if gen:
        age = (now - gen).total_seconds() / 3600
        if age > STALE_H and state.get("stale") != d["generated_at"]:
            state["stale"] = d["generated_at"]
            if STANDALONE:
                out.append(f"⚠️ دادهٔ داشبورد {fa(age)} ساعته تازه نشده (معمولاً هر ۶ ساعت). احتمالاً توکن اینستاگرام منقضی شده یا API خطا داده. لاگ:\n"
                           "/var/log/sajadai-refresh.log")
            else:
                out.append(f"⚠️ دادهٔ داشبورد {fa(age)} ساعته تازه نشده (معمولاً هر ۶ ساعت). احتمالاً همگام‌سازی خطا خورده یا اینستاگرام تو Metricool قطع شده:\n"
                           "https://app.metricool.com/")
        elif age <= STALE_H and state.get("stale") and state["stale"] != d["generated_at"]:
            state.pop("stale")
            out.append("✅ دادهٔ داشبورد دوباره تازه شد.")
    return out


def load_env():
    # the panel passes each user's chat (and the admin's bot) this way
    if os.environ.get("SAJADAI_TG_TOKEN") and os.environ.get("SAJADAI_TG_CHAT"):
        return {"TG_BOT_TOKEN": os.environ["SAJADAI_TG_TOKEN"], "TG_CHAT_ID": os.environ["SAJADAI_TG_CHAT"],
                "DASH_URL": os.environ.get("SAJADAI_DASH_URL", "")}
    env = {}
    try:
        with open(ENV, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*([A-Z_]+)\s*=\s*(.*?)\s*$", line)
                if m and not line.lstrip().startswith("#"):
                    env[m[1]] = m[2].strip("'\"")
    except FileNotFoundError:
        return None
    if not env.get("TG_BOT_TOKEN") and env.get("TG_BOT_TOKEN_FILE"):
        with open(env["TG_BOT_TOKEN_FILE"], encoding="utf-8") as f:
            m = re.search(r"[0-9]{8,}:[A-Za-z0-9_-]{30,}", f.read())
            env["TG_BOT_TOKEN"] = m[0] if m else ""
    return env if env.get("TG_BOT_TOKEN") and env.get("TG_CHAT_ID") else None


def send(env, text):
    if env.get("DASH_URL"):
        text += f"\n\n{env['DASH_URL']}"
    for i in range(0, len(text), 4000):
        body = urllib.parse.urlencode({"chat_id": env["TG_CHAT_ID"], "text": text[i:i + 4000],
                                       "disable_web_page_preview": "true"}).encode()
        url = f"https://api.telegram.org/bot{env['TG_BOT_TOKEN']}/sendMessage"
        with urllib.request.urlopen(url, data=body, timeout=20) as r:
            if r.status != 200:
                raise RuntimeError(f"telegram HTTP {r.status}")


def main(argv):
    dry = "--dry-run" in argv
    state_path = argv[argv.index("--state") + 1] if "--state" in argv else STATE
    env = load_env()
    if not env and not dry:
        return
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    first_run = not state
    now = datetime.now(timezone.utc)
    msgs = alerts(d, state, now)
    if first_run and not dry:
        msgs = []  # don't fire on history the first time; just remember what's already there
    tnow = now.astimezone(TEH)
    week = (tnow.date() - timedelta(days=(tnow.weekday() - 5) % 7)).isoformat()  # this week's Saturday
    if "--weekly-now" in argv or (tnow.weekday() == 5 and tnow.hour >= 9 and state.get("weekly") != week):
        msgs.append(weekly(d, tnow.date()))
        state["weekly"] = week
    for m in msgs:
        if dry:
            print(m, end="\n\n-----\n\n")
        else:
            send(env, m)
            print(f"{now.isoformat(timespec='seconds')} sent: {m.splitlines()[0]}")
    if not dry:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, state_path)


if __name__ == "__main__":
    main(sys.argv[1:])
