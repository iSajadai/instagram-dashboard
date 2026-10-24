"""The panel's own calls to Instagram (Instagram API with Instagram Login), with the user's token:
publishing a reel, replying to comments, sending the one private reply Instagram allows per comment,
and the keyword automation built on it. Errors come back as IGError with a message fit for the user.

Publishing: Instagram fetches the video from a public URL, so an upload is kept under
DATA_DIR/media with an unguessable name, served at /m/<name>, and deleted once the reel is out.
The queue (content/ig_queue.json) moves each post through
scheduled → processing (container made, Instagram transcoding) → published | failed, one step per
scheduler tick, so nothing waits on Instagram inside a request.

Keyword automation (content/ig_auto.json): when a comment on the chosen reel has the keyword, the
commenter gets the message as a private reply (once per person per rule; within 7 days of the
comment, as Instagram requires) and, if wanted, a short public reply so others see it was answered.
Comments are polled, since comment webhooks need Meta's Advanced Access."""
import json, random, re, secrets, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

from . import analysis, config, store

API = "https://graph.instagram.com/v26.0"
MEDIA_DIR = config.DATA_DIR / "media"
MAX_VIDEO = 100 * 1024 * 1024  # what Cloudflare passes on a free plan (Instagram itself takes 300MB)
CAPTION_MAX = 2200
PRIVATE_REPLY_DAYS = 7


class IGError(Exception):
    pass


# ---------- token and calls ----------

def token(user):
    """The current token: the one fetch_instagram.py keeps refreshed, if it came from the token the user
    entered; else the entered one."""
    conns = store.user_secrets(user).get("connections") or {}
    given = (conns.get("instagram") or {}).get("token") or (conns.get("meta_app") or {}).get("token")
    if not given:
        raise IGError("Instagram API وصل نیست؛ از «تنظیمات ← اتصال‌ها» توکن اینستاگرام رو بذار.")
    st = analysis.load(config.user_dir(user["id"]) / "ig-token.json") or {}
    if st.get("access_token") and st.get("source") == given[-12:]:
        return st["access_token"]
    return given


PERM = {
    "instagram_business_content_publish": "انتشار",
    "instagram_business_manage_comments": "کامنت‌ها",
    "instagram_business_manage_messages": "پیام‌ها",
}


def call(user, method, path, data=None, **params):
    tok = token(user)
    url = f"{API}/{path}"
    body = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode({**params, "access_token": tok})
    elif method == "DELETE":
        url += "?" + urllib.parse.urlencode({"access_token": tok})
    else:
        if data is not None:  # JSON body (messages)
            body = json.dumps(data).encode()
            url += "?" + urllib.parse.urlencode({"access_token": tok})
        else:
            body = urllib.parse.urlencode({**params, "access_token": tok}).encode()
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except ValueError:
            err = {}
        raise IGError(explain(e.code, err)) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise IGError(f"به اینستاگرام وصل نشدیم: {getattr(e, 'reason', e)}") from None


def explain(status, err):
    code, sub, msg = err.get("code"), err.get("error_subcode"), err.get("message") or ""
    if code == 190:
        return "توکن اینستاگرام منقضی یا باطل شده؛ یه توکن تازه تو تنظیمات بذار."
    if code == 10 and sub == 2534022 or "outside of allowed window" in msg:
        return "از این کامنت بیشتر از ۷ روز گذشته؛ اینستاگرام اجازهٔ پیام خصوصی نمی‌ده."
    if sub == 2534023 or "already" in msg.lower() and "repl" in msg.lower():
        return "به این کامنت قبلاً پیام خصوصی فرستاده شده (اینستاگرام فقط یک بار اجازه می‌ده)."
    if code in (10, 200) or "permission" in msg.lower():
        need = next((v for k, v in PERM.items() if k in msg), "")
        return f"توکن اینستاگرام اجازهٔ {need or 'این کار'} رو نداره؛ یه توکن تازه با همهٔ دسترسی‌ها بساز (راهنما تو تنظیمات)."
    if code in (4, 17, 32, 613) or status == 429:
        return "سقف درخواست اینستاگرام پر شده؛ کمی بعد دوباره امتحان کن."
    if code == 9 or "limit" in msg.lower() and "publish" in msg.lower():
        return "سقف انتشار ۲۴ ساعتهٔ اینستاگرام پر شده."
    return f"خطای اینستاگرام ({status}): {msg[:200]}"


