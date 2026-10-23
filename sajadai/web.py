"""The web panel: sign-in, each user's dashboard, their settings (connections, AI, Telegram, goals,
Claude/ChatGPT token), the admin page, a read-only JSON API for ChatGPT Actions, and the MCP endpoint.

Run: uvicorn sajadai.web:app --host 0.0.0.0 --port 8000   (or `python -m sajadai serve`, or docker compose up)
"""
import contextlib, json, re, threading, time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from mcp.server.transport_security import TransportSecuritySettings

from . import analysis, config, mcp_server, pipeline, store

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
    return store.session_user(request.cookies.get(COOKIE))


def need_user(request: Request):
    u = current_user(request)
    if not u:
        raise HTTPException(401, "وارد نشدی")
    return u


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


def login_response(user_id, body):
    r = JSONResponse(body)
    r.set_cookie(COOKIE, store.new_session(user_id), max_age=config.SESSION_DAYS * 86400, httponly=True,
                 samesite="lax", secure=config.SECURE_COOKIES)
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
    if store.find_user(username):
        raise HTTPException(400, "این نام کاربری گرفته شده")


def new_user(username, password, is_admin=False):
    uid = store.create_user(username, password, is_admin, prefs={"page_name": username})
    pipeline.ensure_user_dir(uid)
    return uid


# ---------- pages ----------

