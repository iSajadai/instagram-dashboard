"""Link in bio: a public page at /l/<slug> with the page's links, each going through /l/<slug>/<id> so the
panel counts the click before redirecting. Views and clicks are kept per day (content/bio_stats.json)
for the stats in settings. Bots and link previews aren't counted."""
import html, json, re, secrets, threading, time
from datetime import datetime, timedelta, timezone

from . import analysis, config, store

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,29}$")
URL = re.compile(r"^https?://[^\s<>\"']{3,1000}$", re.I)
BOT = re.compile(r"bot|crawl|spider|preview|facebookexternalhit|whatsapp|telegram|slack|discord|curl|wget|python|headless", re.I)
TEHRAN = timezone(timedelta(hours=3, minutes=30))
MAX_LINKS = 12
_lock = threading.Lock()
_slugs = {}  # slug → user id, rebuilt when a bio is saved


def path(user_id, name):
    return config.user_dir(user_id) / "content" / name


def load(user_id):
    b = analysis.load(path(user_id, "bio.json"))
    return b if isinstance(b, dict) else {"enabled": False, "slug": "", "title": "", "text": "", "links": [], "utm": True}


def save(user_id, b):
    p = path(user_id, "bio.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    _slugs.clear()


def owner(slug):
    if not _slugs:
        for u in store.users():
            b = load(u["id"])
            if b.get("enabled") and b.get("slug"):
                _slugs[b["slug"]] = u["id"]
    return _slugs.get(slug)


def clean(b, uid):
    """Validate what settings sent. Raises ValueError with a message for the user."""
    slug = str(b.get("slug") or "").strip().lower()
    on = bool(b.get("enabled"))
    if on and not SLUG.match(slug):
        raise ValueError("آدرس صفحه: ۳ تا ۳۰ حرف انگلیسی کوچک، عدد یا خط تیره")
    if on and owner(slug) not in (None, uid):
        raise ValueError("این آدرس رو یکی دیگه برداشته")
    old = {l["id"]: l for l in load(uid).get("links", [])}
    links = []
    for i, l in enumerate((b.get("links") or [])[:MAX_LINKS]):
        title, url = str(l.get("title") or "").strip()[:80], str(l.get("url") or "").strip()
        if not title and not url:
            continue
        if not title or not URL.match(url):
            raise ValueError(f"لینک {i + 1}: عنوان و یه آدرس کامل (با https://) لازمه")
        lid = str(l.get("id") or "")
        if not re.fullmatch(r"[a-z0-9]{4,12}", lid) or lid in {x["id"] for x in links}:
            lid = secrets.token_hex(4)
        links.append({"id": lid, "title": title, "url": url, "highlight": bool(l.get("highlight")), "created": (old.get(lid) or {}).get("created") or int(time.time())})
    return {"enabled": on, "slug": slug, "title": str(b.get("title") or "").strip()[:60], "text": str(b.get("text") or "").strip()[:300],
            "handle": str(b.get("handle") or "").strip().lstrip("@")[:40], "utm": b.get("utm", True) is not False, "links": links}


def count(user_id, what, user_agent):
    """what: "view" or a link id."""
    if not user_agent or BOT.search(user_agent):
        return
    day = datetime.now(TEHRAN).date().isoformat()
    with _lock:
        p = path(user_id, "bio_stats.json")
        s = analysis.load(p)
        s = s if isinstance(s, dict) else {}
        key = "views" if what == "view" else "clicks"
        bucket = s.setdefault(key, {})
        if key == "views":
            bucket[day] = bucket.get(day, 0) + 1
        else:
            per = bucket.setdefault(what, {})
            per[day] = per.get(day, 0) + 1
        cutoff = (datetime.now(TEHRAN).date() - timedelta(days=120)).isoformat()  # keep four months
        s["views"] = {d: n for d, n in s.get("views", {}).items() if d >= cutoff}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s), encoding="utf-8")