def me(user):
    r = call(user, "GET", "me", fields="user_id,username")
    return {"id": r.get("user_id") or r.get("id"), "username": r.get("username")}


# ---------- media files served for Instagram to fetch ----------

def new_media_name(ext):
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return secrets.token_hex(16) + ext


def media_path(name):
    if not re.fullmatch(r"[0-9a-f]{32}\.(mp4|mov|jpg)", name or ""):
        return None
    p = MEDIA_DIR / name
    return p if p.exists() else None


def drop_media(*names):
    for n in names:
        p = media_path(n) if n else None
        if p:
            p.unlink(missing_ok=True)


def sweep_media(max_age=3 * 86400, keep=()):
    """Uploads nobody published within three days."""
    if not MEDIA_DIR.exists():
        return
    for p in MEDIA_DIR.iterdir():
        if p.name not in keep and time.time() - p.stat().st_mtime > max_age:
            p.unlink(missing_ok=True)


def sniff_video(head):
    """mp4/mov by their header ('ftyp' box at byte 4)."""
    return head[4:8] == b"ftyp"


# ---------- the publishing queue ----------

def _queue_path(user):
    return config.user_dir(user["id"]) / "content" / "ig_queue.json"


def load_queue(user):
    q = analysis.load(_queue_path(user))
    return q if isinstance(q, list) else []


def save_queue(user, q):
    p = _queue_path(user)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(q[-100:], ensure_ascii=False, indent=1), encoding="utf-8")


def limit(user, ig_id=None):
    ig_id = ig_id or me(user)["id"]
    r = call(user, "GET", f"{ig_id}/content_publishing_limit", fields="quota_usage,config")
    d = (r.get("data") or [{}])[0]
    return {"used": d.get("quota_usage", 0), "total": (d.get("config") or {}).get("quota_total", 50)}


def step(user, item, public_url):
    """Move one queued post a step. Returns True when it changed."""
    now = time.time()
    if item["status"] == "scheduled" and item["when"] <= now:
        if not public_url.startswith("https://"):
            return fail(item, "آدرس عمومی پنل (https) تنظیم نشده؛ اینستاگرام ویدیو رو باید از یه آدرس عمومی برداره. ادمین از «پنل مدیریت» تنظیمش کنه.")
        if not media_path(item["video"]):
            return fail(item, "فایل ویدیو پیدا نشد؛ دوباره آپلود کن.")
        ig = me(user)
        lim = limit(user, ig["id"])
        if lim["used"] >= lim["total"]:
            item["note"] = f"سقف {lim['total']} انتشار در ۲۴ ساعت پر شده؛ بعداً خودکار امتحان می‌شه."
            item["when"] = now + 3600
            return True
        params = {"media_type": "REELS", "video_url": f"{public_url}/m/{item['video']}", "caption": item.get("caption", ""),
                  "share_to_feed": "true" if item.get("share_to_feed", True) else "false"}
        if item.get("cover") and media_path(item["cover"]):
            params["cover_url"] = f"{public_url}/m/{item['cover']}"
        elif item.get("thumb_offset"):
            params["thumb_offset"] = str(int(item["thumb_offset"]))
        r = call(user, "POST", f"{ig['id']}/media", **params)
        item.update(status="processing", container=r["id"], ig_id=ig["id"], started=now, note="اینستاگرام داره ویدیو رو پردازش می‌کنه…")
        return True
    if item["status"] == "processing":
        r = call(user, "GET", item["container"], fields="status_code,status")
        code = r.get("status_code")
        if code == "FINISHED":
            pub = call(user, "POST", f"{item['ig_id']}/media_publish", creation_id=item["container"])
            link = call(user, "GET", pub["id"], fields="permalink").get("permalink")
            item.update(status="published", media_id=pub["id"], permalink=link, published=time.time(), note="")
            remember_duration(user, link, media_path(item.get("video")))
            drop_media(item.get("video"), item.get("cover"))
            return True
        if code in ("ERROR", "EXPIRED"):
            drop_media(item.get("cover"))
            return fail(item, "اینستاگرام ویدیو رو قبول نکرد" + (f" ({r.get('status')})" if r.get("status") else "") +
                        ". ویدیو باید MP4 با H.264 و صدای AAC، ۳ ثانیه تا ۱۵ دقیقه، عمودی ۹:۱۶ باشه.")
        if now - item.get("started", now) > 3600:
            return fail(item, "پردازش ویدیو تو اینستاگرام بیشتر از یک ساعت طول کشید؛ دوباره امتحان کن.")
    return False


