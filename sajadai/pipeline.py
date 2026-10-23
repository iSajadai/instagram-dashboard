"""Per-user jobs: fetch from each connected source, build data.json, write the weekly AI content and
send Telegram messages. Each job runs the scripts in scripts/ as a subprocess whose environment holds
only that user's directory and keys, so users never see each other's data."""
import json, os, shutil, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

from . import billing, config, store

TEH = timezone(timedelta(hours=3, minutes=30))

# what a user can connect, and the fields each connection needs (all kept encrypted)
CONNECTIONS = {
    "metricool": {"label": "Metricool", "fields": {"token": "API token", "user_id": "userId", "blog_id": "blogId (brand)"},
                  "script": "fetch_metricool.py"},
    "buffer": {"label": "Buffer", "fields": {"api_key": "API key"}, "script": "fetch_buffer.py"},
    "instagram": {"label": "Instagram API", "fields": {"token": "Long-lived access token"}, "script": "fetch_instagram.py"},
}
AI_PROVIDERS = {"anthropic": "Claude (Anthropic)", "openai": "GPT (OpenAI)"}

DEFAULT_GOALS = [
    {"id": "followers", "label": "۱۰۰۰ فالوئر", "metric": "followers", "target": 1000, "deadline": None, "why": "هدف نمونه؛ از تنظیمات عوضش کن."},
    {"id": "reels-week", "label": "۴ ریل در هفته", "metric": "reels_7d", "target": 4, "deadline": None, "why": "ریل‌های منتشرشده در ۷ روز گذشته."},
    {"id": "views-week", "label": "۱۰ هزار بازدید در هفته", "metric": "views_7d", "target": 10000, "deadline": None, "why": "جمع بازدید ریل‌ها در ۷ روز گذشته."},
]

_locks = {}
_locks_guard = threading.Lock()


def lock_for(user_id):
    with _locks_guard:
        return _locks.setdefault(user_id, threading.Lock())


def ensure_user_dir(user_id):
    """The user's folder with empty raw/ and starter content, and a data.json the page can load."""
    d = config.user_dir(user_id)
    fresh = not (d / "data" / "data.json").exists()
    for sub in ("raw", "data", "content"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    for name, default in (("goals.json", DEFAULT_GOALS), ("topics.json", []), ("reel_topics.json", {}), ("experiments.json", []),
                          ("ideas.json", []), ("insights.json", []), ("benchmarks.json", [])):
        p = d / "content" / name
        if not p.exists():
            p.write_text(json.dumps(default, ensure_ascii=False, indent=1), encoding="utf-8")
    if fresh:
        run_script(user_id, "shape.py", {})
    return d


def import_legacy(user_id, src):
    """Copy an existing dashboard (a repo checkout or a standalone state folder) into a user's folder."""
    src = os.path.abspath(src)
    d = ensure_user_dir(user_id)
    for sub in ("raw", "content"):
        if os.path.isdir(os.path.join(src, sub)):
            for f in os.listdir(os.path.join(src, sub)):
                if f.endswith(".json"):
                    shutil.copy2(os.path.join(src, sub, f), d / sub / f)
    if os.path.exists(os.path.join(src, "data", "data.json")):
        shutil.copy2(os.path.join(src, "data", "data.json"), d / "data" / "data.json")
    for f in ("ig-token.json", "notify-state.json"):
        if os.path.exists(os.path.join(src, f)):
            shutil.copy2(os.path.join(src, f), d / f)


def ai_config(user):
    """The user's own AI provider and key if they set one, else the panel's."""
    p, s = store.prefs(user), store.user_secrets(user)
    panel = store.setting("ai", {}) or {}
    if s.get("ai_key"):
        return {"provider": p.get("ai_provider") or "anthropic", "model": p.get("ai_model") or "", "key": s["ai_key"], "own": True}
    if panel.get("key") and billing.may_use_panel_ai(user):  # with subscriptions on, the shared key is for paid plans
        return {"provider": panel.get("provider") or "anthropic", "model": panel.get("model") or "", "key": panel["key"], "own": False}
    return None


def public_url():
    return (store.setting("public_url") or config.PUBLIC_URL or "").rstrip("/")


def base_env(user):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "PYTHONPATH")}
    env["SAJADAI_STATE"] = str(config.user_dir(user["id"]))
    env["PYTHONIOENCODING"] = "utf-8"
    p = store.prefs(user)
    bot = store.setting("telegram_bot")
    if bot and p.get("telegram_chat"):
        env.update(SAJADAI_TG_TOKEN=bot, SAJADAI_TG_CHAT=str(p["telegram_chat"]), SAJADAI_DASH_URL=public_url())
    return env