def stats(user_id):
    s = analysis.load(path(user_id, "bio_stats.json"))
    s = s if isinstance(s, dict) else {}
    today = datetime.now(TEHRAN).date()

    def total(per_day, days):
        since = (today - timedelta(days=days - 1)).isoformat()
        return sum(n for d, n in (per_day or {}).items() if d >= since)
    views = s.get("views", {})
    out = {"views_7": total(views, 7), "views_30": total(views, 30), "links": {},
           "daily": [{"day": (today - timedelta(days=i)).isoformat(), "views": views.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(29, -1, -1)]}
    for lid, per in s.get("clicks", {}).items():
        out["links"][lid] = {"clicks_7": total(per, 7), "clicks_30": total(per, 30)}
    return out


def target(b, link):
    """The address a click goes to, with UTM tags so the click shows up in the site's analytics."""
    url = link["url"]
    if b.get("utm", True) and "utm_" not in url:
        url += ("&" if "?" in url else "?") + "utm_source=instagram&utm_medium=bio&utm_campaign=" + b.get("slug", "")
    return url


def render(b, slug):
    e = html.escape
    links = "".join(
        f'<a class="l{" hi" if l.get("highlight") else ""}" href="/l/{e(slug)}/{e(l["id"])}" rel="noopener">{e(l["title"])}</a>' for l in b.get("links", []))
    handle = b.get("handle") or ""
    initials = e((b.get("title") or handle or slug)[:2])
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(b.get("title") or handle or slug)}</title>
<meta name="description" content="{e(b.get("text") or "")}">
<meta property="og:title" content="{e(b.get("title") or handle or slug)}">
<link rel="icon" href="/assets/images/favicon.svg" type="image/svg+xml">
<style>
@font-face {{ font-family: "Vazirmatn"; src: url("/assets/vazirmatn.woff2") format("woff2"); font-weight: 100 900; font-display: swap; }}
:root {{ --bg: #f2f4f8; --card: #fff; --text: #16181d; --muted: #5f6470; --accent: #0062d6; --border: rgba(0,0,0,.08); }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #0f1115; --card: #1a1d24; --text: #f2f3f5; --muted: #a6abb5; --accent: #64b5ff; --border: rgba(255,255,255,.1); }} }}
* {{ box-sizing: border-box; letter-spacing: 0; }}
body {{ margin: 0; min-height: 100dvh; font-family: Vazirmatn, Tahoma, sans-serif; background: var(--bg); color: var(--text); line-height: 1.8;
  display: flex; justify-content: center; padding: 48px 16px; }}
main {{ width: min(30rem, 100%); display: flex; flex-direction: column; align-items: center; gap: 12px; text-align: center; }}
.av {{ width: 88px; height: 88px; border-radius: 50%; display: grid; place-items: center; font-size: 30px; font-weight: 800; color: #fff;
  background: linear-gradient(135deg, #f58529, #dd2a7b 50%, #515bd4); }}
h1 {{ margin: 4px 0 0; font-size: 1.375rem; }}
.h {{ color: var(--muted); text-decoration: none; direction: ltr; font-size: .9375rem; }}
p {{ margin: 0 0 12px; color: var(--muted); font-size: .9375rem; }}
.l {{ display: flex; align-items: center; justify-content: center; width: 100%; min-height: 56px; padding: 12px 16px; border-radius: 16px; text-decoration: none;
  color: var(--text); background: var(--card); border: 1px solid var(--border); font-weight: 600; font-size: 1rem; transition: transform .16s; }}
.l:hover {{ transform: translateY(-1px); border-color: var(--accent); }}
.l:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.l.hi {{ background: var(--accent); color: #fff; border-color: transparent; }}
footer {{ margin-top: 24px; font-size: .8125rem; color: var(--muted); }}
@media (prefers-reduced-motion: reduce) {{ .l {{ transition: none; }} }}
</style>
</head>
<body>
<main>
  <div class="av" aria-hidden="true">{initials}</div>
  <h1>{e(b.get("title") or handle or slug)}</h1>
  {f'<a class="h" href="https://www.instagram.com/{e(handle)}/" rel="noopener">@{e(handle)}</a>' if handle else ''}
  {f'<p>{e(b["text"])}</p>' if b.get("text") else ''}
  {links or '<p>هنوز لینکی گذاشته نشده.</p>'}
  <footer>ساخته‌شده با داشبورد اینستاگرام</footer>
</main>
</body>
</html>"""
