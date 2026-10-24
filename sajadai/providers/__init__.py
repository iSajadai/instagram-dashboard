"""Data sources ("providers"): every way a page's numbers can reach the panel, behind one interface.

A provider declares who it is (id, title_fa, description_fa, tier, auth_type), what data it gives
(capabilities, from CAPABILITIES below), the credentials it needs (fields), how to test them, and how
to sync. Syncing writes either the old raw files that scripts/shape.py already reads (the fetch_*.py
scripts) or a normalised file raw/norm/<id>.json in the one shape every source maps to:

  {"source", "fetched_at", "account_days": [{day, followers, reach, engaged, profile_visits, link_taps}],
   "reels": [{shortcode, url, published, caption, views, reach, likes, comments, saves, shares, reposts,
              avg_watch, watch_total, duration, view_rate, follows, cover}],
   "posts": [...same keys + type], "stories": [{published, reach, exits, taps_back, replies}],
   "audience": {"age_gender": [...], "countries": [...], "cities": [...], "online_hours": [...]},
   "competitors": [{handle, name, followers, posts, reels: [{url, published, caption, views, likes, comments}]}]}

shape.py merges all of them field by field in TIER_ORDER (official API → analytics tools → scrapers →
files and forms), remembers which source each number came from (shown on hover) and logs numbers two
sources disagree on by more than 10%. Every sync keeps the provider's raw answers under
raw/payloads/<id>/ so they can be processed again later."""
import json, time
from datetime import datetime, timezone

from .. import config

# what a source can give, grouped as on the coverage page
CAPABILITIES = {
    "account": {"title": "حساب", "items": {"followers_daily": "فالوئر روزانه", "reach": "دسترسی (reach)", "engaged": "حساب‌های درگیر",
                                            "profile_visits": "بازدید پروفایل", "link_taps": "کلیک لینک بایو"}},
    "audience": {"title": "مخاطب", "items": {"age": "سن", "gender": "جنسیت", "country": "کشور", "city": "شهر", "online_hours": "ساعت آنلاین"}},
    "reel": {"title": "ریل", "items": {"views": "بازدید", "reel_reach": "دسترسی", "likes": "لایک", "comments": "کامنت", "saves": "ذخیره",
                                       "shares": "اشتراک", "reposts": "ری‌پست", "avg_watch": "میانگین زمان تماشا", "watch_total": "کل زمان تماشا",
                                       "duration": "مدت ویدیو", "view_rate": "ماندن ۳ ثانیه", "follows": "فالوئر از ریل",
                                       "follower_split": "فالوئر و غیرفالوئر"}},
    "content": {"title": "پست و استوری", "items": {"posts": "پست و کاروسل", "stories": "استوری (خروج، برگشت، پاسخ)"}},
    "engage": {"title": "تعامل", "items": {"comments_read": "خوندن کامنت‌ها", "comment_reply": "جواب کامنت", "dms": "دایرکت"}},
    "publish": {"title": "انتشار", "items": {"publish": "انتشار مستقیم", "schedule": "زمان‌بندی"}},
    "rivals": {"title": "رقبا", "items": {"competitors": "آمار عمومی و ریل‌های رقبا"}},
}
ALL_CAPS = [k for g in CAPABILITIES.values() for k in g["items"]]
TIER_ORDER = ["official", "analytics", "scraper", "manual"]  # who wins when two sources give the same number
TIERS = {"free": "رایگان", "freemium": "رایگان با محدودیت", "paid": "پولی", "manual": "دستی"}


class Provider:
    """One data source. Subclasses fill the class attributes and override what they support."""
    id = ""
    title_fa = ""
    description_fa = ""
    tier = "free"            # free | freemium | paid | manual (the label on the card)
    kind = "official"        # official | analytics | scraper | manual (merge priority)
    auth_type = "token"      # oauth | api_key | token | upload | none
    caps = ()                # keys of CAPABILITIES[*]["items"]
    fields = {}              # credential field → Persian label
    secret_fields = ("token", "api_key", "app_secret", "password")
    script = None            # an existing scripts/fetch_*.py that writes the old raw files
    guide = []               # step-by-step Persian instructions, one string per step
    docs = ""                # the official documentation this adapter follows
    status = "ready"         # ready | soon (no usable public API for a single creator today)
    soon_reason = ""
    min_interval = 0         # minutes between syncs (scrapers cost money; APIs have limits)
    retries = 3              # attempts per sync, with exponential backoff
    upload = None            # for file sources: accepted extensions

    def capabilities(self):
        return list(self.caps)

    def test_connection(self, creds):
        """{"ok", "account_name", "missing_permissions": [{"name", "why_fa"}], "message_fa"}"""
        return {"ok": True, "account_name": "", "missing_permissions": [], "message_fa": ""}

    def sync(self, user, creds, since=None):
        """Write raw/norm/<id>.json (or run self.script). Returns a one-line summary."""
        raise NotImplementedError

    def refresh_credentials(self, user, creds):
        """For tokens that expire: a new creds dict, or None when nothing changed."""
        return None

    def rate_limit_policy(self):
        return {"min_interval_minutes": self.min_interval, "retries": self.retries}

    def card(self):
        """What the connections page shows for this source."""
        return {"id": self.id, "title": self.title_fa, "description": self.description_fa, "tier": self.tier, "tier_fa": TIERS[self.tier],
                "kind": self.kind, "auth_type": self.auth_type, "caps": self.capabilities(), "fields": self.fields,
                "secret_fields": [f for f in self.fields if f in self.secret_fields], "guide": self.guide, "docs": self.docs,
                "status": self.status, "soon_reason": self.soon_reason, "upload": self.upload}


def norm_dir(user_id):
    return config.user_dir(user_id) / "raw" / "norm"


def write_norm(user_id, source, payload, raw=None):
    """Save a source's normalised records, and its raw answer for re-processing later (last 10 kept)."""
    d = norm_dir(user_id)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (d / f"{source}.json").write_text(json.dumps({"source": source, "fetched_at": now, **payload}, ensure_ascii=False), encoding="utf-8")
    if raw is not None:
        pdir = config.user_dir(user_id) / "raw" / "payloads" / source
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / f"{int(time.time())}.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        for old in sorted(pdir.glob("*.json"))[:-10]:
            old.unlink(missing_ok=True)
    return now


def read_norm(user_id, source):
    try:
        return json.loads((norm_dir(user_id) / f"{source}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registry():
    from . import catalog
    return catalog.PROVIDERS


def get(pid):
    return registry().get(pid)
