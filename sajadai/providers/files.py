"""Sources for pages without any API: the official exports (Meta Business Suite / Professional Dashboard
CSV or XLSX; Instagram's "Download your information" JSON), a screenshot of a reel's Insights read by a
vision model (the numbers are confirmed by the user before saving), and a plain form.

Column names are matched loosely (English or Persian, any case, extra words around them), so a renamed or
translated export still maps."""
import csv, io, json, re, zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

from ..fa.text import latin_digits

# each normalised field → words that name it in an export's header (English, then Persian)
COLUMNS = {
    "url": ["permalink", "link", "url", "پیوند", "لینک"],
    "shortcode": ["shortcode"],
    "post_id": ["post id", "media id", "شناسه"],
    "caption": ["description", "caption", "title", "توضیحات", "کپشن", "عنوان"],
    "published": ["publish time", "published", "date", "time", "created", "زمان انتشار", "تاریخ"],
    "type": ["post type", "media type", "type", "نوع"],
    "duration": ["duration", "مدت"],
    "views": ["views", "plays", "video views", "بازدید", "پخش"],
    "reach": ["reach", "accounts reached", "دسترسی"],
    "likes": ["likes", "reactions", "لایک", "پسند"],
    "comments": ["comments", "کامنت", "دیدگاه", "نظر"],
    "shares": ["shares", "اشتراک"],
    "saves": ["saves", "saved", "ذخیره"],
    "follows": ["follows", "new followers", "فالو", "دنبال"],
    "avg_watch": ["average watch time", "avg watch", "میانگین زمان تماشا", "میانگین تماشا"],
    "watch_total": ["watch time", "total watch", "زمان تماشا", "کل تماشا"],
}
NUMERIC = {"duration", "views", "reach", "likes", "comments", "shares", "saves", "follows", "avg_watch", "watch_total"}


def match_columns(header):
    """{field: column index} for a header row; the longest matching name wins, each column used once."""
    names = [latin_digits(str(h or "")).strip().lower() for h in header]
    out, used = {}, set()
    cands = sorted(((len(w), f, w) for f, ws in COLUMNS.items() for w in ws), reverse=True)
    for _, f, w in cands:
        if f in out:
            continue
        for i, n in enumerate(names):
            if i not in used and (n == w or w in n):
                if f == "watch_total" and ("average" in n or "میانگین" in n):
                    continue
                out[f] = i
                used.add(i)
                break
    return out


def number(v):
    s = latin_digits(str(v or "")).replace(",", "").replace("٬", "").replace("٫", ".").strip()
    if not s or s in ("-", "--"):
        return None
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([kKmM]|هزار|میلیون)?", s)
    if not m:
        return None
    n = float(m.group(1))
    n *= {"k": 1e3, "K": 1e3, "هزار": 1e3, "m": 1e6, "M": 1e6, "میلیون": 1e6}.get(m.group(2) or "", 1)
    return int(n) if n.is_integer() else round(n, 2)


