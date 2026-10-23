"""The web panel: sign-in, each user's dashboard, their settings (connections, AI, Telegram, goals,
Claude/ChatGPT token), the admin page, a read-only JSON API for ChatGPT Actions, and the MCP endpoint.

Run: uvicorn sajadai.web:app --host 0.0.0.0 --port 8000   (or `python -m sajadai serve`, or docker compose up)
"""
import contextlib, json, re, secrets, threading, time, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from mcp.server.transport_security import TransportSecuritySettings

from . import agents, ai, analysis, billing, calendar_fa, config, ig, mcp_server, ops, pages, pipeline, publish, store
from .fa import beats as fa_beats, caption as fa_caption, hooks as fa_hooks, human as fa_human, text as fa_text, viral as fa_viral
AI = ai  # the module, for functions with a local named ai

COOKIE = "sj_session"
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

mcp = mcp_server.build(mcp_server.hosted_user)
# stateless + JSON: every call stands alone, so any replica can answer and the token is checked each time.
# Host checks are off because the panel sits behind its own domain; the token is what protects the data.
mcp_http = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                   transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


@contextlib.asynccontextmanager
async def lifespan(_):
    store.db()
    stop = threading.Event()
    if config.SCHEDULER:
        threading.Thread(target=pipeline.scheduler_loop, args=(stop,), daemon=True, name="scheduler").start()
    async with mcp.session_manager.run():
        yield
    stop.set()


api = FastAPI(title="Instagram dashboard API", version="1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
              description="Read-only access to one user's Instagram dashboard. Authenticate with the token from "
                          "Settings → Claude / ChatGPT as a Bearer token.")


# ---------- auth helpers ----------

def current_user(request: Request):
    """The page this browser is working on (a users row as a dict: its data, settings and keys), with
    "person" (who signed in), "role" (theirs on this page: owner, editor or viewer) and "is_admin" (the
    person's). A person's own page is the default; another page needs a membership."""
    tok = request.cookies.get(COOKIE)
    person = store.session_user(tok)
    if not person:
        return None
    page, role = person, "owner"
    acting = store.session_acting(tok)
    if acting and acting != person["id"]:
        r = store.role_for(person["id"], acting)
        p = store.get_user(acting) if r else None
        if p:
            page, role = p, r
    u = dict(page)
    u.update(person=dict(person), role=role, is_admin=bool(person["is_admin"]))
    return u


def need_user(request: Request):
    """Anyone on the page, viewers included: for reading."""
    u = current_user(request)
    if not u:
        raise HTTPException(401, "وارد نشدی")
    return u


def need_editor(user=Depends(need_user)):
    """Owners and editors: changing content (goals, board, ideas) and using the AI tools."""
    if user["role"] not in ("owner", "editor"):
        raise HTTPException(403, "دسترسی تو به این پیج فقط دیدنه")
    return user


def need_owner(user=Depends(need_user)):
    """The page's owner: its connections, keys, token, team and public kit."""
    if user["role"] != "owner":
        raise HTTPException(403, "فقط صاحب پیج می‌تونه این رو عوض کنه")
    return user


def need_admin(user=Depends(need_user)):
    if not user["is_admin"]:
        raise HTTPException(403, "فقط ادمین")
    return user


def same_site(request: Request):
    # a custom header can't be sent cross-site without a CORS preflight, which this app never allows
    if request.headers.get("x-requested-with") != "sajadai":
        raise HTTPException(400, "bad request")


def api_user(request: Request):
    h = request.headers.get("authorization", "")
    u = store.user_by_api_token(h[7:].strip() if h.lower().startswith("bearer ") else request.query_params.get("token", ""))
    if not u:
        raise HTTPException(401, "Missing or invalid token (Settings → Claude / ChatGPT)")
    return u


def login_response(user_id, body, acting=None):
    tok = store.new_session(user_id)
    if acting:
        store.set_acting(tok, acting)
    r = JSONResponse(body)
    r.set_cookie(COOKIE, tok, max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=config.SECURE_COOKIES)
    return r


async def body(request: Request) -> dict:
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON نامعتبر")
    if not isinstance(b, dict):
        raise HTTPException(400, "JSON نامعتبر")
    return b


def check_new_login(username, password):
    if not USERNAME.match(username or ""):
        raise HTTPException(400, "نام کاربری: ۳ تا ۳۲ حرف انگلیسی، عدد، نقطه، خط تیره یا زیرخط")
    if len(password or "") < 8:
        raise HTTPException(400, "رمز باید دست‌کم ۸ حرف باشه")
    if store.name_taken(username):
        raise HTTPException(400, "این نام کاربری گرفته شده")


def new_user(username, password, is_admin=False):
    uid = store.create_user(username, password, is_admin, prefs={"page_name": username})
    pipeline.ensure_user_dir(uid)
    return uid


# ---------- pages ----------

ASSET_REF = re.compile(r'((?:href|src)=")(/?assets/[^"?#]+)(")')


def versioned(html):
    """Add ?v=<file mtime> to every asset link, so browsers and Cloudflare (assets are cached for a
    week) fetch a file again as soon as it changes."""
    def add(m):
        p = config.ROOT / m[2].lstrip("/")
        try:
            return f"{m[1]}{m[2]}?v={int(p.stat().st_mtime)}{m[3]}"
        except OSError:
            return m[0]
    return ASSET_REF.sub(add, html)


def page(name):
    return HTMLResponse(versioned((config.PANEL / name).read_text(encoding="utf-8")), headers={"Cache-Control": "no-cache"})


@api.get("/", include_in_schema=False)
def dashboard(request: Request):
    if store.user_count() == 0:
        return RedirectResponse("/setup")
    u = current_user(request)
    if not u:
        return RedirectResponse("/login")
    # the page reads the user's name, page name and admin link from /api/me itself
    html = (config.ROOT / "index.html").read_text(encoding="utf-8")
    blog = (store.user_secrets(u).get("connections", {}).get("metricool") or {}).get("blog_id", "")
    if blog:
        html = html.replace("app.metricool.com/planner", f"app.metricool.com/planner?blogId={_esc(str(blog))}")
    return HTMLResponse(versioned(html), headers={"Cache-Control": "no-cache"})


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


@api.get("/data/data.json", include_in_schema=False)
def user_data(user=Depends(need_user)):
    p = config.user_dir(user["id"]) / "data" / "data.json"
    if not p.exists():
        pipeline.ensure_user_dir(user["id"])
    return FileResponse(p, media_type="application/json", headers={"Cache-Control": "no-store"})


@api.get("/assets/{name:path}", include_in_schema=False)
def assets(name: str):
    root = (config.ROOT / "assets").resolve()
    p = (root / name).resolve()
    if not p.is_relative_to(root) or not p.is_file():  # resolve() first, so ../ can't step outside assets/
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=604800"})


@api.get("/login", include_in_schema=False)
def login_page():
    return page("login.html")


@api.get("/contact", include_in_schema=False)
def contact_page():
    """Address, phone and the eNamad trust seal; public, like the sign-in page."""
    return page("contact.html")


@api.get("/setup", include_in_schema=False)
def setup_page():
    return RedirectResponse("/login") if store.user_count() else page("login.html")


@api.get("/settings", include_in_schema=False)
def settings_page(request: Request):
    return page("settings.html") if current_user(request) else RedirectResponse("/login")


@api.get("/admin", include_in_schema=False)
def admin_page(request: Request):
    u = current_user(request)
    return page("admin.html") if u and u["is_admin"] else RedirectResponse("/login")


@api.get("/logout", include_in_schema=False)
def logout(request: Request):
    store.end_session(request.cookies.get(COOKIE))
    r = RedirectResponse("/login")
    r.delete_cookie(COOKIE)
    r.headers["Clear-Site-Data"] = '"cache"'  # the installed app's offline copy of this user's data goes too
    return r


# ---------- installable app, media kit, printable report ----------

@api.get("/healthz", include_in_schema=False)
def healthz():
    h = ops.health()
    return JSONResponse(h, status_code=200 if h["ok"] else 503, headers={"Cache-Control": "no-store"})


@api.get("/sw.js", include_in_schema=False)
def service_worker():
    # served from the root so it may control the whole site
    return FileResponse(config.ROOT / "assets" / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@api.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(config.ROOT / "assets" / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "public, max-age=86400"})


KIT_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,29}$")


def kit_owner(slug):
    for u in store.users():
        p = store.prefs(u)
        if p.get("kit_enabled") and p.get("kit_slug") == slug:
            return u, p
    return None, None


@api.get("/kit/{slug}", include_in_schema=False)
def media_kit(slug: str):
    u, p = kit_owner(slug.lower()) if KIT_SLUG.match(slug.lower()) else (None, None)
    if not u:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>پیدا نشد</title><p style='font-family:sans-serif;text-align:center;margin-top:20vh' dir=rtl>این مدیاکیت وجود نداره یا خاموش شده.</p>", 404)
    return HTMLResponse(versioned(pages.kit(user_json(u), p, u["username"])), headers={"Cache-Control": "public, max-age=600"})


@api.get("/report", include_in_schema=False)
def printable_report(request: Request, days: int = 7):
    u = current_user(request)
    if not u:
        return RedirectResponse("/login")
    days = days if days in (7, 30, 90) else 7
    return HTMLResponse(versioned(pages.report(user_json(u), store.prefs(u), u["username"], days)), headers={"Cache-Control": "no-store"})


