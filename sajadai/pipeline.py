"""Per-user jobs: fetch from each connected source, build data.json, write the weekly AI content and
send Telegram messages. Each job runs the scripts in scripts/ as a subprocess whose environment holds
only that user's directory and keys, so users never see each other's data."""
import json, os, shutil, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import billing, config, store

TEH = timezone(timedelta(hours=3, minutes=30))

# what a user can connect, and the fields each connection needs (all kept encrypted)
CONNECTIONS = {
    "metricool": {"label": "Metricool", "fields": {"token": "API token", "user_id": "userId", "blog_id": "blogId (brand)"},
                  "script": "fetch_metricool.py"},
    "buffer": {"label": "Buffer", "fields": {"api_key": "API key"}, "script": "fetch_buffer.py"},
    "instagram": {"label": "Instagram API", "fields": {"token": "Long-lived access token"}, "script": "fetch_instagram.py"},
    "facebook": {"label": "Facebook (رقبا با Business Discovery)", "fields": {"token": "Access token (Facebook Login)"}, "script": "fetch_discovery.py"},
    # a Claude routine reads Metricool through claude.ai's connector and commits the numbers to a git repo
    "routine": {"label": "روتین Claude (مخزن داده)", "fields": {"repo": "مخزن (owner/name)", "branch": "شاخه"}, "script": "fetch_repo.py"},
}
STALE_HOURS = 8  # data older than this gets a banner on the dashboard and a message
REPO_CHECK_MINUTES = 15


def repo_key():
    k = config.DATA_DIR / "keys" / "data_repo"
    return str(k) if k.exists() else ""

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


def ai_chain(user):
    """The user's own AI providers, in the order they're tried. An older single key (ai_key with the
    provider and model in prefs) reads as a one-entry chain."""
    s = store.user_secrets(user)
    if isinstance(s.get("ai_chain"), list):
        return [c for c in s["ai_chain"] if isinstance(c, dict) and c.get("provider")]
    if s.get("ai_key"):
        p = store.prefs(user)
        return [{"id": "legacy", "provider": p.get("ai_provider") or "anthropic", "model": p.get("ai_model") or "", "key": s["ai_key"], "base_url": ""}]
    return []


def ai_config(user):
    """The user's own providers if they set any, else the panel's. The first entry's fields sit at the
    top level too, for the weekly content script."""
    chain = ai_chain(user)
    own = bool(chain)
    if not chain:
        panel = store.setting("ai", {}) or {}
        if panel.get("key") or panel.get("base_url"):
            if not billing.may_use_panel_ai(user):  # with subscriptions on, the shared key is for paid plans
                return None
            chain = [{"id": "panel", "provider": panel.get("provider") or "anthropic", "model": panel.get("model") or "", "key": panel.get("key") or "",
                      "base_url": panel.get("base_url") or "", "private_ok": True}]
    if not chain:
        return None
    first = chain[0]
    return {"provider": first["provider"], "model": first.get("model") or "", "key": first.get("key") or "", "base_url": first.get("base_url") or "",
            "own": own, "chain": chain}


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
    if name == "facebook":
        return {"SAJADAI_FB_TOKEN": vals.get("token", "")}
    if name == "routine":
        return {"SAJADAI_DATA_REPO": vals.get("repo", ""), "SAJADAI_DATA_BRANCH": vals.get("branch") or "main", "SAJADAI_REPO_KEY": repo_key()}
    return {}