def run_script(user_id, script, extra, timeout=900):
    user = store.get_user(user_id)
    env = {**(base_env(user) if user else {"SAJADAI_STATE": str(config.user_dir(user_id)), "PATH": os.environ.get("PATH", "")}), **extra}
    try:
        r = subprocess.run([sys.executable, str(config.SCRIPTS / script)], env=env, cwd=str(config.ROOT),
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()[-3000:]
    except subprocess.TimeoutExpired:
        return False, f"{script}: timed out after {timeout}s"


def source_env(name, vals):
    if name == "metricool":
        return {"METRICOOL_TOKEN": vals.get("token", ""), "METRICOOL_USER": str(vals.get("user_id", "")), "METRICOOL_BLOG": str(vals.get("blog_id", ""))}
    if name == "buffer":
        return {"SAJADAI_BUFFER_KEY": vals.get("api_key", "")}
    if name == "instagram":
        return {"SAJADAI_IG_TOKEN": vals.get("token", "")}
    return {}


def refresh(user_id):
    """Fetch from every connected source; rebuild data.json if at least one worked."""
    with lock_for(user_id):
        user = store.get_user(user_id)
        ensure_user_dir(user_id)
        conns = store.user_secrets(user).get("connections", {})
        log, worked, failed = [], [], []
        for name, spec in CONNECTIONS.items():
            vals = conns.get(name)
            if not vals or not all(vals.get(f) for f in spec["fields"]):
                continue
            ok, out = run_script(user_id, spec["script"], source_env(name, vals))
            log.append(f"[{spec['label']}] {'✓' if ok else '✗'} {out}")
            if ok:
                worked.append(name)
            else:
                failed.append(name)
                if name not in store.status(user).get("refresh_failed", []):  # tell once, when a source starts failing
                    add_notice(user_id, f"⚠️ گرفتن داده از {spec['label']} ناموفق بود", out[-600:] + "\n\nاتصال رو تو تنظیمات چک کن.")
        if not log:
            store.update_status(user_id, refresh_at=time.time(), refresh_ok=False, refresh_log="هنوز هیچ منبعی وصل نشده.")
            return False
        if worked:
            ok, out = run_script(user_id, "shape.py", {})
            log.append(f"[data.json] {'✓' if ok else '✗'} {out}")
        else:
            ok = False
        store.update_status(user_id, refresh_at=time.time(), refresh_ok=bool(worked) and ok, refresh_log="\n".join(log), refresh_failed=failed)
        return bool(worked) and ok


def add_notice(user_id, title, text, kind="system"):
    """A message for the bell on the user's dashboard (notify.py adds alerts and weekly reports to the same file)."""
    path = config.user_dir(user_id) / "content" / "notifications.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        items = []
    items.insert(0, {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "title": title[:120], "text": text[:4000]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items[:100], ensure_ascii=False, indent=1), encoding="utf-8")


def write_content(user_id):
    with lock_for(user_id):
        user = store.get_user(user_id)
        ai = ai_config(user)
        if not ai:
            store.update_status(user_id, content_at=time.time(), content_ok=False, content_log="کلید هوش مصنوعی تنظیم نشده.")
            return False
        p = store.prefs(user)
        extra = {"SAJADAI_AI_PROVIDER": ai["provider"], "SAJADAI_AI_KEY": ai["key"], "SAJADAI_AI_MODEL": ai["model"]}
        if p.get("page_profile"):
            extra["SAJADAI_PAGE_PROFILE"] = p["page_profile"]
        ok, out = run_script(user_id, "write_content.py", extra, timeout=1800)
        if ok:
            run_script(user_id, "shape.py", {})
            add_notice(user_id, "💡 ایده‌ها و تحلیل این هفته آماده‌ست", "تو «تحلیل و ایده‌ها» ببینشون؛ هر کدوم رو می‌تونی به بُرد تولید ببری.", "content")
        else:
            add_notice(user_id, "⚠️ نوشتن ایده‌های هفته ناموفق بود", out[-600:])
        store.update_status(user_id, content_at=time.time(), content_ok=ok, content_log=out,
                            content_week=week_key())
        return ok


def notify(user_id):
    """Alerts and the weekly report: always kept in the user's inbox (the bell on the dashboard), and
    sent to Telegram too when the admin set up the bot and the user gave a chat id."""
    user = store.get_user(user_id)
    if not user:
        return
    d = config.user_dir(user_id)
    env = base_env(user)
    try:
        subprocess.run([sys.executable, str(config.SCRIPTS / "notify.py"), "--state", str(d / "notify-state.json"),
                        "--inbox", str(d / "content" / "notifications.json")], env=env,
                       cwd=str(config.ROOT), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        pass


def week_key():
    t = datetime.now(TEH)
    return (t.date() - timedelta(days=(t.weekday() - 5) % 7)).isoformat()  # this week's Saturday


# ---------- checking a connection before it's saved ----------

def _get(url, headers=None, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "sajadai-dashboard", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def test_connection(name, vals):
    """(ok, message in Persian) for a connection's values, with a read-only call to the service."""
    try:
        if name == "metricool":
            q = urllib.parse.urlencode({"userId": vals["user_id"], "blogId": vals["blog_id"]})
            brands = _get(f"https://app.metricool.com/api/admin/simpleProfiles?{q}", {"X-Mc-Auth": vals["token"]})
            b = next((x for x in brands if str(x.get("id")) == str(vals["blog_id"])), None)
            if not b:
                return False, "توکن درسته ولی برندی با این blogId پیدا نشد. برندهای حساب: " + "، ".join(f"{x.get('label')} ({x.get('id')})" for x in brands[:10])
            return True, f"وصل شد: برند «{b.get('label')}»" + (f"، اینستاگرام @{b['instagram']}" if b.get("instagram") else "، ولی اینستاگرامی به این برند وصل نیست")
        if name == "buffer":
            hdr = {"Authorization": f"Bearer {vals['api_key']}", "Content-Type": "application/json"}
            body = json.dumps({"query": "{ account { organizations { id name } } }"}).encode()
            orgs = _get("https://api.buffer.com", hdr, body)["data"]["account"]["organizations"]
            n = 0
            for o in orgs:
                qq = json.dumps({"query": "query($o: OrganizationId!) { channels(input: {organizationId: $o}) { service } }", "variables": {"o": o["id"]}}).encode()
                n += sum(1 for c in _get("https://api.buffer.com", hdr, qq)["data"]["channels"] if c["service"] == "instagram")
            if not n:
                return False, "کلید درسته، ولی هیچ اینستاگرامی تو Buffer وصل نیست. تو Buffer از Channels ← Connect اینستاگرام رو وصل کن."
            return True, f"وصل شد: {n} حساب اینستاگرام تو Buffer"
        if name == "instagram":
            me = _get("https://graph.instagram.com/v26.0/me?" + urllib.parse.urlencode({"fields": "username,followers_count", "access_token": vals["token"]}))
            me = me["data"][0] if isinstance(me.get("data"), list) and me["data"] else me
            return True, f"وصل شد: @{me.get('username')}، {me.get('followers_count')} فالوئر"
    except urllib.error.HTTPError as e:
        return False, f"سرویس کلید رو قبول نکرد (HTTP {e.code})." + (" API متریکول پلن Advanced لازم داره." if name == "metricool" else "")
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"به سرویس وصل نشدیم: {getattr(e, 'reason', e)}"
    except (KeyError, TypeError, ValueError) as e:
        return False, f"جواب سرویس عجیب بود: {e}"
    return False, "این نوع اتصال شناخته نیست."


# ---------- scheduler ----------

def due_jobs(now=None):
    """(user_id, job) pairs that are due: refresh every 6h, Telegram hourly, AI content on Saturdays from 08:30 Tehran."""
    now = now or time.time()
    t = datetime.fromtimestamp(now, TEH)
    out = []
    for u in store.users():
        s = store.status(u)
        conns = store.user_secrets(u).get("connections", {})
        if conns and now - (s.get("refresh_at") or 0) >= config.REFRESH_HOURS * 3600:
            out.append((u["id"], "refresh"))
        if now - (s.get("notify_at") or 0) >= 3600:
            out.append((u["id"], "notify"))
        if t.weekday() == 5 and (t.hour, t.minute) >= (8, 30) and s.get("content_week") != week_key() and ai_config(u) and conns:
            out.append((u["id"], "content"))
    return out


def scheduler_loop(stop: threading.Event):
    from . import ops  # imported here: ops reaches back into this module for the bell
    while not stop.wait(60):
        ops.tick()  # /healthz checks the scheduler is still turning
        if ops.backup_due(datetime.now(TEH)):
            ops.run_backup()
        for uid, job in due_jobs():
            try:
                if job == "refresh":
                    refresh(uid)
                elif job == "notify":
                    store.update_status(uid, notify_at=time.time())
                    notify(uid)
                elif job == "content":
                    write_content(uid)
            except Exception as e:  # one user's failure mustn't stop the others
                store.update_status(uid, **{f"{job}_log": f"error: {e}"})
                ops.alert_admins(f"⚠️ خطا در کار زمان‌بندی‌شدهٔ «{job}»", f"کاربر {uid}: {e}"[:800])