@api.post("/api/me/kit", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_kit(request: Request, user=Depends(need_owner)):
    b = await body(request)
    slug = str(b.get("slug") or "").strip().lower()
    on = bool(b.get("enabled"))
    if on and not KIT_SLUG.match(slug):
        raise HTTPException(400, "آدرس مدیاکیت: ۳ تا ۳۰ حرف انگلیسی کوچک، عدد یا خط تیره")
    if on:
        other, _ = kit_owner(slug)
        if other and other["id"] != user["id"]:
            raise HTTPException(400, "این آدرس رو یکی دیگه برداشته")
    p = store.prefs(user)
    p.update(kit_enabled=on, kit_slug=slug, kit_bio=str(b.get("bio") or "").strip()[:400],
             kit_contact=str(b.get("contact") or "").strip()[:200], kit_handle=str(b.get("handle") or "").strip().lstrip("@")[:40])
    store.set_prefs(user["id"], p)
    return {"ok": True, "url": (pipeline.public_url() or "") + "/kit/" + slug if on else None}


# ---------- notifications (the bell) ----------

@api.get("/api/me/notifications", include_in_schema=False)
def notifications(user=Depends(need_user)):
    items = load_content(user, "notifications.json", [])[:50]
    # what each person has read is theirs, so a teammate opening the bell doesn't clear it for the owner
    seen = store.prefs(user["person"]).get("notifications_seen") or {}
    # before teams this was one timestamp for the person's own page
    seen = seen.get(str(user["id"]), "") if isinstance(seen, dict) else (seen if user["id"] == user["person"]["id"] else "")
    return {"items": items, "unread": sum(1 for i in items if str(i.get("at") or "") > seen)}


@api.post("/api/me/notifications/seen", include_in_schema=False, dependencies=[Depends(same_site)])
def notifications_seen(user=Depends(need_user)):
    person = store.get_user(user["person"]["id"])
    p = store.prefs(person)
    if not isinstance(p.get("notifications_seen"), dict):
        p["notifications_seen"] = {}
    p["notifications_seen"][str(user["id"])] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.set_prefs(person["id"], p)
    return {"ok": True}


# ---------- pages and teams ----------
# Every page is a users row with its own data folder, connections and settings. A person's own row is
# their first page; extra pages are rows of kind 'page' that nobody signs in as. Others join a page as
# editor or viewer through the memberships table, and each browser remembers which page it has open.

def max_pages():
    return int(store.setting("max_pages", 5) or 5)


@api.post("/api/me/switch", include_in_schema=False, dependencies=[Depends(same_site)])
async def switch_page(request: Request, user=Depends(need_user)):
    b = await body(request)
    try:
        pid = int(b.get("page"))
    except (TypeError, ValueError):
        raise HTTPException(400, "پیج نامعتبره")
    person = user["person"]
    if not store.role_for(person["id"], pid):
        raise HTTPException(403, "به این پیج دسترسی نداری")
    store.set_acting(request.cookies.get(COOKIE), None if pid == person["id"] else pid)
    return {"ok": True}


@api.post("/api/pages", include_in_schema=False, dependencies=[Depends(same_site)])
async def new_page(request: Request, user=Depends(need_user)):
    b = await body(request)
    name = str(b.get("name") or "").strip()[:60]
    if not name:
        raise HTTPException(400, "اسم پیج رو بنویس")
    person = user["person"]
    owned = sum(1 for u in store.users() if u["kind"] == "page" and u["owner_id"] == person["id"])
    limit = billing.max_pages(person, max_pages())
    if owned + 1 >= limit and not person["is_admin"]:
        raise HTTPException(400, f"با اشتراک فعلیت حداکثر {limit} پیج می‌تونی داشته باشی" if billing.config()["enabled"]
                            else f"هر حساب حداکثر {limit} پیج می‌تونه داشته باشه")
    pid = store.create_page(person["id"], name)
    pipeline.ensure_user_dir(pid)
    store.set_acting(request.cookies.get(COOKIE), pid)
    return {"ok": True, "id": pid}


@api.delete("/api/pages/{pid}", include_in_schema=False, dependencies=[Depends(same_site)])
def delete_page(pid: int, request: Request, user=Depends(need_user)):
    page = store.get_user(pid)
    person = user["person"]
    if not page or page["kind"] != "page" or store.role_for(person["id"], pid) != "owner":
        raise HTTPException(403, "فقط صاحب یه پیج اضافه می‌تونه پاکش کنه")
    store.delete_user(pid)  # its folder stays on disk, so a mistake can be undone by hand
    store.set_acting(request.cookies.get(COOKIE), None)
    return {"ok": True}


@api.get("/api/me/members", include_in_schema=False)
def team(user=Depends(need_user)):
    return {"members": store.members(user["id"]), "you": user["person"]["id"], "role": user["role"]}


@api.post("/api/me/members", include_in_schema=False, dependencies=[Depends(same_site)])
async def add_member(request: Request, user=Depends(need_owner)):
    """Add someone who already has an account here, by their username, as editor or viewer."""
    b = await body(request)
    role = b.get("role")
    if role not in ("editor", "viewer", "owner"):
        raise HTTPException(400, "نقش باید editor، viewer یا owner باشه")
    who = store.find_user(str(b.get("username") or ""))
    if not who:
        raise HTTPException(400, "کسی با این نام کاربری اینجا حساب نداره؛ اول باید ثبت‌نام کنه")
    if who["id"] == user["id"]:
        raise HTTPException(400, "این پیج خودشه")
    store.set_member(user["id"], who["id"], role)
    return {"ok": True}


@api.delete("/api/me/members/{uid}", include_in_schema=False, dependencies=[Depends(same_site)])
def remove_member(uid: int, request: Request, user=Depends(need_user)):
    me_id = user["person"]["id"]
    if uid != me_id and user["role"] != "owner":
        raise HTTPException(403, "فقط صاحب پیج می‌تونه کسی رو برداره")
    if uid == user["id"]:
        raise HTTPException(400, "صاحب اصلی پیج رو نمی‌شه برداشت")
    owners = [m for m in store.members(user["id"]) if m["role"] == "owner"]
    if len(owners) == 1 and owners[0]["id"] == uid:
        raise HTTPException(400, "پیج بدون صاحب نمی‌مونه؛ اول یکی دیگه رو owner کن")
    store.remove_member(user["id"], uid)
    if uid == me_id:  # left the page: back to their own
        store.set_acting(request.cookies.get(COOKIE), None)
    return {"ok": True}


# ---------- sign-in ----------

@api.get("/api/state", include_in_schema=False)
def state(request: Request):
    u = current_user(request)
    return {"setup_needed": store.user_count() == 0, "signup": bool(store.setting("allow_signup", False)),
            "user": u["username"] if u else None}


@api.post("/api/setup", include_in_schema=False, dependencies=[Depends(same_site)])
async def setup(request: Request):
    b = await body(request)
    with store._lock:
        if store.user_count():
            raise HTTPException(400, "ادمین قبلاً ساخته شده")
        check_new_login(b.get("username"), b.get("password"))
        uid = new_user(b["username"], b["password"], is_admin=True)
    return login_response(uid, {"ok": True})


@api.post("/api/login", include_in_schema=False, dependencies=[Depends(same_site)])
async def login(request: Request):
    b = await body(request)
    u = store.find_user(b.get("username") or "")
    if not u or not store.check_pw(b.get("password") or "", u["pw"]):
        time.sleep(0.5)
        raise HTTPException(401, "نام کاربری یا رمز اشتباهه")
    return login_response(u["id"], {"ok": True})


@api.post("/api/signup", include_in_schema=False, dependencies=[Depends(same_site)])
async def signup(request: Request):
    if not store.setting("allow_signup", False):
        raise HTTPException(403, "ثبت‌نام بسته‌ست؛ از ادمین بخواه برات حساب بسازه")
    b = await body(request)
    check_new_login(b.get("username"), b.get("password"))
    return login_response(new_user(b["username"], b["password"]), {"ok": True})


# ---------- the signed-in user's settings ----------

def mask(v):
    v = str(v or "")
    return ("•" * 6 + v[-4:]) if len(v) > 8 else ("•" * len(v))


@api.get("/api/me", include_in_schema=False)
def me(user=Depends(need_user)):
    p, s = store.prefs(user), store.user_secrets(user)
    owner = user["role"] == "owner"
    conns = s.get("connections", {}) if owner else {k: {} for k in s.get("connections", {})}  # teammates see what's connected, not the keys
    panel_ai = store.setting("ai", {}) or {}
    base = pipeline.public_url()
    person = user["person"]
    return {
        "username": person["username"], "is_admin": bool(user["is_admin"]), "role": user["role"],
        "page": {"id": user["id"], "name": p.get("page_name") or user["username"], "own": user["id"] == person["id"]},
        "pages": store.pages_for(person),
        "prefs": {k: p.get(k, "") for k in ("page_name", "page_profile", "telegram_chat")},
        "kit": {"enabled": bool(p.get("kit_enabled")), "slug": p.get("kit_slug", ""), "bio": p.get("kit_bio", ""), "contact": p.get("kit_contact", ""),
                "handle": p.get("kit_handle", ""), "url": (base or "") + "/kit/" + p["kit_slug"] if p.get("kit_enabled") and p.get("kit_slug") else None},
        "connections": {name: {"label": spec["label"], "connected": name in conns,
                               "fields": {f: {"label": lbl, "value": (mask(conns[name].get(f)) if f in ("token", "api_key") else conns[name].get(f, "")) if name in conns else ""}
                                          for f, lbl in spec["fields"].items()}}
                        for name, spec in pipeline.CONNECTIONS.items()},
        "ai": {"chain": [chain_view(c) for c in pipeline.ai_chain(user)] if owner else [{"provider": c["provider"]} for c in pipeline.ai_chain(user)],
               "panel_provider": panel_ai.get("provider") if (panel_ai.get("key") or panel_ai.get("base_url")) and billing.may_use_panel_ai(user) else None,
               **ai.public_catalog()},
        "telegram_ready": bool(store.setting("telegram_bot")),
        "has_token": bool(user["api_token"]),
        "urls": {"base": base, "mcp": (base or "") + "/mcp", "api": (base or "") + "/api/v1", "openapi": (base or "") + "/openapi.json"},
        "goals": load_content(user, "goals.json", []),
        "experiments": load_content(user, "experiments.json", []),
        "topics": load_content(user, "topics.json", []),
        "reel_topics": load_content(user, "reel_topics.json", {}),
        "status": {k: v for k, v in store.status(user).items()},
        "onboarding": onboarding(user, p, s),
        "billing": billing_view(person),
    }


@api.post("/api/me/prefs", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_prefs(request: Request, user=Depends(need_owner)):
    b = await body(request)
    p = store.prefs(user)
    for k in ("page_name", "page_profile", "telegram_chat"):
        if k in b:
            p[k] = str(b[k] or "").strip()[:4000]
    if p.get("telegram_chat") and not re.match(r"^-?\d{3,20}$", p["telegram_chat"]):
        raise HTTPException(400, "chat id تلگرام باید عدد باشه")
    store.set_prefs(user["id"], p)
    return {"ok": True}


@api.post("/api/me/connections/{name}", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_connection(name: str, request: Request, user=Depends(need_owner)):
    spec = pipeline.CONNECTIONS.get(name)
    if not spec:
        raise HTTPException(404)
    b = await body(request)
    s = store.user_secrets(user)
    old = s.get("connections", {}).get(name, {})
    vals = {}
    for f in spec["fields"]:
        v = str(b.get(f) or "").strip()
        vals[f] = old.get(f, "") if (not v or v.startswith("•")) else v  # a masked field left as it was keeps the stored value
    if not all(vals.values()):
        raise HTTPException(400, "همهٔ فیلدها لازمه")
    ok, msg = pipeline.test_connection(name, vals)
    if not ok and not b.get("force"):
        return {"ok": False, "message": msg}
    s.setdefault("connections", {})[name] = vals
    store.set_secrets(user["id"], s)
    return {"ok": True, "message": msg if ok else "ذخیره شد، ولی تست موفق نبود: " + msg}


@api.delete("/api/me/connections/{name}", include_in_schema=False, dependencies=[Depends(same_site)])
def remove_connection(name: str, user=Depends(need_owner)):
    s = store.user_secrets(user)
    s.get("connections", {}).pop(name, None)
    store.set_secrets(user["id"], s)
    return {"ok": True}


def chain_view(c):
    spec = ai.PROVIDERS.get(c["provider"], {})
    return {"id": c.get("id"), "provider": c["provider"], "label": spec.get("label", c["provider"]), "model": c.get("model") or "",
            "base_url": c.get("base_url") or "", "key": mask(c.get("key")) if c.get("key") else "", "group": spec.get("group", "own")}


def save_chain(user, chain):
    s = store.user_secrets(user)
    s["ai_chain"] = chain[:ai.MAX_CHAIN]
    s.pop("ai_key", None)  # the old single key now lives in the chain
    store.set_secrets(user["id"], s)


@api.post("/api/me/ai/connect", include_in_schema=False, dependencies=[Depends(same_site)])
async def ai_connect(request: Request, user=Depends(need_owner)):
    """Add (or re-test) one provider: check the key, find the models, pick one, ask a test question.
    The entry is saved only when the test answer comes back."""
    b = await body(request)
    prov = str(b.get("provider") or "")
    spec = ai.PROVIDERS.get(prov)
    if not spec:
        raise HTTPException(400, "سرویس نامعتبره")
    chain = pipeline.ai_chain(user)
    old = next((c for c in chain if c.get("id") == b.get("id")), None) if b.get("id") else None
    key = str(b.get("key") or "").strip()
    if key.startswith("•"):
        key = (old or {}).get("key", "")
    if not key and not spec.get("key_optional"):
        raise HTTPException(400, "کلید لازمه")
    entry = {"id": old["id"] if old and old["id"] != "legacy" else "p" + secrets.token_hex(4), "provider": prov, "key": key[:400],
             "model": str(b.get("model") or "").strip()[:120], "base_url": "", "private_ok": bool(user["person"]["is_admin"])}
    if spec.get("needs_url"):
        try:
            entry["base_url"] = ai.check_url(b.get("base_url"), entry["private_ok"])
        except ai.AIError as e:
            raise HTTPException(400, str(e))
    try:
        entry, models, message = await run_in_threadpool(lambda: ai.connect(entry))
    except ai.AIError as e:
        return {"ok": False, "message": str(e)}
    chain = [entry if c.get("id") == old["id"] else c for c in chain] if old else chain + [entry]
    if len(chain) > ai.MAX_CHAIN:
        raise HTTPException(400, f"حداکثر {ai.MAX_CHAIN} سرویس")
    save_chain(user, chain)
    return {"ok": True, "message": message, "models": models, "entry": chain_view(entry)}


@api.post("/api/me/ai/chain", include_in_schema=False, dependencies=[Depends(same_site)])
async def ai_chain_order(request: Request, user=Depends(need_owner)):
    """Reorder, remove or change a provider's model: {"items": [{"id", "model"?}, …]} in the new order;
    entries left out are removed."""
    b = await body(request)
    items = b.get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "فهرست نامعتبره")
    have = {c.get("id"): c for c in pipeline.ai_chain(user)}
    chain = []
    for it in items:
        c = have.get(str((it or {}).get("id")))
        if not c or c in chain:
            continue
        if isinstance(it.get("model"), str) and it["model"].strip():
            c = {**c, "model": it["model"].strip()[:120]}
        chain.append(c)
    save_chain(user, chain)
    return {"ok": True, "chain": [chain_view(c) for c in chain]}


@api.post("/api/me/ai/test", include_in_schema=False, dependencies=[Depends(same_site)])
async def ai_test(request: Request, user=Depends(need_owner)):
    """Ask each provider in the chain a short question and say which answer."""
    out = []
    for c in pipeline.ai_chain(user):
        t = time.time()
        try:
            r = await run_in_threadpool(lambda c=c: ai.call(c, "Reply in Persian with one short word.", [{"role": "user", "content": "سلام! فقط بنویس: آماده"}], None, 400, "low"))
            out.append({"id": c.get("id"), "ok": True, "message": f"جواب داد در {time.time() - t:.1f} ثانیه: «{str(r)[:40]}»"})
        except ai.AIError as e:
            out.append({"id": c.get("id"), "ok": False, "message": str(e)})
    return {"ok": True, "results": out}


@api.post("/api/me/goals", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_goals(request: Request, user=Depends(need_editor)):
    b = await body(request)
    goals = b.get("goals")
    if not isinstance(goals, list) or len(goals) > 20:
        raise HTTPException(400, "هدف‌ها باید یه فهرست باشن")
    clean = []
    for i, g in enumerate(goals):
        if not isinstance(g, dict) or g.get("metric") not in ("followers", "reels_7d", "views_7d"):
            raise HTTPException(400, f"هدف {i + 1}: metric باید followers، reels_7d یا views_7d باشه")
        try:
            target = float(g.get("target"))
        except (TypeError, ValueError):
            raise HTTPException(400, f"هدف {i + 1}: عدد هدف نامعتبره")
        dl = g.get("deadline") or None
        if dl and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(dl)):
            raise HTTPException(400, f"هدف {i + 1}: مهلت باید YYYY-MM-DD باشه")
        clean.append({"id": f"g{i + 1}", "label": str(g.get("label") or "")[:80], "metric": g["metric"],
                      "target": int(target) if target.is_integer() else target, "deadline": dl, "why": str(g.get("why") or "")[:300]})
    save_content(user, "goals.json", clean)
    p = store.prefs(user)
    if not p.get("goals_set"):  # the starter goals were looked at and saved: that onboarding step is done
        p["goals_set"] = True
        store.set_prefs(user["id"], p)
    return {"ok": True}


def save_content(user, name, data, reshape=True):
    """Write one of the user's content files; reshape so the dashboard picks it up."""
    d = pipeline.ensure_user_dir(user["id"])
    (d / "content" / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if reshape:
        pipeline.run_script(user["id"], "shape.py", {})


def load_content(user, name, default):
    v = analysis.load(config.user_dir(user["id"]) / "content" / name)  # {} when missing or broken
    return v if isinstance(v, type(default)) else default


REEL_URL = re.compile(r"^https://(www\.)?instagram\.com/(reel|reels|p)/[A-Za-z0-9_-]+/?(\?.*)?$")
EXP_METRICS = ("multiple", "view_rate", "save_rate", "shares_per_1k", "avg_watch")


def slug(text, taken, fallback="t"):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:30] or fallback
    out, n = s, 2
    while out in taken:
        out, n = f"{s}-{n}", n + 1
    taken.add(out)
    return out


@api.post("/api/me/experiments", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_experiments(request: Request, user=Depends(need_editor)):
    b = await body(request)
    exps = b.get("experiments")
    if not isinstance(exps, list) or len(exps) > 50:
        raise HTTPException(400, "آزمایش‌ها باید یه فهرست باشن")
    clean, taken = [], set()
    for i, e in enumerate(exps):
        if not isinstance(e, dict) or not str(e.get("title") or "").strip():
            raise HTTPException(400, f"آزمایش {i + 1}: عنوان لازمه")
        if e.get("metric") not in EXP_METRICS:
            raise HTTPException(400, f"آزمایش {i + 1}: معیار نامعتبره")
        sides = {}
        for k in ("a", "b"):
            s = e.get(k) if isinstance(e.get(k), dict) else {}
            url = str(s.get("url") or "").strip()
            if url and not REEL_URL.match(url):
                raise HTTPException(400, f"آزمایش {i + 1}: لینک ریل {k.upper()} باید لینک اینستاگرام باشه")
            sides[k] = {"label": str(s.get("label") or "")[:200], "url": url}
        clean.append({"id": slug(e.get("id") or e["title"], taken, "exp"), "title": str(e["title"]).strip()[:120],
                      "hypothesis": str(e.get("hypothesis") or "")[:500], "metric": e["metric"], **sides,
                      "notes": str(e.get("notes") or "")[:1000]})
    save_content(user, "experiments.json", clean)
    return {"ok": True}


@api.post("/api/me/topics", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_topics(request: Request, user=Depends(need_editor)):
    """Topics ({label, keywords}) and the manual reel → topic fixes ({reel url: topic id})."""
    b = await body(request)
    topics, manual = b.get("topics"), b.get("reel_topics") or {}
    if not isinstance(topics, list) or len(topics) > 40 or not isinstance(manual, dict) or len(manual) > 2000:
        raise HTTPException(400, "موضوع‌ها نامعتبرن")
    clean, taken = [], {"other"}
    for i, t in enumerate(topics):
        label = str((t or {}).get("label") or "").strip()[:60] if isinstance(t, dict) else ""
        if not label:
            raise HTTPException(400, f"موضوع {i + 1}: اسم لازمه")
        kws = t.get("keywords") or []
        if isinstance(kws, str):
            kws = re.split(r"[,،\n]", kws)
        kws = [str(k).strip()[:60] for k in kws if str(k).strip()][:40]
        tid = str(t.get("id") or "")
        if re.match(r"^[a-z0-9-]{1,40}$", tid) and tid not in taken:
            taken.add(tid)  # an existing topic keeps its id, so reel fixes pointing at it still work
        else:
            tid = slug(label, taken, "topic")
        clean.append({"id": tid, "label": label, "keywords": kws})
    ids = {t["id"] for t in clean} | {"other"}
    fixes = {}
    for url, tid in manual.items():
        if not REEL_URL.match(str(url)) or tid not in ids:
            raise HTTPException(400, "یه موضوع دستی به ریل یا موضوع ناموجود اشاره می‌کنه")
        fixes[url] = tid
    save_content(user, "topics.json", clean, reshape=False)
    save_content(user, "reel_topics.json", fixes)
    return {"ok": True}


BOARD_STAGES = ("idea", "script", "filmed", "published")


# ---------- Instagram: publishing, comments, keyword automation ----------

def ig_call(fn):
    try:
        return fn()
    except ig.IGError as e:
        raise HTTPException(400, str(e))


@api.get("/m/{name}", include_in_schema=False)
def ig_media(name: str):
    """An uploaded video or cover, at an unguessable address, for Instagram to fetch while publishing."""
    p = ig.media_path(name)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, media_type="video/mp4" if name.endswith((".mp4", ".mov")) else "image/jpeg",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


@api.post("/api/me/ig/upload", include_in_schema=False, dependencies=[Depends(same_site)])
async def ig_upload(request: Request, kind: str = "video", user=Depends(need_editor)):
    """The raw file in the body (no form encoding): a reel video (MP4/MOV, up to 100MB) or a JPEG cover."""
    if kind not in ("video", "cover"):
        raise HTTPException(400, "نوع فایل نامعتبره")
    cap = ig.MAX_VIDEO if kind == "video" else 8 * 1024 * 1024
    name = ig.new_media_name(".mp4" if kind == "video" else ".jpg")
    path, size, head = ig.MEDIA_DIR / name, 0, b""
    try:
        with open(path, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > cap:
                    raise HTTPException(413, f"فایل بزرگ‌تر از {cap // (1024 * 1024)} مگابایته")
                if len(head) < 16:
                    head += chunk[:16]
                f.write(chunk)
        if kind == "video" and not ig.sniff_video(head):
            raise HTTPException(400, "فایل ویدیوی MP4 یا MOV نیست")
        if kind == "cover" and not head.startswith(b"\xff\xd8"):
            raise HTTPException(400, "کاور باید JPEG باشه")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"name": name, "size": size}


@api.get("/api/me/ig/queue", include_in_schema=False)
def ig_queue_list(user=Depends(need_user)):
    q = ig.load_queue(user)
    return {"items": [{k: v for k, v in i.items() if k not in ("container", "ig_id")} for i in reversed(q)],
            "public_url": pipeline.public_url().startswith("https://"),
            "connected": "instagram" in store.user_secrets(user).get("connections", {})}


@api.get("/api/me/ig/limit", include_in_schema=False)
async def ig_limit(user=Depends(need_user)):
    return await run_in_threadpool(lambda: ig_call(lambda: ig.limit(user)))


@api.post("/api/me/ig/queue", include_in_schema=False, dependencies=[Depends(same_site)])
async def ig_queue_add(request: Request, user=Depends(need_editor)):
    """Queue a reel: publish now, or at a time (Tehran). The scheduler does the rest within a minute."""
    b = await body(request)
    if not ig.media_path(str(b.get("video") or "")):
        raise HTTPException(400, "اول ویدیو رو آپلود کن")
    cover = str(b.get("cover") or "")
    if cover and not ig.media_path(cover):
        raise HTTPException(400, "کاور پیدا نشد؛ دوباره آپلود کن")
    caption = str(b.get("caption") or "").strip()
    if len(caption) > ig.CAPTION_MAX:
        raise HTTPException(400, f"کپشن بیشتر از {ig.CAPTION_MAX} حرفه")
    if len(re.findall(r"#\w", caption)) > 30:
        raise HTTPException(400, "اینستاگرام بیشتر از ۳۰ هشتگ قبول نمی‌کنه")
    when = time.time()
    if b.get("when"):
        try:
            when = datetime.fromisoformat(str(b["when"])).replace(tzinfo=timezone(timedelta(hours=3, minutes=30))).timestamp()
        except ValueError:
            raise HTTPException(400, "زمان نامعتبره")
        if when < time.time() - 120:
            raise HTTPException(400, "این زمان گذشته")
    if not pipeline.public_url().startswith("https://"):
        raise HTTPException(400, "آدرس عمومی https پنل تنظیم نشده؛ اینستاگرام ویدیو رو باید از اونجا برداره (ادمین: پنل مدیریت ← آدرس عمومی).")
    if "instagram" not in store.user_secrets(user).get("connections", {}):
        raise HTTPException(400, "Instagram API وصل نیست؛ از تنظیمات ← اتصال‌ها وصلش کن.")
    item = {"id": "q" + secrets.token_hex(4), "video": b["video"], "cover": cover, "caption": caption, "when": when,
            "share_to_feed": b.get("share_to_feed", True) is not False, "thumb_offset": int(b.get("thumb_offset") or 0),
            "card": str(b.get("card") or "")[:40], "status": "scheduled", "created": time.time(),
            "by": user["person"]["username"], "note": "تو صف؛ تا یک دقیقهٔ دیگه شروع می‌شه." if when <= time.time() + 60 else ""}
    q = ig.load_queue(user)
    q.append(item)
    ig.save_queue(user, q)
    return {"ok": True, "item": item}


@api.delete("/api/me/ig/queue/{qid}", include_in_schema=False, dependencies=[Depends(same_site)])
def ig_queue_cancel(qid: str, user=Depends(need_editor)):
    q = ig.load_queue(user)
    item = next((i for i in q if i["id"] == qid), None)
    if not item:
        raise HTTPException(404)
    if item["status"] == "processing":
        raise HTTPException(400, "اینستاگرام داره پردازشش می‌کنه؛ دیگه نمی‌شه لغوش کرد")
    if item["status"] == "scheduled":
        ig.drop_media(item.get("video"), item.get("cover"))
    ig.save_queue(user, [i for i in q if i["id"] != qid])
    return {"ok": True}


@api.post("/api/me/comments/reply", include_in_schema=False, dependencies=[Depends(same_site)])
async def comment_reply(request: Request, user=Depends(need_editor)):
    """Answer a comment publicly, send its author the one private reply Instagram allows, or hide it."""
    b = await body(request)
    cid, text, how = str(b.get("comment_id") or ""), str(b.get("text") or "").strip(), b.get("how", "public")
    if not re.fullmatch(r"\d{5,30}", cid):
        raise HTTPException(400, "کامنت نامعتبره")
    if how == "hide":
        await run_in_threadpool(lambda: ig_call(lambda: ig.hide_comment(user, cid, b.get("hide", True) is not False)))
        return {"ok": True, "message": "کامنت پنهان شد" if b.get("hide", True) is not False else "کامنت دوباره پیدا شد"}
    if not text:
        raise HTTPException(400, "متن جواب خالیه")
    if how == "private":
        await run_in_threadpool(lambda: ig_call(lambda: ig.private_reply(user, cid, text)))
        return {"ok": True, "message": "پیام خصوصی فرستاده شد ✓"}
    await run_in_threadpool(lambda: ig_call(lambda: ig.reply_comment(user, cid, text)))
    # mark it answered here too, so the list updates before the next data fetch
    raw_path = config.user_dir(user["id"]) / "raw" / "ig_comments.json"
    raw = analysis.load(raw_path)
    for p in (raw or {}).get("posts", []):
        for c in p.get("comments", []):
            if c.get("id") == cid:
                c.setdefault("replies", []).append({"text": text, "user": raw.get("username"), "at": datetime.now(timezone.utc).isoformat()})
    if raw:
        raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "message": "جواب گذاشته شد ✓"}


AUTO_KEYS = ("media_id", "label", "keyword", "message", "public_reply", "active")


@api.get("/api/me/ig/auto", include_in_schema=False)
def ig_auto_get(user=Depends(need_user)):
    a = ig.load_auto(user)
    reels = [{"id": p.get("id"), "label": (p.get("caption") or "").split("\n")[0][:70] or "ریل", "url": p.get("url")}
             for p in (analysis.load(config.user_dir(user["id"]) / "raw" / "ig_comments.json") or {}).get("posts", []) if p.get("id")]
    ig_raw = analysis.load(config.user_dir(user["id"]) / "raw" / "ig.json") or {}
    seen = {r["id"] for r in reels}
    for m in (ig_raw.get("media") or [])[:30]:
        if m.get("id") and m["id"] not in seen and m.get("media_product_type") in ("REELS", "FEED"):
            reels.append({"id": m["id"], "label": (m.get("caption") or "").split("\n")[0][:70] or "پست", "url": m.get("permalink")})
    return {"rules": a["rules"], "log": list(reversed(a.get("log", [])))[:30], "checked": a.get("checked"), "reels": reels[:40]}


@api.post("/api/me/ig/auto", include_in_schema=False, dependencies=[Depends(same_site)])
async def ig_auto_save(request: Request, user=Depends(need_editor)):
    b = await body(request)
    rules = b.get("rules")
    if not isinstance(rules, list) or len(rules) > 20:
        raise HTTPException(400, "فهرست قانون‌ها نامعتبره")
    a = ig.load_auto(user)
    old = {r["id"]: r for r in a["rules"]}
    clean = []
    for i, r in enumerate(rules):
        r = {k: r.get(k) for k in AUTO_KEYS} | {"id": str(r.get("id") or "") or "r" + secrets.token_hex(4)}
        if not re.fullmatch(r"\d{5,30}", str(r["media_id"] or "")):
            raise HTTPException(400, f"قانون {i + 1}: ریل رو انتخاب کن")
        r["keyword"] = str(r["keyword"] or "").strip()[:40]
        r["message"] = str(r["message"] or "").strip()[:900]
        if not r["keyword"] or not r["message"]:
            raise HTTPException(400, f"قانون {i + 1}: کلمه و پیام لازمه")
        r["label"] = str(r["label"] or "")[:80]
        r["public_reply"], r["active"] = bool(r["public_reply"]), bool(r["active"])
        r["count"] = (old.get(r["id"]) or {}).get("count", 0)
        clean.append(r)
    a["rules"] = clean
    ig.save_auto(user, a)
    return {"ok": True, "rules": clean}


@api.get("/api/me/ig/online", include_in_schema=False)
async def ig_online(user=Depends(need_user)):
    """When followers are online (from Instagram), cached for a day."""
    cache = load_content(user, "online_followers.json", {})
    if cache.get("at") and time.time() - cache["at"] < 86400:
        return cache
    if "instagram" not in store.user_secrets(user).get("connections", {}):
        return {"hours": None, "reason": "Instagram API وصل نیست."}
    try:
        r = await run_in_threadpool(lambda: ig.online_followers(user))
    except ig.IGError as e:
        return {"hours": None, "reason": str(e)}
    out = {"at": time.time(), **(r or {"hours": None, "reason": "اینستاگرام این آمار رو برای پیج نداد (برای پیج‌های زیر ۱۰۰ فالوئر نمیاد)."})}
    if r:
        save_content(user, "online_followers.json", out, reshape=False)
    return out


@api.get("/api/me/calendar", include_in_schema=False)
def jalali_month(jy: int = 0, jm: int = 0, user=Depends(need_user)):
    """A Jalali month with Iran's occasions, for the board's calendar view (this month by default)."""
    today = datetime.now(timezone(timedelta(hours=3, minutes=30))).date()
    if not jy or not 1 <= jm <= 12:
        jy, jm, _ = calendar_fa.to_jalali(today)
    if not 1300 <= jy <= 1500:
        raise HTTPException(400, "سال نامعتبره")
    return {**calendar_fa.month(jy, jm), "today": today.isoformat()}


@api.get("/api/me/board", include_in_schema=False)
def get_board(user=Depends(need_user)):
    return {"items": load_content(user, "board.json", [])}


@api.post("/api/me/board", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_board(request: Request, user=Depends(need_editor)):
    """The whole production board: each card is a reel on its way from idea to published."""
    b = await body(request)
    items = b.get("items")
    if not isinstance(items, list) or len(items) > 300:
        raise HTTPException(400, "بُرد نامعتبره")
    clean, seen = [], set()
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not str(it.get("title") or "").strip():
            raise HTTPException(400, f"کارت {i + 1}: عنوان لازمه")
        if it.get("stage") not in BOARD_STAGES:
            raise HTTPException(400, f"کارت {i + 1}: مرحله نامعتبره")
        cid = str(it.get("id") or "")
        if not re.match(r"^[A-Za-z0-9_-]{1,40}$", cid) or cid in seen:
            cid = f"c{int(time.time() * 1000)}{i}"
        seen.add(cid)
        reel = str(it.get("reel") or "").strip()
        if reel and not REEL_URL.match(reel):
            raise HTTPException(400, f"کارت {i + 1}: لینک ریل باید لینک اینستاگرام باشه")
        due = it.get("due") or None
        if due and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(due)):
            raise HTTPException(400, f"کارت {i + 1}: تاریخ باید YYYY-MM-DD باشه")
        clean.append({"id": cid, "title": str(it["title"]).strip()[:200], "hook": str(it.get("hook") or "")[:500],
                      "notes": str(it.get("notes") or "")[:3000], "stage": it["stage"], "reel": reel, "due": due,
                      "created": int(it.get("created") or time.time()), "moved": int(it.get("moved") or time.time()),
                      "buffer": clean_sent(it.get("buffer"))})
    save_content(user, "board.json", clean, reshape=False)
    return {"ok": True, "items": clean}


def clean_sent(v):
    """What a card was sent to Buffer as ({kind, id, at, due_at}), kept as the server wrote it."""
    if not isinstance(v, dict) or v.get("kind") not in ("idea", "post", "draft"):
        return None
    return {"kind": v["kind"], "id": str(v.get("id") or "")[:64], "at": int(v.get("at") or 0), "due_at": str(v.get("due_at") or "")[:40] or None}


def buffer_key(user):
    k = store.user_secrets(user).get("connections", {}).get("buffer", {}).get("api_key")
    if not k:
        raise HTTPException(400, "اول Buffer رو تو تنظیمات وصل کن")
    return k


def buffer_call(fn, *args):
    try:
        return fn(*args)
    except publish.PublishError as e:
        raise HTTPException(400, str(e))


@api.get("/api/me/buffer/channels", include_in_schema=False)
async def buffer_channels(user=Depends(need_editor)):
    k = buffer_key(user)
    chans = [c for c in await run_in_threadpool(buffer_call, publish.channels, k) if not c["disconnected"]]
    if not chans:
        raise HTTPException(400, "تو Buffer هیچ اینستاگرامی وصل نیست (Channels ← Connect ← Instagram)")
    return {"channels": chans}


@api.post("/api/me/buffer/send", include_in_schema=False, dependencies=[Depends(same_site)])
async def buffer_send(request: Request, user=Depends(need_editor)):
    """Send a board card to Buffer: as an idea, or as a reel scheduled for a Tehran time (needs a video URL)."""
    b = await body(request)
    k = buffer_key(user)
    kind, chan = b.get("kind"), str(b.get("channel") or "")
    title, text = str(b.get("title") or "").strip()[:200], str(b.get("text") or "").strip()[:2200]
    chans = {c["id"]: c for c in await run_in_threadpool(buffer_call, publish.channels, k)}
    if chan not in chans:
        raise HTTPException(400, "کانال Buffer رو انتخاب کن")
    when = str(b.get("when") or "")  # "YYYY-MM-DDTHH:MM", Tehran time
    due_at = None
    if when:
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", when):
            raise HTTPException(400, "زمان نامعتبره")
        due_at = when + ":00+03:30"  # Iran has had no daylight saving since 2022
    if kind == "idea":
        if not title and not text:
            raise HTTPException(400, "عنوان یا متن لازمه")
        res = await run_in_threadpool(buffer_call, publish.send_idea, k, chans[chan]["organization"], title or text[:80], text, due_at)
    elif kind == "reel":
        video = str(b.get("video_url") or "").strip()
        if not re.match(r"^https://\S+$", video):
            raise HTTPException(400, "برای ریل، لینک مستقیم و عمومی ویدیو (https) لازمه")
        if not due_at or datetime.fromisoformat(due_at) <= datetime.now(timezone.utc):
            raise HTTPException(400, "زمان انتشار باید در آینده باشه")
        if not text:
            raise HTTPException(400, "کپشن لازمه")
        res = await run_in_threadpool(buffer_call, publish.schedule_reel, k, chan, text, video, due_at, bool(b.get("draft")), str(b.get("first_comment") or "")[:2200])
    else:
        raise HTTPException(400, "نوع ارسال نامعتبره")
    sent = {**res, "at": int(time.time()), "due_at": res.get("due_at") or due_at}
    card = str(b.get("card") or "")
    if card:  # remember it on the board card
        items = load_content(user, "board.json", [])
        for it in items:
            if it.get("id") == card:
                it["buffer"] = clean_sent(sent)
        save_content(user, "board.json", items, reshape=False)
    return {"ok": True, "sent": clean_sent(sent)}


def background(fn, user_id):
    if pipeline.lock_for(user_id).locked():
        return {"ok": False, "message": "یه کار دیگه برای همین حساب در جریانه؛ کمی بعد دوباره بزن."}
    threading.Thread(target=fn, args=(user_id,), daemon=True).start()
    return {"ok": True, "message": "شروع شد؛ چند ثانیه تا یکی دو دقیقه طول می‌کشه."}


@api.post("/api/me/refresh", include_in_schema=False, dependencies=[Depends(same_site)])
def refresh_now(user=Depends(need_editor)):
    return background(pipeline.refresh, user["id"])


@api.post("/api/me/content", include_in_schema=False, dependencies=[Depends(same_site)])
def content_now(user=Depends(need_editor)):
    if not pipeline.ai_config(user):
        raise HTTPException(400, "اول کلید هوش مصنوعی رو تنظیم کن (تو همین صفحه، یا از ادمین بخواه)")
    return background(pipeline.write_content, user["id"])


@api.post("/api/me/token", include_in_schema=False, dependencies=[Depends(same_site)])
def make_token(user=Depends(need_owner)):
    return {"token": store.new_api_token(user["id"])}


@api.post("/api/me/password", include_in_schema=False, dependencies=[Depends(same_site)])
async def change_password(request: Request, user=Depends(need_user)):
    b = await body(request)
    person = user["person"]  # the password is the signed-in person's, whatever page is open
    if not store.check_pw(b.get("current") or "", person["pw"]):
        raise HTTPException(400, "رمز فعلی اشتباهه")
    if len(b.get("new") or "") < 8:
        raise HTTPException(400, "رمز تازه باید دست‌کم ۸ حرف باشه")
    store.set_password(person["id"], b["new"])
    return login_response(person["id"], {"ok": True}, acting=user["id"] if user["id"] != person["id"] else None)  # stay on the open page


# ---------- AI: chat with the dashboard, a reel's critique, hook/caption writing ----------

def ai_call(fn):
    try:
        return fn()
    except ai.AIError as e:
        raise HTTPException(400, str(e))
    except ValueError:
        raise HTTPException(502, "جواب مدل قابل خوندن نبود؛ دوباره امتحان کن.")


def page_context(user):
    """What the AI knows about the page: its own description and the numbers, compact."""
    d = user_json(user)
    p = store.prefs(user)
    return {
        "page": p.get("page_name") or user["username"],
        "about": p.get("page_profile") or "",
        "last_7_days": analysis.overview(d, 7), "last_30_days": analysis.overview(d, 30), "all_time": analysis.overview(d, 0),
        "reels_newest_first": analysis.reels_list(d, 30),
        "daily_last_30": analysis.daily(d, 30),
        "best_posting_times": analysis.best_times(d, 5),
        "this_weeks_ideas": [{k: i.get(k) for k in ("priority", "title", "hook")} for i in d.get("ideas", [])],
    }


CHAT_SYSTEM = """You are the analytics assistant inside an Instagram creator's dashboard. Answer in Persian (conversational, clear),
from the page's numbers below only; say so when the data can't answer a question rather than guessing. Be concrete: name reels by
their caption start and date, give the numbers that support each point, and end with one practical next step when it helps.
"multiple_of_median" compares a reel with the page's median views; view_rate_3s_pct is the share who stayed past 3 seconds.
Keep answers short unless asked for detail. Dates are Tehran time.

The page's data (JSON):
{context}"""


@api.post("/api/me/chat", include_in_schema=False, dependencies=[Depends(same_site)])
async def chat(request: Request, user=Depends(need_editor)):
    b = await body(request)
    msgs = [m for m in (b.get("messages") or []) if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    msgs = [{"role": m["role"], "content": str(m.get("content") or "")[:4000]} for m in msgs][-12:]
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "سؤالی فرستاده نشد")
    system = CHAT_SYSTEM.format(context=json.dumps(page_context(user), ensure_ascii=False))
    answer = await run_in_threadpool(lambda: ai_call(lambda: ai.ask(user, system, msgs, max_tokens=4000)))
    return {"answer": answer}


@api.get("/api/me/reel", include_in_schema=False)
def my_reel(reel: str, user=Depends(need_user)):
    d = user_json(user)
    r = analysis.reel(d, reel)
    if not r:
        raise HTTPException(404, "این ریل تو داشبورد نیست")
    critiques = analysis.load(config.user_dir(user["id"]) / "content" / "critiques.json") or {}
    return {**r, "page_median_views": analysis.scored(d)[1], "critique": critiques.get(r["url"]),
            "topics": [{"id": t["id"], "label": t["label"]} for t in load_content(user, "topics.json", [])],
            "topic_manual": r["url"] in load_content(user, "reel_topics.json", {})}


@api.post("/api/me/reel-topic", include_in_schema=False, dependencies=[Depends(same_site)])
async def set_reel_topic(request: Request, user=Depends(need_editor)):
    """Fix one reel's topic by hand ("" goes back to guessing from the caption)."""
    b = await body(request)
    url, tid = str(b.get("reel") or ""), str(b.get("topic") or "")
    if not REEL_URL.match(url):
        raise HTTPException(400, "لینک ریل نامعتبره")
    if tid and tid != "other" and tid not in {t["id"] for t in load_content(user, "topics.json", [])}:
        raise HTTPException(400, "این موضوع وجود نداره")
    fixes = load_content(user, "reel_topics.json", {})
    if tid:
        fixes[url] = tid
    else:
        fixes.pop(url, None)
    save_content(user, "reel_topics.json", fixes)
    return {"ok": True}


CRITIQUE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "hook", "caption", "cover", "what_worked", "what_to_change", "next_reel"],
    "properties": {k: {"type": "string"} for k in ("verdict", "hook", "caption", "cover", "what_worked", "what_to_change", "next_reel")},
}


@api.post("/api/me/reel-critique", include_in_schema=False, dependencies=[Depends(same_site)])
async def reel_critique(request: Request, user=Depends(need_editor)):
    b = await body(request)
    d = user_json(user)
    r = analysis.reel(d, str(b.get("reel") or ""))
    if not r:
        raise HTTPException(404, "این ریل تو داشبورد نیست")
    path = config.user_dir(user["id"]) / "content" / "critiques.json"
    critiques = analysis.load(path) or {}
    if r["url"] in critiques and not b.get("fresh"):
        return critiques[r["url"]]
    ctx = page_context(user)
    system = ("You review one Instagram reel for its creator, in Persian (conversational). Use only the numbers given. "
              "verdict: one sentence on how it did against the page median and why. hook: what the first line/second does and how to "
              "sharpen it (give a rewritten hook). caption: same for the caption. cover: what the cover should show (you can't see it; "
              "reason from the caption and numbers). what_worked / what_to_change: 2-4 short points each. next_reel: one concrete idea "
              "for the next reel that builds on this one.\n\nPage: " + json.dumps({k: ctx[k] for k in ("page", "about", "last_30_days")}, ensure_ascii=False))
    reel_data = {k: r.get(k) for k in ("published", "caption", "views", "reach", "multiple_of_median", "view_rate_3s_pct", "avg_watch_s",
                                         "save_rate_pct", "shares_per_1k_reach", "follows", "likes", "comments", "view_curve")}
    out = await run_in_threadpool(lambda: ai_call(lambda: ai.ask(
        user, system, [{"role": "user", "content": "The reel:\n" + json.dumps(reel_data, ensure_ascii=False)}], schema=CRITIQUE_SCHEMA)))
    out["at"] = time.time()
    critiques[r["url"]] = out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(critiques, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


CAPTION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["hooks", "caption", "hashtags", "cta"],
    "properties": {"hooks": {"type": "array", "items": {"type": "string"}}, "caption": {"type": "string"},
                   "hashtags": {"type": "array", "items": {"type": "string"}}, "cta": {"type": "string"}},
}


@api.post("/api/me/write-caption", include_in_schema=False, dependencies=[Depends(same_site)])
async def write_caption(request: Request, user=Depends(need_editor)):
    b = await body(request)
    topic = "\n".join(str(b.get(k) or "")[:1500] for k in ("title", "hook", "beats", "text") if b.get(k)).strip()
    if not topic:
        raise HTTPException(400, "موضوع ریل رو بنویس")
    ctx = page_context(user)
    best = sorted(ctx["reels_newest_first"], key=lambda r: r.get("multiple_of_median") or 0, reverse=True)[:5]
    system = ("You write Instagram reel copy in Persian for this page, in its voice (conversational, natural, no clichés). "
              "hooks: 3 different first spoken lines, each under 12 words, built to stop the scroll (a surprise, a promise or a "
              "question). caption: the caption, its first 125 characters a complete hook on their own, with a 'save this' line when "
              "it fits, no hashtags inside. hashtags: at most 5, relevant, without #. cta: one closing line for the video. Follow any "
              "rule in the page description.\n\nPage: " + json.dumps({"page": ctx["page"], "about": ctx["about"]}, ensure_ascii=False) +
              "\nIts best reels so far: " + json.dumps([{k: r.get(k) for k in ("caption", "multiple_of_median", "view_rate_3s_pct")} for r in best], ensure_ascii=False))
    return await run_in_threadpool(lambda: ai_call(lambda: ai.ask(
        user, system, [{"role": "user", "content": "The reel:\n" + topic}], schema=CAPTION_SCHEMA, max_tokens=3000)))


# ---------- content studio: the 13 Persian agents and their tools ----------

@api.post("/api/me/studio/{agent}", include_in_schema=False, dependencies=[Depends(same_site)])
async def studio_run(agent: str, request: Request, user=Depends(need_user)):
    if agent not in agents.AGENTS:
        raise HTTPException(404)
    b = await body(request)
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    if not (agent == "human" and not inp.get("rewrite")) and user["role"] not in ("owner", "editor"):
        raise HTTPException(403, "دسترسی تو به این پیج فقط دیدنه")  # everything but the plain humanizer calls the AI
    try:
        return await run_in_threadpool(lambda: ai_call(lambda: agents.run(user, agent, inp)))
    except agents.InputError as e:
        raise HTTPException(400, str(e))


@api.get("/api/me/studio/history", include_in_schema=False)
def studio_history(user=Depends(need_user)):
    return {"items": [{k: h[k] for k in ("at", "agent", "input")} | {"i": i} for i, h in enumerate(agents.load(user, "studio_history.json", []))]}


@api.get("/api/me/studio/history/{i}", include_in_schema=False)
def studio_history_item(i: int, user=Depends(need_user)):
    h = agents.load(user, "studio_history.json", [])
    if not 0 <= i < len(h):
        raise HTTPException(404)
    return h[i]


@api.get("/api/me/studio/meta", include_in_schema=False)
def studio_meta(user=Depends(need_user)):
    return {"formulas": [{k: f[k] for k in ("id", "name", "template", "example", "on_screen", "best_for", "trap")} for f in fa_hooks.formulas()],
            "rubric": fa_text.data("rubric_fa.json")["items"], "voice": store.prefs(user).get("voice") or {},
            "agents": {k: v[0] for k, v in agents.AGENTS.items()}}


@api.post("/api/me/fa/{tool}", include_in_schema=False, dependencies=[Depends(same_site)])
async def fa_tool(tool: str, request: Request, user=Depends(need_user)):
    """The Persian tools on their own, no AI: hook scores, a beat sheet, the caption linter, the humanizer, a swipe ranking."""
    b = await body(request)
    w = agents.wpm(user)
    if tool == "hooks":
        return {"ranked": fa_hooks.rank([str(h) for h in (b.get("hooks") or [])][:20], w),
                "formulas": [fa_hooks.classify(h) for h in (b.get("hooks") or [])][:20]}
    if tool == "beats":
        return fa_beats.analyse(str(b.get("script") or "")[:8000], int(b.get("wpm") or w), float(b["target"]) if b.get("target") else None)
    if tool == "caption":
        return fa_caption.analyse(str(b.get("text") or "")[:5000], b.get("keywords") or [])
    if tool == "human":
        return fa_human.run(str(b.get("text") or "")[:12000], agents.casual(user))
    if tool == "swipe":
        return fa_viral.swipe(fa_viral.read_rows(b.get("rows")))
    raise HTTPException(404)


VOICE_KEYS = ("who", "handle", "audience", "sells", "samples", "on_camera", "words_used", "words_never", "emoji", "face", "wpm",
              "positions", "off_limits", "proof", "keyword", "keyword_sends", "link", "register")


@api.post("/api/me/voice", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_voice(request: Request, user=Depends(need_editor)):
    b = await body(request)
    v = {k: str(b.get(k) or "").strip()[:3000] for k in VOICE_KEYS}
    v["register"] = "formal" if v["register"] == "formal" else "casual"
    if v["wpm"] and not v["wpm"].isdigit():
        raise HTTPException(400, "سرعت گفتار باید عدد باشه (کلمه در دقیقه)")
    p = store.prefs(user)
    p["voice"] = v
    store.set_prefs(user["id"], p)
    return {"ok": True}


@api.post("/api/me/voice/infer", include_in_schema=False, dependencies=[Depends(same_site)])
async def infer_voice(user=Depends(need_editor)):
    try:
        return await run_in_threadpool(lambda: ai_call(lambda: agents.infer_voice(user)))
    except agents.InputError as e:
        raise HTTPException(400, str(e))


# ---------- comments ----------

def comments_data(user):
    """raw/ig_comments.json (from the Instagram connection), each comment marked answered when the page replied."""
    raw = analysis.load(config.user_dir(user["id"]) / "raw" / "ig_comments.json")
    if not raw:
        return {"fetched_at": None, "error": "none", "posts": []}
    me = (raw.get("username") or "").lower()
    posts = []
    for p in raw.get("posts", []):
        cs = [{**c, "answered": any((r.get("user") or "").lower() == me for r in c.get("replies", []))}
              for c in p.get("comments", []) if (c.get("user") or "").lower() != me]
        if cs:
            posts.append({**p, "comments": cs, "unanswered": sum(not c["answered"] for c in cs)})
    return {"fetched_at": raw.get("fetched_at"), "error": raw.get("error"), "username": raw.get("username"), "posts": posts}


@api.get("/api/me/comments", include_in_schema=False)
def my_comments(user=Depends(need_user)):
    d = comments_data(user)
    d["analysis"] = load_content(user, "comment_insights.json", {}) or None
    return d


COMMENTS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "mood", "themes", "questions", "ideas"],
    "properties": {
        "summary": {"type": "string"}, "mood": {"type": "string"},
        "themes": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["theme", "detail"],
                                              "properties": {"theme": {"type": "string"}, "detail": {"type": "string"}}}},
        "questions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["question", "reel_url", "reply"],
                                                 "properties": {"question": {"type": "string"}, "reel_url": {"type": "string"}, "reply": {"type": "string"}}}},
        "ideas": {"type": "array", "items": {"type": "string"}},
    },
}