def page(name):
    return HTMLResponse((config.PANEL / name).read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


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
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


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
    return r


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
    conns = s.get("connections", {})
    panel_ai = store.setting("ai", {}) or {}
    base = pipeline.public_url()
    return {
        "username": user["username"], "is_admin": bool(user["is_admin"]),
        "prefs": {k: p.get(k, "") for k in ("page_name", "page_profile", "telegram_chat", "ai_provider", "ai_model")},
        "connections": {name: {"label": spec["label"], "connected": name in conns,
                               "fields": {f: {"label": lbl, "value": (mask(conns[name].get(f)) if f in ("token", "api_key") else conns[name].get(f, "")) if name in conns else ""}
                                          for f, lbl in spec["fields"].items()}}
                        for name, spec in pipeline.CONNECTIONS.items()},
        "ai": {"own_key": mask(s.get("ai_key")) if s.get("ai_key") else "", "panel_provider": panel_ai.get("provider") if panel_ai.get("key") else None,
               "providers": pipeline.AI_PROVIDERS},
        "telegram_ready": bool(store.setting("telegram_bot")),
        "has_token": bool(user["api_token"]),
        "urls": {"base": base, "mcp": (base or "") + "/mcp", "api": (base or "") + "/api/v1", "openapi": (base or "") + "/openapi.json"},
        "goals": analysis.load(config.user_dir(user["id"]) / "content" / "goals.json") or [],
        "status": {k: v for k, v in store.status(user).items()},
    }


@api.post("/api/me/prefs", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_prefs(request: Request, user=Depends(need_user)):
    b = await body(request)
    p = store.prefs(user)
    for k in ("page_name", "page_profile", "telegram_chat", "ai_provider", "ai_model"):
        if k in b:
            p[k] = str(b[k] or "").strip()[:4000]
    if p.get("ai_provider") and p["ai_provider"] not in pipeline.AI_PROVIDERS:
        raise HTTPException(400, "ارائه‌دهندهٔ هوش مصنوعی نامعتبر")
    if p.get("telegram_chat") and not re.match(r"^-?\d{3,20}$", p["telegram_chat"]):
        raise HTTPException(400, "chat id تلگرام باید عدد باشه")
    store.set_prefs(user["id"], p)
    return {"ok": True}


@api.post("/api/me/connections/{name}", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_connection(name: str, request: Request, user=Depends(need_user)):
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
def remove_connection(name: str, user=Depends(need_user)):
    s = store.user_secrets(user)
    s.get("connections", {}).pop(name, None)
    store.set_secrets(user["id"], s)
    return {"ok": True}


@api.post("/api/me/ai_key", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_ai_key(request: Request, user=Depends(need_user)):
    b = await body(request)
    s = store.user_secrets(user)
    key = str(b.get("key") or "").strip()
    if key:
        s["ai_key"] = key
    else:
        s.pop("ai_key", None)
    store.set_secrets(user["id"], s)
    return {"ok": True}


@api.post("/api/me/goals", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_goals(request: Request, user=Depends(need_user)):
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
    d = pipeline.ensure_user_dir(user["id"])
    (d / "content" / "goals.json").write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    pipeline.run_script(user["id"], "shape.py", {})
    return {"ok": True}


def background(fn, user_id):
    if pipeline.lock_for(user_id).locked():
        return {"ok": False, "message": "یه کار دیگه برای همین حساب در جریانه؛ کمی بعد دوباره بزن."}
    threading.Thread(target=fn, args=(user_id,), daemon=True).start()
    return {"ok": True, "message": "شروع شد؛ چند ثانیه تا یکی دو دقیقه طول می‌کشه."}


@api.post("/api/me/refresh", include_in_schema=False, dependencies=[Depends(same_site)])
def refresh_now(user=Depends(need_user)):
    return background(pipeline.refresh, user["id"])


@api.post("/api/me/content", include_in_schema=False, dependencies=[Depends(same_site)])
def content_now(user=Depends(need_user)):
    if not pipeline.ai_config(user):
        raise HTTPException(400, "اول کلید هوش مصنوعی رو تنظیم کن (تو همین صفحه، یا از ادمین بخواه)")
    return background(pipeline.write_content, user["id"])


@api.post("/api/me/token", include_in_schema=False, dependencies=[Depends(same_site)])
def make_token(user=Depends(need_user)):
    return {"token": store.new_api_token(user["id"])}


@api.post("/api/me/password", include_in_schema=False, dependencies=[Depends(same_site)])
async def change_password(request: Request, user=Depends(need_user)):
    b = await body(request)
    if not store.check_pw(b.get("current") or "", user["pw"]):
        raise HTTPException(400, "رمز فعلی اشتباهه")
    if len(b.get("new") or "") < 8:
        raise HTTPException(400, "رمز تازه باید دست‌کم ۸ حرف باشه")
    store.set_password(user["id"], b["new"])
    return login_response(user["id"], {"ok": True})


# ---------- admin ----------

@api.get("/api/admin", include_in_schema=False)
def admin_state(admin=Depends(need_admin)):
    ai = store.setting("ai", {}) or {}
    return {
        "settings": {"ai_provider": ai.get("provider", "anthropic"), "ai_model": ai.get("model", ""), "ai_key": mask(ai.get("key")) if ai.get("key") else "",
                     "telegram_bot": mask(store.setting("telegram_bot")) if store.setting("telegram_bot") else "",
                     "allow_signup": bool(store.setting("allow_signup", False)), "public_url": store.setting("public_url") or config.PUBLIC_URL},
        "providers": pipeline.AI_PROVIDERS,
        "users": [{"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"]), "created_at": u["created_at"],
                   "connections": sorted(store.user_secrets(u).get("connections", {}).keys()),
                   "status": {k: v for k, v in store.status(u).items() if not k.endswith("_log")}} for u in store.users()],
    }


@api.post("/api/admin/settings", include_in_schema=False, dependencies=[Depends(same_site)])
async def admin_settings(request: Request, admin=Depends(need_admin)):
    b = await body(request)
    ai = store.setting("ai", {}) or {}
    if "ai_provider" in b:
        if b["ai_provider"] not in pipeline.AI_PROVIDERS:
            raise HTTPException(400, "ارائه‌دهندهٔ نامعتبر")
        ai["provider"] = b["ai_provider"]
    if "ai_model" in b:
        ai["model"] = str(b["ai_model"] or "").strip()
    if b.get("ai_key") is not None and not str(b["ai_key"]).startswith("•"):
        ai["key"] = str(b["ai_key"]).strip()
    store.set_setting("ai", ai)
    if b.get("telegram_bot") is not None and not str(b["telegram_bot"]).startswith("•"):
        store.set_setting("telegram_bot", str(b["telegram_bot"]).strip())
    if "allow_signup" in b:
        store.set_setting("allow_signup", bool(b["allow_signup"]))
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
    store.set_password(uid, b["password"])
    return {"ok": True}


@api.delete("/api/admin/users/{uid}", include_in_schema=False, dependencies=[Depends(same_site)])
def admin_delete_user(uid: int, admin=Depends(need_admin)):
    if uid == admin["id"]:
        raise HTTPException(400, "نمی‌تونی حساب خودت رو پاک کنی")
    store.delete_user(uid)  # the user's folder stays on disk, so a mistake can be undone by hand
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
