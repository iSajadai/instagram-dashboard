"""HTTP routes for the connections page (sajadai/providers): list the sources with their state, connect
and test, disconnect, upload exports, read Insights screenshots, the manual form, the coverage matrix, and
Instagram's webhooks. Mounted by web.py."""
import base64, hashlib, hmac, json, re, secrets, threading, time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from . import analysis, config, pipeline, store
from .providers import files, get, read_norm, registry, write_norm
from .providers.coverage import matrix

router = APIRouter()
REEL_URL = re.compile(r"^https://(www\.)?instagram\.com/(reel|reels|p|tv)/([A-Za-z0-9_-]+)/?")
MAX_UPLOAD = 25 * 1024 * 1024


def deps():
    from .web import body, mask, need_editor, need_owner, need_user, same_site
    return body, mask, need_editor, need_owner, need_user, same_site


body, mask, need_editor, need_owner, need_user, same_site = deps()


def user_data(user):
    return analysis.load(config.user_dir(user["id"]) / "data" / "data.json") or {}


def state_of(user, pid):
    st = (store.status(user).get("providers") or {}).get(pid) or {}
    return {"last_at": st.get("at"), "ok": st.get("ok"), "message": st.get("message", ""), "account": st.get("account", ""),
            "missing": st.get("missing", [])}


@router.get("/api/me/providers", include_in_schema=False)
def list_providers(user=Depends(need_user)):
    conns = store.user_secrets(user).get("connections", {})
    owner = user["role"] == "owner"
    out = []
    for pid, p in registry().items():
        c = p.card()
        vals = conns.get(pid) or {}
        c["connected"] = pid in conns
        c["values"] = {f: (mask(vals.get(f)) if f in c["secret_fields"] else vals.get(f, "")) for f in p.fields} if owner and vals else {}
        c["state"] = state_of(user, pid)
        if pid in ("export_csv", "dyi_json", "screenshot", "manual"):
            n = read_norm(user["id"], pid)
            c["connected"] = bool(n)
            c["state"] = {**c["state"], "last_at": n.get("fetched_at"), "ok": True if n else None,
                          "message": f"{len(n.get('reels', []))} ریل" + (f"، {len(n.get('posts', []))} پست" if n.get("posts") else "") if n else ""}
        if pid == "webhooks" and vals:
            c["callback"] = (pipeline.public_url() or "") + "/webhooks/instagram"
            c["verify_token"] = vals.get("verify_token", "")
        if pid == "routine":
            try:
                c["deploy_key"] = (config.DATA_DIR / "keys" / "data_repo.pub").read_text().strip()
            except OSError:
                c["deploy_key"] = ""
        if p.kind == "scraper" and not pipeline.scrapers_allowed():
            c["status"], c["soon_reason"] = "off", "ادمین پنل این دسته رو خاموش کرده."
        out.append(c)
    d = user_data(user)
    return {"providers": out, "coverage": matrix(user, conns, d, pipeline.scrapers_allowed()),
            "discrepancies": (analysis.load(config.user_dir(user["id"]) / "raw" / "discrepancies.json") or [])[-20:] if isinstance(
                analysis.load(config.user_dir(user["id"]) / "raw" / "discrepancies.json"), list) else []}


def save_state(user, pid, res, ok):
    st = dict(store.status(user).get("providers") or {})
    st[pid] = {**(st.get(pid) or {}), "tested_at": time.time(), "ok": ok, "message": res.get("message_fa", ""),
               "account": res.get("account_name", ""), "missing": res.get("missing_permissions", []), **({"ig_user_id": res["ig_user_id"]} if res.get("ig_user_id") else {})}
    store.update_status(user["id"], providers=st)