@api.post("/api/me/comments/analyze", include_in_schema=False, dependencies=[Depends(same_site)])
async def analyze_comments(user=Depends(need_editor)):
    d = comments_data(user)
    if not d["posts"]:
        raise HTTPException(400, "هنوز کامنتی گرفته نشده" if d["error"] != "permission" else "توکن اینستاگرام اجازهٔ خوندن کامنت‌ها رو نداره")
    page = store.prefs(user)
    posts = [{"reel_url": p["url"], "caption": p["caption"][:200],
              "comments": [{"text": c["text"][:400], "likes": c.get("likes"), "answered": c["answered"]} for c in p["comments"][:40]]}
             for p in d["posts"]]
    system = ("You read the comments on an Instagram creator's recent reels and report in Persian (conversational, clear). summary: "
              "2-3 sentences on what the audience is saying. mood: one short line on the overall tone. themes: up to 5 recurring "
              "topics, each with a sentence of detail. questions: up to 8 real questions people asked, prefer unanswered ones, each "
              "with the reel it was on and a short friendly reply in the page's voice. ideas: up to 5 reel ideas the comments ask "
              "for. Use only what is in the comments; don't invent.\n\nPage: " +
              json.dumps({"page": page.get("page_name"), "about": page.get("page_profile")}, ensure_ascii=False))
    out = await run_in_threadpool(lambda: ai_call(lambda: ai.ask(
        user, system, [{"role": "user", "content": json.dumps(posts, ensure_ascii=False)}], schema=COMMENTS_SCHEMA, max_tokens=4000)))
    out = {**out, "created": int(time.time()), "comments": sum(len(p["comments"]) for p in d["posts"])}
    save_content(user, "comment_insights.json", out, reshape=False)
    return out