def repo_head(vals):
    """The latest commit on the routine's branch (git ls-remote), or None when it can't be reached."""
    repo = vals.get("repo", "")
    url = repo if repo.startswith(("git@", "https://", "ssh://")) else (f"git@github.com:{repo}.git" if repo_key() else f"https://github.com/{repo}.git")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if repo_key():
        env["GIT_SSH_COMMAND"] = (f"ssh -i {repo_key()} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "
                                  f"-o UserKnownHostsFile={config.DATA_DIR / 'keys' / 'known_hosts'}")
    try:
        r = subprocess.run(["git", "ls-remote", url, "refs/heads/" + (vals.get("branch") or "main")], env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None, "git در دسترس نیست"
    if r.returncode or not r.stdout.strip():
        err = (r.stderr.strip().splitlines() or [""])[-1]
        return None, ("دسترسی به مخزن نیست؛ کلید پنل (deploy key) رو با دسترسی خواندن به مخزن اضافه کن." if "denied" in err.lower() or "not found" in err.lower() or "could not read" in err.lower()
                      else f"مخزن پیدا نشد: {err[:120]}")
    return r.stdout.split()[0], ""


def data_time(user_id):
    """When the page's numbers were last read from their source: the routine's commit time when the data
    comes from its repo, else the last successful sync, else data.json's build time."""
    d = config.user_dir(user_id)
    for v in ((analysis_load(d / "raw" / "repo_source.json") or {}).get("committed_at"),):
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            pass
    user = store.get_user(user_id)
    if user and store.status(user).get("last_ok_at"):
        return store.status(user)["last_ok_at"]
    try:
        return datetime.fromisoformat(str((analysis_load(d / "data" / "data.json") or {}).get("generated_at")).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def analysis_load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def health(user):
    """{"data_at", "stale", "hours"} for the banner and the alert."""
    if not store.user_secrets(user).get("connections"):
        return {"data_at": None, "stale": False, "hours": None, "connected": False}
    t = data_time(user["id"])
    hours = round((time.time() - t) / 3600, 1) if t else None
    return {"data_at": t, "hours": hours, "stale": hours is None or hours > STALE_HOURS, "connected": True,
            "last_error": None if store.status(user).get("refresh_ok", True) else (store.status(user).get("refresh_log") or "")[-400:]}


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
            env = source_env(name, vals)
            if name == "routine" and len(conns) == 1:
                env["SAJADAI_REPO_ONLY"] = "1"
            ok, out = run_script(user_id, spec["script"], env)
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
        good = bool(worked) and ok
        store.update_status(user_id, refresh_at=time.time(), refresh_ok=good, refresh_log="\n".join(log), refresh_failed=failed,
                            **({"last_ok_at": time.time()} if good else {}))
        if good:
            after_sync(user_id)
        return good


def after_sync(user_id):
    """After a successful sync: rebuild the AI analysis when the numbers changed (in the background)."""
    try:
        from . import insights
        threading.Thread(target=insights.refresh_if_changed, args=(user_id,), daemon=True).start()
    except ImportError:
        pass


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
        # the weekly research wants web search (Claude or GPT); other providers write from the page's own numbers
        from .ai import PROVIDERS
        pick = next((c for c in ai["chain"] if PROVIDERS.get(c["provider"], {}).get("kind") in ("anthropic", "openai")), ai["chain"][0])
        spec = PROVIDERS.get(pick["provider"], {})
        extra = {"SAJADAI_AI_PROVIDER": spec.get("kind", "compat") if spec.get("kind") != "compat" else "compat", "SAJADAI_AI_KEY": pick.get("key") or "",
                 "SAJADAI_AI_MODEL": pick.get("model") or spec.get("default") or "", "SAJADAI_AI_BASE_URL": pick.get("base_url") or spec.get("base") or ""}
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
        if name == "routine":
            head, err = repo_head(vals)
            return (True, f"وصل شد: آخرین commit مخزن {head[:7]}. داده هر ۱۵ دقیقه چک می‌شه.") if head else (False, err)
        if name == "facebook":
            pages = _get("https://graph.facebook.com/v24.0/me/accounts?" + urllib.parse.urlencode(
                {"fields": "name,instagram_business_account{username}", "limit": 50, "access_token": vals["token"]})).get("data", [])
            linked = [p for p in pages if p.get("instagram_business_account")]
            if not linked:
                return False, "توکن درسته، ولی هیچ صفحهٔ فیسبوکی با اینستاگرام حرفه‌ای بهش وصل نیست. تو Meta Business اینستاگرام رو به یه صفحهٔ فیسبوک وصل کن."
            ig = linked[0]["instagram_business_account"]
            return True, f"وصل شد: صفحهٔ «{linked[0].get('name')}» با اینستاگرام @{ig.get('username')}. رقبا رو تو صفحهٔ «رقبا» اضافه کن."
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
        if store.prefs(u).get("agency_auto"):
            from . import agency
            if agency.due(u, t):
                out.append((u["id"], "agency"))
        if "routine" in conns and now - (s.get("repo_check_at") or 0) >= REPO_CHECK_MINUTES * 60:
            out.append((u["id"], "repocheck"))
        if conns and now - (s.get("health_at") or 0) >= 3600:
            out.append((u["id"], "health"))
        if "instagram" in conns:
            content = config.user_dir(u["id"]) / "content"
            if (content / "ig_queue.json").exists() and '"scheduled"' in _peek(content / "ig_queue.json") + _peek(content / "ig_queue.json", "processing"):
                out.append((u["id"], "igqueue"))
            if now - (s.get("igauto_at") or 0) >= 600 and '"active": true' in _peek(content / "ig_auto.json"):
                out.append((u["id"], "igauto"))
    return out


def _peek(path, status=None):
    """A file's text, for a cheap check before parsing it (status: the word to look for instead)."""
    try:
        t = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return t if status is None else ('"scheduled"' if f'"{status}"' in t else "")


def ig_queue(uid):
    from . import ig, ops
    user = store.get_user(uid)
    for item in ig.queue_tick(user, public_url()):
        if item["status"] == "published":
            ops.tell_user(user, "✅ ریل منتشر شد", (item.get("caption") or "").split("\n")[0][:120] + "\n" + (item.get("permalink") or ""), "publish")
        else:
            ops.tell_user(user, "⚠️ ریل منتشر نشد", item.get("note") or "", "publish")


def repo_check(uid):
    """Every 15 minutes: has the routine committed new numbers? Then sync now instead of waiting 6 hours."""
    user = store.get_user(uid)
    vals = store.user_secrets(user).get("connections", {}).get("routine") or {}
    head, err = repo_head(vals)
    store.update_status(uid, repo_check_at=time.time(), **({"repo_error": err} if err else {"repo_error": ""}))
    if head and head != store.status(user).get("repo_head"):
        if refresh(uid):
            store.update_status(uid, repo_head=head)


def health_check(uid):
    """Hourly: data older than STALE_HOURS → the bell and Telegram, at most every 6 hours."""
    from . import ops
    user = store.get_user(uid)
    h = health(user)
    st = store.status(user)
    store.update_status(uid, health_at=time.time())
    if h["stale"] and time.time() - (st.get("stale_alert_at") or 0) >= 6 * 3600:
        store.update_status(uid, stale_alert_at=time.time())
        age = f"{round(h['hours'])} ساعت" if h["hours"] is not None else "مدت نامعلومی"
        why = ("\n\nآخرین خطا: " + h["last_error"][-300:]) if h.get("last_error") else ""
        ops.tell_user(user, "⚠️ دادهٔ داشبورد قدیمی شده", f"آخرین دادهٔ موفق {age} پیشه (بیشتر از {STALE_HOURS} ساعت).{why}\n\nاتصال‌ها رو تو تنظیمات چک کن.", "system")
        ops.alert_admins("⚠️ همگام‌سازی یه پیج عقب افتاده", f"کاربر {uid}: {age}{why}")


def agency_report(uid):
    from . import agency, ops
    user = store.get_user(uid)
    agency.mark_sent(user)  # once a month even if a channel fails; the owner hears about failures
    data = json.loads((config.user_dir(uid) / "data" / "data.json").read_text(encoding="utf-8"))
    res = agency.send(user, data)
    if not all(ok for _, ok, _ in res):
        ops.tell_user(user, "⚠️ گزارش ماهانهٔ مشتری کامل نرفت", " · ".join(m for _, _, m in res))


def ig_auto(uid):
    from . import ig
    store.update_status(uid, igauto_at=time.time())
    ig.auto_tick(store.get_user(uid))


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
                elif job == "igqueue":
                    ig_queue(uid)
                elif job == "igauto":
                    ig_auto(uid)
                elif job == "agency":
                    agency_report(uid)
                elif job == "repocheck":
                    repo_check(uid)
                elif job == "health":
                    health_check(uid)
            except Exception as e:  # one user's failure mustn't stop the others
                store.update_status(uid, **{f"{job}_log": f"error: {e}"})
                ops.alert_admins(f"⚠️ خطا در کار زمان‌بندی‌شدهٔ «{job}»", f"کاربر {uid}: {e}"[:800])