def when(v):
    s = latin_digits(str(v or "")).strip()
    for fmt in ("%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            d = datetime.strptime(s[:25], fmt)
            if d.tzinfo:
                d = d.astimezone(timezone.utc).replace(tzinfo=None)
            return d.isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def shortcode(url):
    m = re.search(r"/(?:reels?|p|tv)/([A-Za-z0-9_-]+)", str(url or ""))
    return m.group(1) if m else ""


def rows_from(data, name):
    """Rows of a CSV (any encoding Meta uses) or the first sheet of an XLSX."""
    if name.lower().endswith(".xlsx") or data[:2] == b"PK":
        return xlsx_rows(data)
    for enc in ("utf-8-sig", "utf-16", "cp1256"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("کدگذاری فایل شناخته نشد؛ از CSV با UTF-8 استفاده کن.")
    dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t") if text.strip() else csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def xlsx_rows(data):
    """The first worksheet of an .xlsx, without a spreadsheet library (shared strings + inline values)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheet = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))[0]
        rows = []
        for r in ElementTree.fromstring(z.read(sheet)).iter("{%s}row" % ns["m"]):
            row = {}
            for c in r.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", c.get("r", "A")).group(1)
                col = 0
                for ch in ref:
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                is_ = c.find("m:is", ns)
                if c.get("t") == "s" and v is not None:
                    val = shared[int(v.text)]
                elif is_ is not None:
                    val = "".join(t.text or "" for t in is_.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else ""
                row[col - 1] = val
            rows.append([row.get(i, "") for i in range(max(row) + 1)] if row else [])
        return rows


def parse_export(data, name):
    """Reels and posts from a Meta Business Suite / Professional Dashboard export."""
    rows = [r for r in rows_from(data, name) if any(str(c).strip() for c in r)]
    head_i = next((i for i, r in enumerate(rows[:10]) if len(match_columns(r)) >= 3), None)
    if head_i is None:
        raise ValueError("ستون‌های فایل شناخته نشد؛ خروجی «محتوا» از Meta Business Suite یا داشبورد حرفه‌ای اینستاگرام رو بذار.")
    cols = match_columns(rows[head_i])
    if "views" not in cols and "reach" not in cols and "likes" not in cols:
        raise ValueError("تو این فایل ستون بازدید، دسترسی یا لایک پیدا نشد.")
    reels, posts = [], []
    for r in rows[head_i + 1:]:
        rec = {}
        for f, i in cols.items():
            v = r[i] if i < len(r) else ""
            rec[f] = number(v) if f in NUMERIC else when(v) if f == "published" else str(v).strip()
        code = rec.get("shortcode") or shortcode(rec.get("url"))
        if not code:
            continue
        rec["shortcode"] = code
        rec.pop("post_id", None)
        kind = str(rec.pop("type", "") or "").lower()
        if "reel" in kind or "ریل" in kind or (not kind and rec.get("duration")) or "/reel/" in str(rec.get("url")):
            reels.append({k: v for k, v in rec.items() if v not in (None, "")})
        else:
            posts.append({**{k: v for k, v in rec.items() if v not in (None, "")}, "type": kind or "post"})
    if not reels and not posts:
        raise ValueError("هیچ ردیفی با لینک پست پیدا نشد.")
    return {"reels": reels, "posts": posts}


def parse_dyi(data, name):
    """Instagram's "Download your information" (JSON, zipped or one file): the page's own reels and posts
    (caption and date; the export has no view counts) and the follower count from the followers list."""
    files = {}
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.endswith(".json") and ("content/" in n or "followers" in n):
                    files[n] = json.loads(z.read(n).decode("utf-8", errors="replace"))
    else:
        files[name] = json.loads(data.decode("utf-8-sig"))
    reels, posts, followers = [], [], None

    def fix(s):  # Instagram writes UTF-8 as latin-1 escapes
        try:
            return s.encode("latin-1").decode("utf-8")
        except (UnicodeError, AttributeError):
            return s
    for n, d in files.items():
        low = n.lower()
        if "followers" in low and isinstance(d, list):
            followers = (followers or 0) + len(d)
            continue
        items = d.get("ig_reels_media", d.get("ig_reels", d)) if isinstance(d, dict) else d
        if not isinstance(items, list):
            continue
        for it in items:
            media = (it.get("media") or [it]) if isinstance(it, dict) else []
            for m in media:
                ts = m.get("creation_timestamp") or it.get("creation_timestamp")
                rec = {"caption": fix(m.get("title") or it.get("title") or ""),
                       "published": datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") if ts else None,
                       "media_uri": m.get("uri")}
                if "reel" in low:
                    reels.append(rec)
                else:
                    posts.append(rec)
    if not reels and not posts and followers is None:
        raise ValueError("تو این فایل پست، ریل یا فهرست فالوئر پیدا نشد؛ «Download your information» رو با قالب JSON بگیر.")
    return {"reels": reels, "posts": posts, "followers": followers}


SCREENSHOT_SCHEMA = {"type": "object", "additionalProperties": False,
                     "required": ["views", "reach", "likes", "comments", "shares", "saves", "follows", "avg_watch_seconds", "watch_total_seconds", "view_rate_pct", "notes"],
                     "properties": {k: {"type": ["number", "null"]} for k in ("views", "reach", "likes", "comments", "shares", "saves", "follows",
                                                                            "avg_watch_seconds", "watch_total_seconds", "view_rate_pct")}
                     | {"notes": {"type": "string"}}}
SCREENSHOT_SYSTEM = """You read a screenshot of an Instagram reel's Insights screen (English or Persian UI, light or dark) and return
the numbers you can actually see. Views/plays, accounts reached, likes, comments, shares, saves, follows, average watch time
(convert to seconds), watch time total (convert to seconds), and "skip rate"/"view rate" as the percent who watched past 3
seconds (if the screen shows a skip rate S%, view_rate_pct = 100 − S). Persian digits and «هزار»/K/M count as numbers.
Use null for anything not visible. Never guess. notes: one short Persian sentence on what was hard to read, or ""."""


def read_screenshot(user, images):
    """The numbers a vision model sees on Insights screenshots; the user confirms them before they're saved."""
    from .. import ai
    out = ai.ask(user, SCREENSHOT_SYSTEM, [{"role": "user", "content": "اعداد این اسکرین‌شات(ها) رو بخون."}], schema=SCREENSHOT_SCHEMA,
                 max_tokens=1500, effort="low", images=images)
    return {"views": out.get("views"), "reach": out.get("reach"), "likes": out.get("likes"), "comments": out.get("comments"),
            "shares": out.get("shares"), "saves": out.get("saves"), "follows": out.get("follows"), "avg_watch": out.get("avg_watch_seconds"),
            "watch_total": out.get("watch_total_seconds"), "view_rate": out.get("view_rate_pct"), "notes": out.get("notes") or ""}
