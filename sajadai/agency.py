"""Agency mode: a page's report carries the agency's name and colour, has a public link the client can open
without an account (/r/<token>, revocable), and goes to the client by itself on the 1st of each Jalali
month: to their Telegram through the panel's bot, and by email when the admin set up SMTP."""
import os, re, secrets, smtplib, ssl, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from . import calendar_fa, pages, pipeline, store

TEHRAN = timezone(timedelta(hours=3, minutes=30))
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$", re.I)
def fresh(user):
    """The prefs as stored now (a user row read at the start of a request goes stale once it changes)."""
    return store.prefs(store.get_user(user["id"]) or user)


KEYS = ("agency_name", "agency_color", "agency_client", "agency_days", "agency_chat", "agency_email", "agency_auto")


def settings(user):
    p = fresh(user)
    return {"name": p.get("agency_name", ""), "color": p.get("agency_color", "#0062d6"), "client": p.get("agency_client", ""),
            "days": int(p.get("agency_days") or 30), "chat": p.get("agency_chat", ""), "email": p.get("agency_email", ""),
            "auto": bool(p.get("agency_auto")), "token": p.get("agency_token", ""), "sent": p.get("agency_sent", "")}


def clean(b):
    out = {"agency_name": str(b.get("name") or "").strip()[:60], "agency_client": str(b.get("client") or "").strip()[:60],
           "agency_color": str(b.get("color") or "#0062d6").strip(), "agency_days": int(b.get("days") or 30),
           "agency_chat": str(b.get("chat") or "").strip(), "agency_email": str(b.get("email") or "").strip(), "agency_auto": bool(b.get("auto"))}
    if not COLOR.match(out["agency_color"]):
        raise ValueError("رنگ باید به شکل #1a2b3c باشه")
    if out["agency_days"] not in (7, 30, 90):
        raise ValueError("دورهٔ گزارش: ۷، ۳۰ یا ۹۰ روز")
    if out["agency_chat"] and not re.fullmatch(r"-?\d{3,20}", out["agency_chat"]):
        raise ValueError("chat id تلگرام مشتری باید عدد باشه")
    if out["agency_email"] and not EMAIL.match(out["agency_email"]):
        raise ValueError("ایمیل مشتری درست نیست")
    if out["agency_auto"] and not (out["agency_chat"] or out["agency_email"]):
        raise ValueError("برای فرستادن خودکار، تلگرام یا ایمیل مشتری رو بذار")
    return out