def probe(path):
    """Seconds of video, from the file's header (ffprobe)."""
    import shutil, subprocess
    if not path or not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60)
        return round(float(r.stdout.strip()), 1) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def remember_duration(user, permalink, path):
    """content/durations.json {shortcode: seconds}, which shape.py uses for the watch-% column."""
    m = re.search(r"/(?:reels?|p|tv)/([A-Za-z0-9_-]+)", permalink or "")
    secs = probe(path)
    if not m or not secs:
        return
    p = config.user_dir(user["id"]) / "content" / "durations.json"
    d = analysis.load(p) or {}
    d[m.group(1)] = secs
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")


def fail(item, msg):
    item.update(status="failed", note=msg)
    return True


def queue_tick(user, public_url):
    """Called every minute by the scheduler for users with something queued."""
    q = load_queue(user)
    if not any(i["status"] in ("scheduled", "processing") for i in q):
        return []
    changed, done = False, []
    for item in q:
        if item["status"] not in ("scheduled", "processing"):
            continue
        before = item["status"]
        try:
            changed |= step(user, item, public_url)
        except IGError as e:
            changed |= fail(item, str(e))
        if item["status"] != before and item["status"] in ("published", "failed"):
            done.append(item)
    if changed:
        save_queue(user, q)
    return done


# ---------- comments ----------

def reply_comment(user, comment_id, text):
    return call(user, "POST", f"{comment_id}/replies", message=text[:CAPTION_MAX])


def hide_comment(user, comment_id, hide=True):
    return call(user, "POST", comment_id, hide="true" if hide else "false")


def private_reply(user, comment_id, text, ig_id=None):
    ig_id = ig_id or "me"
    return call(user, "POST", f"{ig_id}/messages", data={"recipient": {"comment_id": comment_id}, "message": {"text": text[:900]}})


# ---------- keyword automation ----------

def _auto_path(user):
    return config.user_dir(user["id"]) / "content" / "ig_auto.json"


def load_auto(user):
    a = analysis.load(_auto_path(user))
    return a if isinstance(a, dict) and isinstance(a.get("rules"), list) else {"rules": [], "sent": {}, "log": []}


def save_auto(user, a):
    p = _auto_path(user)
    p.parent.mkdir(parents=True, exist_ok=True)
    a["log"] = a.get("log", [])[-200:]
    p.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")


def keyword_hit(keyword, text):
    """The keyword as a word or phrase in the comment, ignoring Persian/Arabic letter variants, kashida,
    case and diacritics («پرامپت»، «پرامپـت!»، «PROMPT»). A half-space joins a word, so «پرامپت‌نویسی»
    isn't «پرامپت»."""
    from .fa.text import normalize
    def norm(s):
        s = normalize(str(s or "")).lower().replace("\u0640", "")
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s\u200c]", " ", s)).strip()
    k, t = norm(keyword), norm(text)
    return bool(k) and f" {k} " in f" {t} "