@router.post("/api/me/providers/{pid}", include_in_schema=False, dependencies=[Depends(same_site)])
async def connect(pid: str, request: Request, user=Depends(need_owner)):
    """Test the credentials and save them when they work (or when asked to anyway)."""
    p = get(pid)
    if not p or p.status != "ready" or p.auth_type in ("upload", "none"):
        raise HTTPException(404, "این منبع اتصال نمی‌خواد یا فعلاً در دسترس نیست")
    if p.kind == "scraper" and not pipeline.scrapers_allowed():
        raise HTTPException(400, "ادمین پنل اسکرپرها رو خاموش کرده")
    b = await body(request)
    s = store.user_secrets(user)
    old = s.get("connections", {}).get(pid, {})
    from .accounts import limits
    if not old and len(s.get("connections", {})) >= limits()["connections"]:
        raise HTTPException(400, f"حداکثر {limits()['connections']} اتصال برای هر پیج؛ یکی رو قطع کن.")
    vals = {}
    for f in p.fields:
        v = str(b.get(f) or "").strip()
        vals[f] = old.get(f, "") if (not v or v.startswith("•")) else v
    if pid == "routine" and not vals.get("branch"):
        vals["branch"] = "main"
    if not all(vals.get(f) for f in p.fields):
        raise HTTPException(400, "همهٔ فیلدها لازمه")
    res = await run_in_threadpool(lambda: p.test_connection(vals))
    if res.get("new_creds"):
        vals = res.pop("new_creds")
    if pid == "webhooks":
        vals["verify_token"] = old.get("verify_token") or secrets.token_urlsafe(18)
        res["message_fa"] += subscribe_webhooks(user)
    save_state(user, pid, res, res["ok"])
    if not res["ok"] and not b.get("force"):
        return res
    s.setdefault("connections", {})[pid] = vals
    store.set_secrets(user["id"], s)
    if p.script or pid in pipeline.SCRAPERS:
        from . import jobs
        jobs.start()
        jobs.enqueue(user["id"], "refresh", manual=True)
    return {**res, "saved": True}


@router.post("/api/me/providers/{pid}/test", include_in_schema=False, dependencies=[Depends(same_site)])
async def retest(pid: str, user=Depends(need_owner)):
    p = get(pid)
    vals = store.user_secrets(user).get("connections", {}).get(pid)
    if not p or not vals:
        raise HTTPException(404, "این منبع وصل نیست")
    res = await run_in_threadpool(lambda: p.test_connection(vals))
    res.pop("new_creds", None)
    save_state(user, pid, res, res["ok"])
    return res


@router.delete("/api/me/providers/{pid}", include_in_schema=False, dependencies=[Depends(same_site)])
def disconnect(pid: str, user=Depends(need_owner)):
    """Remove a source. Its numbers stay in the history; the next sync uses the remaining sources."""
    s = store.user_secrets(user)
    s.get("connections", {}).pop(pid, None)
    store.set_secrets(user["id"], s)
    (config.user_dir(user["id"]) / "raw" / "norm" / f"{pid}.json").unlink(missing_ok=True)
    pipeline.run_script(user["id"], "shape.py", {})
    return {"ok": True}


def merge_records(old, new, key="shortcode"):
    by = {r.get(key): r for r in old if r.get(key)}
    for r in new:
        k = r.get(key)
        if k:
            by[k] = {**by.get(k, {}), **{a: b for a, b in r.items() if b not in (None, "")}}
    return list(by.values())


async def read_body(request):
    data, size = b"", 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD:
            raise HTTPException(413, "فایل بزرگ‌تر از ۲۵ مگابایته")
        data += chunk
    if not data:
        raise HTTPException(400, "فایلی نرسید")
    return data


