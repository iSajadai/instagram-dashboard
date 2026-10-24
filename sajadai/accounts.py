"""Public accounts: sign-up with email and password (or Google), email verification, password reset
without the admin, a waitlist the admin approves in batches, rate limits on sign-in and sign-up,
deleting an account with everything in it, and the admin's overview (users, sync errors, AI use, queue).

Sign-up mode (setting "signup_mode"): closed | open | waitlist. Email links need the panel's SMTP
(Admin → ایمیل پنل); without it, sign-up still works and addresses are marked unverified."""
import json, os, re, secrets, shutil, threading, time, urllib.parse, urllib.request
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import config, pipeline, store

router = APIRouter()
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")


def deps():
    from .web import body, login_response, need_admin, need_user, page, same_site
    return body, login_response, need_admin, need_user, page, same_site


body, login_response, need_admin, need_user, page, same_site = deps()


# ---------- rate limits ----------

class Limiter:
    """At most `n` tries per `window` seconds for each key (an IP, an email). In memory: one process."""
    def __init__(self, n, window):
        self.n, self.window, self.hits, self.lock = n, window, defaultdict(deque), threading.Lock()

    def check(self, *keys):
        """Refuse when any key is over its limit (without counting this try)."""
        now = time.time()
        with self.lock:
            for k in keys:
                q = self.hits[k]
                while q and now - q[0] > self.window:
                    q.popleft()
                if len(q) >= self.n:
                    raise HTTPException(429, f"تلاش زیاد بود؛ {max(1, int((self.window - (now - q[0])) // 60) + 1)} دقیقهٔ دیگه دوباره امتحان کن.")

    def add(self, *keys):
        with self.lock:
            for k in keys:
                self.hits[k].append(time.time())

    def hit(self, *keys):
        self.check(*keys)
        self.add(*keys)


LOGIN = Limiter(8, 600)       # 8 wrong tries per 10 minutes per IP and per name
SIGNUP = Limiter(5, 3600)     # 5 sign-ups per hour per IP
MAIL = Limiter(4, 3600)       # 4 emails (verify / reset) per hour per address


def ip(request):
    return (request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0] or (request.client.host if request.client else "")).strip()


def mode():
    m = store.setting("signup_mode")
    if m in ("closed", "open", "waitlist"):
        return m
    return "open" if store.setting("allow_signup", False) else "closed"


def smtp_ready():
    from .agency import smtp_config
    s = smtp_config()
    return bool(s.get("host") and s.get("from") and (s.get("password") or os.environ.get("SAJADAI_SMTP_PASSWORD") or not s.get("user")))


def mail(to, subject, text):
    from .agency import email
    return email(to, subject, text, sender_name="داشبورد اینستاگرام")


def link(path):
    return (pipeline.public_url() or "") + path


def send_verify(u):
    if not smtp_ready() or not u["email"]:
        return False
    tok = store.new_token(u["id"], "verify", 48)
    ok, _ = mail(u["email"], "تأیید ایمیل داشبورد اینستاگرام",
                 f"سلام!\n\nبرای تأیید ایمیلت این لینک رو باز کن (تا ۴۸ ساعت اعتبار داره):\n{link('/verify?token=' + tok)}\n\nاگه تو ثبت‌نام نکردی، این ایمیل رو نادیده بگیر.")
    return ok


def username_for(email):
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:24] or "user"
    if len(base) < 3:
        base += "user"
    name, n = base, 1
    while store.name_taken(name):
        n += 1
        name = f"{base}{n}"
    return name


def create_account(email, password=None, verified=False, google_sub=None):
    from .web import new_user
    uid = new_user(username_for(email), password or secrets.token_urlsafe(24))
    store.set_user(uid, email=email.strip().lower(), email_verified=int(verified), state="waitlist" if mode() == "waitlist" else "active",
                   **({"google_sub": google_sub} if google_sub else {}))
    return store.get_user(uid)