# ---------- admin ----------

@api.get("/api/admin", include_in_schema=False)
def admin_state(admin=Depends(need_admin)):
    ai = store.setting("ai", {}) or {}
    return {
        "settings": {"ai_provider": ai.get("provider", "anthropic"), "ai_model": ai.get("model", ""), "ai_key": mask(ai.get("key")) if ai.get("key") else "",
                     "ai_base_url": ai.get("base_url", ""),
                     "telegram_bot": mask(store.setting("telegram_bot")) if store.setting("telegram_bot") else "",
                     "allow_signup": bool(store.setting("allow_signup", False)), "public_url": store.setting("public_url") or config.PUBLIC_URL,
                     "max_pages": max_pages()},
        "ops": {**(store.setting("ops", {}) or {}), "backups": ops.describe()},
        "billing": {**{k: v for k, v in billing.config().items() if k != "merchant"}, "merchant": mask(billing.config()["merchant"])},
        "payments": [{k: r[k] for k in ("authority", "username", "plan_id", "amount", "status", "ref_id", "created_at")} for r in store.payments()],
        "providers": {k: v["label"] for k, v in AI.PROVIDERS.items()},
        "users": [{"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"]), "created_at": u["created_at"],
                   "kind": u["kind"], "owner_id": u["owner_id"], "page_name": store.prefs(u).get("page_name") or "",
                   "connections": sorted(store.user_secrets(u).get("connections", {}).keys()),
                   "status": {k: v for k, v in store.status(u).items() if not k.endswith("_log")}} for u in store.users()],
    }