@router.post("/api/me/providers/{pid}/upload", include_in_schema=False, dependencies=[Depends(same_site)])
async def upload(pid: str, request: Request, name: str = "file", user=Depends(need_editor)):
    """An export file: Meta Business Suite / Professional Dashboard (CSV, XLSX) or Download your information (JSON, ZIP)."""
    if pid not in ("export_csv", "dyi_json"):
        raise HTTPException(404)
    data = await read_body(request)
    try:
        parsed = await run_in_threadpool(lambda: (files.parse_export if pid == "export_csv" else files.parse_dyi)(data, name))
    except (ValueError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e) if isinstance(e, ValueError) else "فایل خونده نشد")
    old = read_norm(user["id"], pid)
    if pid == "dyi_json":
        # no permalinks in this export: each item keyed by its timestamp so it shows up with its caption and date
        reels = [{"shortcode": "dyi" + re.sub(r"\D", "", r["published"] or "")[:14], "url": "dyi://" + (r["published"] or ""), "caption": r["caption"],
                  "published": r["published"]} for r in parsed["reels"] if r.get("published")]
        days = old.get("account_days", [])
        if parsed.get("followers") is not None:
            from datetime import datetime, timedelta, timezone
            today = datetime.now(timezone(timedelta(hours=3, minutes=30))).date().isoformat()
            days = [d for d in days if d["day"] != today] + [{"day": today, "followers": parsed["followers"]}]
        payload = {"reels": merge_records(old.get("reels", []), reels), "posts": parsed["posts"], "account_days": days}
        msg = f"{len(reels)} ریل و {len(parsed['posts'])} پست" + (f"، {parsed['followers']} فالوئر" if parsed.get("followers") is not None else "") + " خونده شد. (این فایل آمار بازدید نداره.)"
    else:
        payload = {"reels": merge_records(old.get("reels", []), parsed["reels"]), "posts": merge_records(old.get("posts", []), parsed["posts"])}
        msg = f"{len(parsed['reels'])} ریل و {len(parsed['posts'])} پست خونده شد."
    write_norm(user["id"], pid, payload, raw={"file": name, "size": len(data)})
    ok, out = await run_in_threadpool(lambda: pipeline.run_script(user["id"], "shape.py", {}))
    if ok:
        store.update_status(user["id"], last_ok_at=time.time())
    return {"ok": ok, "message": msg if ok else out[-300:]}


@router.post("/api/me/providers/screenshot/read", include_in_schema=False, dependencies=[Depends(same_site)])
async def read_screenshot(request: Request, user=Depends(need_editor)):
    """Up to four Insights screenshots (JPEG/PNG/WebP, base64) → suggested numbers, not saved yet."""
    b = await body(request)
    imgs = []
    for x in (b.get("images") or [])[:4]:
        try:
            raw = base64.b64decode(str(x).split(",")[-1], validate=True)
        except ValueError:
            raise HTTPException(400, "عکس خراب بود")
        if len(raw) > 6 * 1024 * 1024:
            raise HTTPException(400, "هر عکس حداکثر ۶ مگابایت")
        imgs.append(to_jpeg(raw))
    if not imgs:
        raise HTTPException(400, "اسکرین‌شاتی نرسید")
    if not pipeline.ai_config(user):
        raise HTTPException(400, "برای خوندن اسکرین‌شات، هوش مصنوعی رو تو تنظیمات وصل کن (Gemini رایگان کافیه).")
    from . import ai
    try:
        return {"ok": True, "numbers": await run_in_threadpool(lambda: files.read_screenshot(user, imgs))}
    except ai.AIError as e:
        raise HTTPException(502, str(e))


def to_jpeg(raw):
    """Vision models take JPEG everywhere; PNG/WebP screenshots are converted with ffmpeg when needed."""
    if raw[:2] == b"\xff\xd8":
        return raw
    import shutil, subprocess, tempfile
    if not shutil.which("ffmpeg"):
        return raw
    with tempfile.TemporaryDirectory() as d:
        src, dst = f"{d}/in", f"{d}/out.jpg"
        open(src, "wb").write(raw)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-q:v", "3", dst], timeout=60)
        try:
            return open(dst, "rb").read()
        except OSError:
            raise HTTPException(400, "قالب عکس شناخته نشد")


NUMS = ("views", "reach", "likes", "comments", "saves", "shares", "follows", "avg_watch", "watch_total", "duration", "view_rate")