@router.post("/api/signup", include_in_schema=False, dependencies=[Depends(same_site)])
async def signup(request: Request):
    m = mode()
    if m == "closed":
        raise HTTPException(403, "ثبت‌نام فعلاً بسته‌ست.")
    SIGNUP.hit("ip:" + ip(request))
    b = await body(request)
    email, pw = str(b.get("email") or b.get("username") or "").strip().lower(), str(b.get("password") or "")
    if not EMAIL.match(email):
        raise HTTPException(400, "ایمیل درست نیست")
    if len(pw) < 8:
        raise HTTPException(400, "رمز باید دست‌کم ۸ حرف باشه")
    if store.find_email(email):
        raise HTTPException(400, "با این ایمیل قبلاً حساب ساخته شده؛ وارد شو یا رمز رو بازیابی کن.")
    if b.get("privacy") is not True:
        raise HTTPException(400, "برای ثبت‌نام، حریم خصوصی رو بخون و تیکش رو بزن.")
    u = create_account(email, pw)
    sent = send_verify(u)
    if u["state"] == "waitlist":
        return {"ok": True, "waitlist": True, "message": "تو صف انتظاری ✓ وقتی حسابت باز شد بهت ایمیل می‌زنیم." + (" ایمیلت رو هم تأیید کن." if sent else "")}
    if sent:
        return {"ok": True, "verify": True, "message": "یه لینک تأیید به ایمیلت فرستادیم؛ بازش کن تا وارد بشی."}
    return login_response(u["id"], {"ok": True, "next": "/welcome"})


def login_block(u):
    """Why this person can't sign in yet, or None."""
    if u["state"] == "waitlist":
        return "حسابت تو صف انتظاره؛ وقتی باز شد ایمیل می‌گیری."
    if u["email"] and not u["email_verified"] and smtp_ready():
        return "اول ایمیلت رو تأیید کن (لینک تو ایمیلت هست). ایمیل نرسیده؟ «فرستادن دوباره» رو بزن."
    return None


@router.post("/api/login", include_in_schema=False, dependencies=[Depends(same_site)])
async def login(request: Request):
    b = await body(request)
    name = str(b.get("username") or b.get("email") or "").strip()
    keys = ("ip:" + ip(request), "name:" + name.lower())
    LOGIN.check(*keys)  # only wrong passwords count against the limit
    u = store.find_email(name) if "@" in name else store.find_user(name)
    if not u or not store.check_pw(str(b.get("password") or ""), u["pw"]):
        LOGIN.add(*keys)
        time.sleep(0.5)
        raise HTTPException(401, "ایمیل (یا نام کاربری) یا رمز اشتباهه")
    why = login_block(u)
    if why:
        raise HTTPException(403, why)
    LOGIN.hits.pop("name:" + name.lower(), None)
    return login_response(u["id"], {"ok": True})


@router.get("/verify", include_in_schema=False)
def verify(token: str = ""):
    u = store.use_token(token, "verify")
    if not u:
        return HTMLResponse(page_msg("لینک تأیید منقضی یا استفاده‌شده‌ست", "از صفحهٔ ورود «فرستادن دوباره» رو بزن."), 400)
    store.set_user(u["id"], email_verified=1)
    if u["state"] == "waitlist":
        return HTMLResponse(page_msg("ایمیلت تأیید شد ✓", "حسابت تو صف انتظاره؛ وقتی باز شد خبرت می‌کنیم."))
    return login_response(u["id"], RedirectResponse("/welcome", 303))


@router.post("/api/verify/resend", include_in_schema=False, dependencies=[Depends(same_site)])
async def resend(request: Request):
    b = await body(request)
    email = str(b.get("email") or "").strip().lower()
    MAIL.hit("ip:" + ip(request), "mail:" + email)
    u = store.find_email(email)
    if u and not u["email_verified"]:
        send_verify(u)
    return {"ok": True, "message": "اگه این ایمیل ثبت شده و تأیید نشده، لینک تازه فرستادیم."}