PUBLIC_REPLIES = ["دایرکتت رو چک کن 🙌", "فرستادم، دایرکت رو ببین ✨", "تو دایرکتته 📩", "برات فرستادم 🌱"]


def auto_tick(user):
    """Check the reels that have active rules and answer new matching comments. Returns what was sent."""
    a = load_auto(user)
    rules = [r for r in a["rules"] if r.get("active")]
    if not rules:
        return []
    ig = me(user)
    sent = a.setdefault("sent", {})
    out = []
    now = datetime.now(timezone.utc)
    for media in {r["media_id"] for r in rules}:
        try:
            r = call(user, "GET", f"{media}/comments", fields="id,text,timestamp,username,from", limit=50)
        except IGError as e:
            a["log"].append({"at": time.time(), "error": str(e)})
            continue
        for c in r.get("data", []):
            who = (c.get("from") or {}).get("id") or c.get("username")
            if not who or (c.get("username") or "").lower() == (ig["username"] or "").lower():
                continue
            try:
                age = (now - datetime.fromisoformat(c["timestamp"].replace("+0000", "+00:00"))).days
            except (KeyError, ValueError):
                age = 0
            if age >= PRIVATE_REPLY_DAYS:
                continue
            for rule in rules:
                key = f"{rule['id']}:{who}"
                if rule["media_id"] != media or key in sent or not keyword_hit(rule["keyword"], c.get("text")):
                    continue
                try:
                    private_reply(user, c["id"], rule["message"], ig["id"])
                    sent[key] = int(time.time())
                    entry = {"at": time.time(), "rule": rule["id"], "user": c.get("username"), "comment": (c.get("text") or "")[:120], "ok": True}
                    if rule.get("public_reply"):
                        try:
                            reply_comment(user, c["id"], random.choice(PUBLIC_REPLIES))
                        except IGError:
                            pass
                    rule["count"] = rule.get("count", 0) + 1
                except IGError as e:
                    sent[key] = int(time.time())  # Instagram allows one try per comment; don't hammer it
                    entry = {"at": time.time(), "rule": rule["id"], "user": c.get("username"), "comment": (c.get("text") or "")[:120], "ok": False, "error": str(e)}
                a["log"].append(entry)
                out.append(entry)
    a["checked"] = time.time()
    save_auto(user, a)
    return out


def online_followers(user):
    """When the page's followers are online, by hour (Tehran), averaged over the days Instagram returns.
    None when Instagram doesn't give it (fewer than 100 followers, or the metric isn't offered)."""
    ig = me(user)
    try:
        r = call(user, "GET", f"{ig['id']}/insights", metric="online_followers", period="lifetime")
    except IGError:
        return None
    rows = ((r.get("data") or [{}])[0].get("values") or [])
    per_hour = {}
    for v in rows:
        val = v.get("value") or {}
        if not isinstance(val, dict) or not val:
            continue
        for h, n in val.items():
            try:
                per_hour.setdefault(int(h), []).append(float(n))
            except (TypeError, ValueError):
                pass
    if not per_hour:
        return None
    # Instagram reports hours in Pacific time; Tehran is +11:30 from PST, +10:30 from PDT
    shift = 10.5 if is_pdt(datetime.now(timezone.utc)) else 11.5
    tehran = {}
    for h, ns in per_hour.items():
        th = (h + shift) % 24
        tehran[th] = sum(ns) / len(ns)
    return {"hours": [{"hour": h, "online": round(tehran[h])} for h in sorted(tehran)], "days": len(rows)}


def is_pdt(dt):
    """US Pacific daylight time: second Sunday of March to first Sunday of November."""
    y = dt.year
    def nth_sunday(month, n):
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        first = (6 - d.weekday()) % 7 + 1
        return datetime(y, month, first + 7 * (n - 1), 10, tzinfo=timezone.utc)
    return nth_sunday(3, 2) <= dt < nth_sunday(11, 1)