@router.post("/api/me/providers/manual/save", include_in_schema=False, dependencies=[Depends(same_site)])
async def save_manual(request: Request, user=Depends(need_editor)):
    """One reel's numbers from the form or a confirmed screenshot."""
    b = await body(request)
    m = REEL_URL.match(str(b.get("url") or "").strip())
    if not m:
        raise HTTPException(400, "لینک ریل اینستاگرام رو بذار (مثل https://www.instagram.com/reel/…)")
    src = "screenshot" if b.get("source") == "screenshot" else "manual"
    rec = {"shortcode": m.group(3), "url": f"https://www.instagram.com/reel/{m.group(3)}/"}
    for k in NUMS:
        v = b.get(k)
        if v in (None, ""):
            continue
        try:
            rec[k] = float(files.number(v)) if not isinstance(v, (int, float)) else float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"«{k}» عدد نیست")
        if rec[k] < 0 or (k == "view_rate" and rec[k] > 100):
            raise HTTPException(400, f"«{k}» نامعتبره")
        rec[k] = int(rec[k]) if rec[k].is_integer() and k not in ("avg_watch", "view_rate") else rec[k]
    for k in ("caption", "published"):
        if b.get(k):
            rec[k] = str(b[k])[:2200]
    if len(rec) <= 2:
        raise HTTPException(400, "دست‌کم یه عدد بنویس")
    old = read_norm(user["id"], src)
    write_norm(user["id"], src, {"reels": merge_records(old.get("reels", []), [rec])})
    ok, out = await run_in_threadpool(lambda: pipeline.run_script(user["id"], "shape.py", {}))
    if ok:
        store.update_status(user["id"], last_ok_at=time.time())
    return {"ok": ok, "message": "ذخیره شد ✓" if ok else out[-300:]}


@router.get("/api/me/coverage", include_in_schema=False)
def coverage(user=Depends(need_user)):
    return matrix(user, store.user_secrets(user).get("connections", {}), user_data(user), pipeline.scrapers_allowed())


# ---------- Instagram webhooks (https://developers.facebook.com/docs/instagram-platform/webhooks) ----------

def subscribe_webhooks(user):
    """Turn on comment and message events for this account: POST /me/subscribed_apps (needs the IG token)."""
    import urllib.parse, urllib.request
    from . import ig
    try:
        tok = ig.token(user)
    except ig.IGError:
        return " (Instagram API وصل نیست؛ بعد از وصل کردنش دوباره ذخیره کن تا رویدادها برای حسابت روشن بشن.)"
    q = urllib.parse.urlencode({"subscribed_fields": "comments,messages", "access_token": tok})
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://graph.instagram.com/v26.0/me/subscribed_apps?{q}", method="POST"), timeout=30).close()
        return " رویدادهای کامنت و پیام برای حسابت روشن شد."
    except Exception as e:  # noqa: BLE001
        return f" (روشن کردن رویدادها نشد: {str(e)[:80]})"

def webhook_users():
    for u in store.users():
        w = store.user_secrets(u).get("connections", {}).get("webhooks")
        if w:
            yield u, w


@router.get("/webhooks/instagram", include_in_schema=False)
def webhook_verify(request: Request):
    """Meta's subscription check: hub.mode=subscribe, hub.verify_token, hub.challenge echoed back."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and any(hmac.compare_digest(w.get("verify_token", ""), q.get("hub.verify_token", "")) for _, w in webhook_users()):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403)


@router.post("/webhooks/instagram", include_in_schema=False)
async def webhook_receive(request: Request):
    """A comment or message event, signed with the app secret (X-Hub-Signature-256). A comment on a reel
    with an active keyword rule runs that page's automation right away."""
    raw = await request.body()
    sig = request.headers.get("x-hub-signature-256", "")
    owners = [u for u, w in webhook_users()
              if sig and hmac.compare_digest("sha256=" + hmac.new(w.get("app_secret", "").encode(), raw, hashlib.sha256).hexdigest(), sig)]
    if not owners:
        raise HTTPException(403)
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400)
    ig_ids = {str(e.get("id")) for e in payload.get("entry", [])}
    # Instagram Login sends {field, value} in each entry; Facebook Login wraps them in entry[].changes[]
    has_comment = any(c.get("field") in ("comments", "live_comments") for e in payload.get("entry", []) for c in (e.get("changes") or [e]))
    for u in owners:
        mine = str(((store.status(u).get("providers") or {}).get("instagram") or (store.status(u).get("providers") or {}).get("meta_app") or {}).get("ig_user_id", ""))
        if has_comment and (not mine or mine in ig_ids):
            from . import ig
            threading.Thread(target=lambda u=u: ig.auto_tick(u), daemon=True).start()
            store.update_status(u["id"], webhook_at=time.time())
    return {"ok": True}