@router.post("/api/password/forgot", include_in_schema=False, dependencies=[Depends(same_site)])
async def forgot(request: Request):
    """Always the same answer, so nobody can probe which emails have accounts."""
    b = await body(request)
    email = str(b.get("email") or "").strip().lower()
    MAIL.hit("ip:" + ip(request), "mail:" + email)
    if not smtp_ready():
        raise HTTPException(503, "ایمیل پنل هنوز راه‌اندازی نشده؛ برای بازیابی رمز به پشتیبانی پیام بده.")
    u = store.find_email(email)
    if u:
        tok = store.new_token(u["id"], "reset", 2)
        mail(email, "بازیابی رمز داشبورد اینستاگرام", f"سلام!\n\nبرای گذاشتن رمز تازه این لینک رو باز کن (تا ۲ ساعت اعتبار داره):\n{link('/reset?token=' + tok)}\n\nاگه درخواست نکردی، کاری نکن؛ رمزت عوض نمی‌شه.")
    return {"ok": True, "message": "اگه حسابی با این ایمیل هست، لینک بازیابی رو فرستادیم."}


@router.get("/reset", include_in_schema=False)
def reset_page():
    return page("login.html")


@router.post("/api/password/reset", include_in_schema=False, dependencies=[Depends(same_site)])
async def reset(request: Request):
    b = await body(request)
    LOGIN.hit("ip:" + ip(request))
    pw = str(b.get("password") or "")
    if len(pw) < 8:
        raise HTTPException(400, "رمز باید دست‌کم ۸ حرف باشه")
    u = store.use_token(b.get("token"), "reset")
    if not u:
        raise HTTPException(400, "لینک بازیابی منقضی یا استفاده‌شده‌ست؛ دوباره درخواست بده.")
    store.set_user(u["id"], pw=store.hash_pw(pw), email_verified=1)
    store.q("DELETE FROM sessions WHERE user_id = ?", u["id"])  # every old sign-in ends
    if u["state"] == "waitlist":
        return {"ok": True, "message": "رمز عوض شد. حسابت هنوز تو صف انتظاره."}
    return login_response(u["id"], {"ok": True, "message": "رمز عوض شد ✓"})


# ---------- Google sign-in (optional: Admin → Google client id/secret) ----------
# https://developers.google.com/identity/protocols/oauth2/web-server

def google_cfg():
    g = store.setting("google_oauth", {}) or {}
    return g if g.get("client_id") and g.get("client_secret") else None


@router.get("/auth/google", include_in_schema=False)
def google_start():
    g = google_cfg()
    if not g:
        raise HTTPException(404)
    state = secrets.token_urlsafe(16)
    q = urllib.parse.urlencode({"client_id": g["client_id"], "redirect_uri": link("/auth/google/callback"), "response_type": "code",
                                "scope": "openid email", "state": state, "prompt": "select_account"})
    r = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + q, 303)
    r.set_cookie("g_state", state, max_age=600, httponly=True, secure=config.SECURE_COOKIES, samesite="lax")
    return r


@router.get("/auth/google/callback", include_in_schema=False)
def google_back(request: Request, code: str = "", state: str = ""):
    g = google_cfg()
    if not g or not code or not state or state != request.cookies.get("g_state"):
        return HTMLResponse(page_msg("ورود با گوگل نشد", "دوباره امتحان کن."), 400)
    data = urllib.parse.urlencode({"code": code, "client_id": g["client_id"], "client_secret": g["client_secret"],
                                   "redirect_uri": link("/auth/google/callback"), "grant_type": "authorization_code"}).encode()
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=20) as r:
            tok = json.load(r)
        with urllib.request.urlopen("https://openidconnect.googleapis.com/v1/userinfo?" + urllib.parse.urlencode({"access_token": tok["access_token"]}), timeout=20) as r:
            info = json.load(r)
    except Exception:  # noqa: BLE001
        return HTMLResponse(page_msg("ورود با گوگل نشد", "گوگل جواب نداد؛ دوباره امتحان کن."), 502)
    email, sub = str(info.get("email") or "").lower(), str(info.get("sub") or "")
    if not email or not info.get("email_verified"):
        return HTMLResponse(page_msg("ایمیل گوگل تأییدشده نیست", ""), 400)
    u = store.find_email(email)
    if not u:
        if mode() == "closed":
            return HTMLResponse(page_msg("ثبت‌نام فعلاً بسته‌ست", ""), 403)
        u = create_account(email, verified=True, google_sub=sub)
    else:
        store.set_user(u["id"], email_verified=1, google_sub=sub)
        u = store.get_user(u["id"])
    if u["state"] == "waitlist":
        return HTMLResponse(page_msg("تو صف انتظاری ✓", "وقتی حسابت باز شد بهت ایمیل می‌زنیم."))
    return login_response(u["id"], RedirectResponse("/welcome" if time.time() - u["created_at"] < 600 else "/", 303))