@api.post("/api/admin/settings", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_settings(request: Request, admin=Depends(need_admin)):
    b = await body(request)
    ai = store.setting("ai", {}) or {}
    if "ai_provider" in b:
        if b["ai_provider"] not in AI.PROVIDERS:
            raise HTTPException(400, "ارائه‌دهندهٔ نامعتبر")
        ai["provider"] = b["ai_provider"]
    if "ai_base_url" in b:
        url = str(b["ai_base_url"] or "").strip()
        try:
            ai["base_url"] = AI.check_url(url, True) if url else ""
        except AI.AIError as e:
            raise HTTPException(400, str(e))
    if "ai_model" in b:
        ai["model"] = str(b["ai_model"] or "").strip()
    if b.get("ai_key") is not None and not str(b["ai_key"]).startswith("•"):
        ai["key"] = str(b["ai_key"]).strip()
    store.set_setting("ai", ai)
    if b.get("telegram_bot") is not None and not str(b["telegram_bot"]).startswith("•"):
        store.set_setting("telegram_bot", str(b["telegram_bot"]).strip())
    if "allow_signup" in b:
        store.set_setting("allow_signup", bool(b["allow_signup"]))
    if "max_pages" in b:
        try:
            n = int(b["max_pages"])
        except (TypeError, ValueError):
            raise HTTPException(400, "تعداد پیج باید عدد باشه")
        store.set_setting("max_pages", max(1, min(n, 100)))
    if "public_url" in b:
        url = str(b["public_url"] or "").strip().rstrip("/")
        if url and not re.match(r"^https?://[^\s/]+", url):
            raise HTTPException(400, "آدرس باید با http:// یا https:// شروع بشه")
        store.set_setting("public_url", url)
    return {"ok": True}


@api.post("/api/admin/users", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_add_user(request: Request, admin=Depends(need_admin)):
    b = await body(request)
    check_new_login(b.get("username"), b.get("password"))
    return {"ok": True, "id": new_user(b["username"], b["password"], bool(b.get("is_admin")))}


@api.post("/api/admin/users/{uid}/password", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_reset_password(uid: int, request: Request, admin=Depends(need_admin)):
    b = await body(request)
    if len(b.get("password") or "") < 8:
        raise HTTPException(400, "رمز باید دست‌کم ۸ حرف باشه")
    u = store.get_user(uid)
    if not u or u["kind"] != "person":
        raise HTTPException(400, "این یه پیج اضافه‌ست و رمز نداره")
    store.set_password(uid, b["password"])
    return {"ok": True}


@api.delete("/api/admin/users/{uid}", include_in_schema=False, dependencies=[Depends(same_site)])
def admin_delete_user(uid: int, admin=Depends(need_admin)):
    if uid == admin["person"]["id"]:
        raise HTTPException(400, "نمی‌تونی حساب خودت رو پاک کنی")
    store.delete_user(uid)  # the user's folder stays on disk, so a mistake can be undone by hand
    return {"ok": True}


@api.post("/api/admin/backup", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_backup(admin=Depends(need_admin)):
    ok, msg = await run_in_threadpool(ops.run_backup)
    return {"ok": ok, "message": ("ساخته شد: " + msg) if ok else msg}


@api.get("/api/admin/backups/{name}", include_in_schema=False)
def admin_backup_file(name: str, admin=Depends(need_admin)):
    p = next((b for b in ops.backups() if b.name == name), None)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, media_type="application/gzip", filename=p.name, headers={"Cache-Control": "no-store"})


@api.post("/api/admin/billing", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_billing(request: Request, admin=Depends(need_admin)):
    b = await body(request)
    c = store.setting("billing", {}) or {}
    if "enabled" in b:
        c["enabled"] = bool(b["enabled"])
    if "sandbox" in b:
        c["sandbox"] = bool(b["sandbox"])
    m = str(b.get("merchant") or "").strip()
    if m and not m.startswith("•"):
        if not re.match(r"^[0-9a-fA-F-]{36}$", m):
            raise HTTPException(400, "مرچنت کد زرین‌پال ۳۶ کاراکتره")
        c["merchant"] = m
    if "free_pages" in b:
        c["free_pages"] = max(1, min(int(b["free_pages"] or 1), 50))
    if "plans" in b:
        plans, seen = [], set()
        for i, x in enumerate(b["plans"] or []):
            try:
                plan = {"id": re.sub(r"[^a-z0-9-]", "", str(x.get("id") or "").lower())[:30] or f"plan-{i + 1}", "name": str(x["name"]).strip()[:60],
                        "price": int(x["price"]), "days": int(x["days"]), "max_pages": int(x["max_pages"]), "ai": bool(x.get("ai"))}
            except (KeyError, TypeError, ValueError):
                raise HTTPException(400, f"پلن {i + 1}: اسم، قیمت (تومان)، روز و تعداد پیج لازمه")
            if plan["id"] in seen or not plan["name"] or plan["price"] < 1000 or plan["days"] < 1 or plan["max_pages"] < 1:
                raise HTTPException(400, f"پلن {i + 1}: نامعتبره (قیمت دست‌کم ۱۰۰۰ تومان)")
            seen.add(plan["id"])
            plans.append(plan)
        c["plans"] = plans
    if c.get("enabled") and not c.get("merchant"):
        raise HTTPException(400, "برای روشن کردن اشتراک، اول مرچنت کد زرین‌پال رو بذار")
    store.set_setting("billing", c)
    return {"ok": True}


# ---------- subscriptions (users) ----------

def billing_view(person):
    c = billing.config()
    if not c["enabled"]:
        return {"enabled": False}
    return {"enabled": True, "plan": billing.plan_for(person), "plans": [x for x in c["plans"] if x.get("price")]}


@api.post("/api/billing/checkout", include_in_schema=False, dependencies=[Depends(same_site)])
async def checkout(request: Request, user=Depends(need_user)):
    b = await body(request)
    base = pipeline.public_url() or str(request.base_url).rstrip("/")
    try:
        url = await run_in_threadpool(billing.start, user["person"], str(b.get("plan") or ""), base + "/billing/callback")
    except billing.PayError as e:
        raise HTTPException(400, str(e))
    return {"url": url}


@api.get("/billing/callback", include_in_schema=False)
async def billing_callback(Authority: str = "", Status: str = ""):
    try:
        ok, msg = await run_in_threadpool(billing.finish, Authority, Status)
    except billing.PayError as e:
        ok, msg = False, str(e)
    return RedirectResponse("/settings?" + urllib.parse.urlencode({"billing": "ok" if ok else "fail", "msg": msg}) + "#billing-card")


# ---------- onboarding ----------

def onboarding(user, p, s):
    """The first steps for a new page, each checked against what's really there."""
    st = store.status(user)
    steps = [
        {"id": "profile", "label": "معرفی پیج برای هوش مصنوعی", "done": bool(p.get("page_profile")), "href": "/settings#page-card"},
        {"id": "source", "label": "وصل کردن یه منبع داده (Instagram API، Buffer یا Metricool)", "done": bool(s.get("connections")), "href": "/settings#conns-card"},
        {"id": "data", "label": "گرفتن اولین داده", "done": bool(st.get("refresh_ok")), "href": "/settings#status"},
        {"id": "goals", "label": "تعیین هدف‌ها", "done": bool(p.get("goals_set")), "href": "/settings#goals-card"},
        {"id": "ai", "label": "کلید هوش مصنوعی (برای ایده‌ها و دستیار)", "done": pipeline.ai_config(user) is not None, "href": "/settings#ai-card"},
        {"id": "telegram", "label": "هشدارها تو تلگرام (اختیاری)", "done": bool(p.get("telegram_chat")), "href": "/settings#tg-card", "optional": True},
    ]
    return {"steps": steps, "hidden": bool(p.get("onboarding_hidden")), "done": all(x["done"] for x in steps if not x.get("optional"))}


@api.post("/api/me/onboarding", include_in_schema=False, dependencies=[Depends(same_site)])
async def hide_onboarding(request: Request, user=Depends(need_owner)):
    b = await body(request)
    p = store.prefs(user)
    p["onboarding_hidden"] = bool(b.get("hidden", True))
    store.set_prefs(user["id"], p)
    return {"ok": True}


# ---------- read-only API (ChatGPT Actions, scripts) ----------

def user_json(user):
    return analysis.load(config.user_dir(user["id"]) / "data" / "data.json")


@api.get("/api/v1/overview", summary="Headline numbers", operation_id="getOverview")
def v1_overview(days: int = 30, user=Depends(api_user)):
    """Followers and net change, reel count and views, 3-second view rate, save rate, shares per 1,000 reached,
    top and weakest reels and goal progress for the last `days` days (0 = all)."""
    return analysis.overview(user_json(user), days)


@api.get("/api/v1/reels", summary="List reels", operation_id="listReels")
def v1_reels(limit: int = 20, sort: str = "published", days: int = 0, user=Depends(api_user)):
    """Reels with their numbers. sort: published, views, multiple, view_rate, follows or saves."""
    return {"reels": analysis.reels_list(user_json(user), limit, sort, days)}


@api.get("/api/v1/reel", summary="One reel", operation_id="getReel")
def v1_reel(reel: str, user=Depends(api_user)):
    """One reel's numbers, caption and view curve. `reel` is its Instagram URL or shortcode."""
    r = analysis.reel(user_json(user), reel)
    if not r:
        raise HTTPException(404, "No reel with that URL or shortcode")
    return r


@api.get("/api/v1/daily", summary="Daily account numbers", operation_id="getDailyStats")
def v1_daily(days: int = 30, user=Depends(api_user)):
    return {"days": analysis.daily(user_json(user), days)}


@api.get("/api/v1/content", summary="This week's content plan", operation_id="getContentPlan")
def v1_content(user=Depends(api_user)):
    """AI-written reel ideas, insights with actions, benchmark pages and A/B experiments."""
    return analysis.content(user_json(user))


@api.get("/api/v1/best-times", summary="Best posting times", operation_id="getBestTimes")
def v1_best(top: int = 5, user=Depends(api_user)):
    return {"best_times": analysis.best_times(user_json(user), top)}


@api.get("/openapi.json", include_in_schema=False)
def openapi_for_actions():
    """The spec ChatGPT's Custom GPT Actions import, with this server's public address filled in."""
    spec = api.openapi()
    base = pipeline.public_url()
    if base:
        spec = {**spec, "servers": [{"url": base}]}
    spec.setdefault("components", {})["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
    spec["security"] = [{"bearer": []}]
    return JSONResponse(spec)



# ---------- one ASGI app: /mcp goes to the MCP server, everything else to the panel ----------

MCP_PATH = re.compile(r"^/mcp(?:/u/([A-Za-z0-9_-]+))?/?$")


async def app(scope, receive, send):
    if scope["type"] == "http" and scope["path"].startswith("/mcp"):
        m = MCP_PATH.match(scope["path"])
        if not m:
            await Response(status_code=404)(scope, receive, send)
            return
        headers = [(k, v) for k, v in scope["headers"] if k != b"x-sajadai-token"]
        if m[1]:
            headers.append((b"x-sajadai-token", m[1].encode()))
        await mcp_http({**scope, "path": "/", "raw_path": b"/", "root_path": "", "headers": headers}, receive, send)
        return
    await api(scope, receive, send)