def owner_of(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", token or ""):
        return None
    for u in store.users():
        if store.prefs(u).get("agency_token") == token:
            return u
    return None


def new_token(user):
    p = fresh(user)
    p["agency_token"] = secrets.token_urlsafe(24)
    store.set_prefs(user["id"], p)
    return p["agency_token"]


def brand(user):
    s = settings(user)
    return {"agency": s["name"], "color": s["color"], "client": s["client"]} if s["name"] else None


def link(user):
    s = settings(user)
    base = pipeline.public_url()
    return f"{base}/r/{s['token']}" if s["token"] and base else None


def summary(user, d):
    s = settings(user)
    t = pages.today()
    start = t - timedelta(days=s["days"] - 1)
    cur = pages.period(d, start.isoformat(), t.isoformat())
    prev = pages.period(d, (start - timedelta(days=s["days"])).isoformat(), (start - timedelta(days=1)).isoformat())
    name = fresh(user).get("page_name") or user["username"]

    def delta(a, b):
        if a is None or not b:
            return ""
        pct = round((a - b) / b * 100)
        return f" ({'+' if pct >= 0 else ''}{pct}٪)".translate(pages.FA)
    lines = [f"گزارش {pages.fa(s['days'])} روزهٔ {name}" + (f" — {s['name']}" if s["name"] else ""),
             f"{pages.jdate(start.isoformat())} تا {pages.jdate(t.isoformat())}", "",
             f"بازدید ریل‌ها: {pages.fa(cur['views'])}{delta(cur['views'], prev['views'])}",
             f"ریل منتشرشده: {pages.fa(cur['n'])}",
             f"فالوئر: {pages.fa(cur['followers'])}" + (f" (خالص {pages.fa(cur['followers_net'])})" if cur["followers_net"] is not None else "")]
    if cur.get("view_rate") is not None:
        lines.append(f"ماندن بعد از ۳ ثانیه: {pages.fa(cur['view_rate'], 1, '٪')}")
    return "\n".join(lines)


def send(user, d):
    """Send the report to the client now. Returns [(channel, ok, message)]."""
    s = settings(user)
    if not s["token"]:
        new_token(user)
    url = link(user)
    text = summary(user, d) + (f"\n\nگزارش کامل: {url}" if url else "")
    out = []
    bot = store.setting("telegram_bot")
    if s["chat"]:
        if not bot:
            out.append(("telegram", False, "ربات تلگرام پنل تنظیم نشده (ادمین)."))
        else:
            try:
                body = urllib.parse.urlencode({"chat_id": s["chat"], "text": text[:4000], "disable_web_page_preview": "false"}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{bot}/sendMessage", data=body, timeout=20).close()
                out.append(("telegram", True, "به تلگرام مشتری رفت."))
            except Exception as e:  # noqa: BLE001
                out.append(("telegram", False, "تلگرام نشد: مشتری باید اول به ربات پنل پیام بده. " + str(e)[:80]))
    if s["email"]:
        ok, msg = email(s["email"], f"گزارش {pages.fa(s['days'])} روزهٔ " + (fresh(user).get("page_name") or user["username"]),
                        text, reply_to=None, sender_name=s["name"] or None)
        out.append(("email", ok, msg))
    if not out:
        out.append(("none", False, "تلگرام یا ایمیل مشتری تنظیم نشده."))
    return out


def smtp_config():
    """Admin → ایمیل پنل, or the server's env (SAJADAI_SMTP_HOST/PORT/USER/FROM/PASSWORD) for anything left empty."""
    cfg = dict(store.setting("smtp", {}) or {})
    for k in ("host", "port", "user", "from"):
        if not cfg.get(k) and os.environ.get(f"SAJADAI_SMTP_{k.upper()}"):
            cfg[k] = os.environ[f"SAJADAI_SMTP_{k.upper()}"]
    return cfg


def email(to, subject, text, reply_to=None, sender_name=None):
    cfg = smtp_config()
    if not cfg.get("host") or not cfg.get("from"):
        return False, "ایمیل پنل (SMTP) تنظیم نشده (ادمین: پنل مدیریت)."
    m = EmailMessage()
    m["Subject"], m["To"] = subject, to
    m["From"] = f"{sender_name} <{cfg['from']}>" if sender_name else cfg["from"]
    if reply_to:
        m["Reply-To"] = reply_to
    m.set_content(text)
    try:
        port = int(cfg.get("port") or 587)
        if port == 465:
            s = smtplib.SMTP_SSL(cfg["host"], port, context=ssl.create_default_context(), timeout=30)
        else:
            s = smtplib.SMTP(cfg["host"], port, timeout=30)
            s.starttls(context=ssl.create_default_context())
        with s:
            if cfg.get("user"):
                # the password can stay in the server's .env (SAJADAI_SMTP_PASSWORD, e.g. a Resend API key)
                s.login(cfg["user"], cfg.get("password") or os.environ.get("SAJADAI_SMTP_PASSWORD", ""))
            s.send_message(m)
        return True, "ایمیل شد."
    except Exception as e:  # noqa: BLE001
        return False, "ایمیل نشد: " + str(e)[:120]


def month_key(now=None):
    jy, jm, _ = calendar_fa.to_jalali((now or datetime.now(TEHRAN)).date())
    return f"{jy}-{jm:02}"


def due(user, now=None):
    """The 1st of a Jalali month, from 09:00 Tehran, once per month."""
    now = now or datetime.now(TEHRAN)
    s = settings(user)
    return s["auto"] and calendar_fa.to_jalali(now.date())[2] == 1 and now.hour >= 9 and s["sent"] != month_key(now)


def mark_sent(user, now=None):
    p = fresh(user)
    p["agency_sent"] = month_key(now)
    p["agency_sent_at"] = int(time.time())
    store.set_prefs(user["id"], p)