# ---------- deleting an account ----------

@router.post("/api/me/delete", include_in_schema=False, dependencies=[Depends(same_site)])
async def delete_me(request: Request, user=Depends(need_user)):
    """The person, every page they own, their files, keys and sign-ins: gone. Needs the password (or the
    word «حذف» for a Google-only account)."""
    b = await body(request)
    person = store.get_user(user["person"]["id"])
    if person["google_sub"] and not b.get("password"):
        if str(b.get("confirm") or "").strip() != "حذف":
            raise HTTPException(400, "برای تأیید، کلمهٔ «حذف» رو بنویس")
    elif not store.check_pw(str(b.get("password") or ""), person["pw"]):
        raise HTTPException(401, "رمز اشتباهه")
    if person["is_admin"] and sum(1 for u in store.users() if u["is_admin"]) == 1:
        raise HTTPException(400, "تو تنها ادمین پنلی؛ اول یه ادمین دیگه بساز.")
    ids = [person["id"]] + [u["id"] for u in store.users() if u["kind"] == "page" and u["owner_id"] == person["id"]]
    for i in ids:
        shutil.rmtree(config.user_dir(i), ignore_errors=True)
    store.delete_user(person["id"])
    from fastapi.responses import JSONResponse
    from .web import COOKIE
    resp = JSONResponse({"ok": True, "message": "حسابت و همهٔ داده‌هاش پاک شد."})
    resp.delete_cookie(COOKIE)
    return resp


# ---------- admin: waitlist and overview ----------

@router.get("/api/admin/accounts", include_in_schema=False)
def admin_accounts(admin=Depends(need_admin)):
    from . import jobs
    people = [u for u in store.users() if u["kind"] == "person"]
    errors = []
    for u in store.users():
        st = store.status(u)
        if st.get("refresh_at") and st.get("refresh_ok") is False:
            errors.append({"id": u["id"], "name": store.prefs(u).get("page_name") or u["username"], "at": st.get("refresh_at"), "log": (st.get("refresh_log") or "")[-300:]})
    today = store.q1("SELECT COALESCE(SUM(panel_calls),0) AS p, COALESCE(SUM(own_calls),0) AS o FROM ai_usage WHERE day = ?",
                     time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3.5 * 3600)))
    month = store.q1("SELECT COALESCE(SUM(panel_calls),0) AS p, COALESCE(SUM(own_calls),0) AS o FROM ai_usage WHERE day >= ?",
                     time.strftime("%Y-%m-01", time.gmtime(time.time() + 3.5 * 3600)))
    top = store.q("SELECT u.username, SUM(a.panel_calls) AS p, SUM(a.own_calls) AS o FROM ai_usage a JOIN users u ON u.id = a.user_id "
                  "WHERE a.day >= ? GROUP BY a.user_id ORDER BY p DESC LIMIT 10", time.strftime("%Y-%m-01", time.gmtime(time.time() + 3.5 * 3600)))
    return {"mode": mode(), "smtp": smtp_ready(), "google": bool(google_cfg()),
            "people": len(people), "active": sum(1 for u in people if u["state"] == "active"), "pages": sum(1 for u in store.users() if u["kind"] == "page"),
            "verified": sum(1 for u in people if u["email_verified"]),
            "waitlist": [{"id": u["id"], "email": u["email"], "at": u["created_at"], "verified": bool(u["email_verified"])} for u in people if u["state"] == "waitlist"],
            "sync_errors": errors[:30], "ai": {"today": dict(today), "month": dict(month), "top": [dict(r) for r in top]},
            "queue": jobs.pending(), "queue_stats": {k: v for k, v in jobs.stats.items() if k != "running"}, "running": list(jobs.stats["running"]),
            "quota": quota(), "limits": limits()}


@router.post("/api/admin/accounts", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_accounts_save(request: Request, admin=Depends(need_admin)):
    b = await body(request)
    if b.get("mode") in ("closed", "open", "waitlist"):
        store.set_setting("signup_mode", b["mode"])
        store.set_setting("allow_signup", b["mode"] != "closed")
    if isinstance(b.get("quota"), dict):
        store.set_setting("ai_quota", {"daily": max(0, int(b["quota"].get("daily") or 0)), "monthly": max(0, int(b["quota"].get("monthly") or 0))})
    if isinstance(b.get("limits"), dict):
        store.set_setting("limits", {"connections": max(1, int(b["limits"].get("connections") or 6)), "competitors": max(0, int(b["limits"].get("competitors") or 10))})
    if isinstance(b.get("google"), dict):
        g = store.setting("google_oauth", {}) or {}
        cid, sec = str(b["google"].get("client_id") or "").strip(), str(b["google"].get("client_secret") or "").strip()
        store.set_setting("google_oauth", {"client_id": cid, "client_secret": sec if sec and not sec.startswith("•") else g.get("client_secret", "")})
    approved = []
    for uid in b.get("approve") or []:
        u = store.get_user(int(uid))
        if u and u["state"] == "waitlist":
            store.set_user(u["id"], state="active")
            approved.append(u["id"])
            if u["email"] and smtp_ready():
                mail(u["email"], "حسابت باز شد ✓", f"سلام!\n\nحسابت تو داشبورد اینستاگرام باز شد. از اینجا وارد شو:\n{link('/login')}")
    return {"ok": True, "approved": approved}


def quota():
    q = store.setting("ai_quota", {}) or {}
    return {"daily": int(q.get("daily", 20)), "monthly": int(q.get("monthly", 300))}


def limits():
    lim = store.setting("limits", {}) or {}
    return {"connections": int(lim.get("connections", 6)), "competitors": int(lim.get("competitors", 10))}


def check_quota(user):
    """Calls on the panel's own key are free up to a daily and monthly quota; the person's own key is unlimited."""
    q = quota()
    pid = store.person_id(user)
    if q["daily"] and store.ai_used(pid, 1)["panel"] >= q["daily"]:
        from .ai import AIError
        raise AIError(f"سهمیهٔ رایگان امروزِ هوش مصنوعی ({q['daily']} درخواست) تموم شد. کلید Claude، GPT یا یه سرویس رایگان مثل Gemini رو تو «تنظیمات ← هوش مصنوعی» بذار تا محدودیت نداشته باشی.")
    if q["monthly"] and store.ai_used(pid, 31)["panel"] >= q["monthly"]:
        from .ai import AIError
        raise AIError(f"سهمیهٔ رایگان این ماه ({q['monthly']} درخواست) تموم شد. کلید یا سرویس هوش مصنوعی خودت رو تو تنظیمات وصل کن.")


def page_msg(title, text):
    e = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    return (f"<!doctype html><html lang=fa dir=rtl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}</title><link rel=stylesheet href=/assets/pages.css><main style='max-width:32rem;margin:15vh auto;padding:0 16px;text-align:center'>"
            f"<h1>{e(title)}</h1><p>{e(text)}</p><p><a href=/login>صفحهٔ ورود</a></p></main></html>")


@router.get("/privacy", include_in_schema=False)
def privacy():
    return page("privacy.html")


@router.get("/welcome", include_in_schema=False)
def welcome(request: Request):
    from .web import current_user
    return page("welcome.html") if current_user(request) else RedirectResponse("/login")
