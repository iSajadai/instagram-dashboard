"""Paid services that collect PUBLIC Instagram data: views, likes and comments of reels, followers, and
competitors' reels. They don't have private insights (reach, saves, watch time, audience), and the cards
say so. The admin can switch the whole group off (setting scrapers_enabled).

Apify: POST https://api.apify.com/v2/acts/<actor>/run-sync-get-dataset-items with "Authorization: Bearer"
(runs over 300 s time out with 408) — https://docs.apify.com/api/v2/act-run-sync-get-dataset-items-post
  actors: apify~instagram-reel-scraper {"username": [...], "resultsLimit"} and
          apify~instagram-profile-scraper {"usernames": [...]}; fields shortCode, url, caption, timestamp,
          videoPlayCount / videoViewCount, likesCount (-1 = hidden), commentsCount, videoDuration, followersCount
Bright Data: POST https://api.brightdata.com/datasets/v3/scrape?dataset_id=… (Bearer), Instagram datasets
  profiles gd_l1vikfch901nx3by4, reels gd_lyclm20il4r5helnj — https://docs.brightdata.com/api-reference/web-scraper-api"""
import json, re, statistics, urllib.error, urllib.request
from datetime import datetime, timezone

from . import Provider, write_norm

PUBLIC_CAPS = ("followers_daily", "views", "likes", "comments", "duration", "competitors")


def post(url, token, payload, timeout=320):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:300]
        if e.code in (401, 403):
            raise RuntimeError("کلید سرویس قبول نشد (401/403)")
        if e.code == 408:
            raise RuntimeError("timeout: اجرای اسکرپر بیشتر از ۵ دقیقه طول کشید")
        if e.code == 402:
            raise RuntimeError("اعتبار حساب سرویس تموم شده (402)")
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"network: {getattr(e, 'reason', e)}")


def iso(ts):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return None


def handles_of(user, own):
    from .. import analysis, config
    hs = analysis.load(config.user_dir(user["id"]) / "content" / "competitor_handles.json") or []
    return [own.lstrip("@").lower()] + [h for h in hs if isinstance(h, str) and h.lower() != own.lower()][:10]


def summarize(reels_by, profiles, own):
    """Normalised records: the page's own reels and follower count, and competitors with their reels."""
    own = own.lower()
    out = {"reels": [], "account_days": [], "competitors": []}
    today = datetime.now(timezone.utc).date().isoformat()
    for h, rs in reels_by.items():
        recs = [{"shortcode": r["shortcode"], "url": r["url"], "published": r["published"], "caption": r["caption"], "views": r["views"],
                 "likes": r["likes"], "comments": r["comments"], "duration": r["duration"]} for r in rs if r.get("shortcode")]
        prof = profiles.get(h, {})
        if h == own:
            out["reels"] = recs
            if prof.get("followers") is not None:
                out["account_days"].append({"day": today, "followers": prof["followers"]})
        else:
            views = [r["views"] for r in recs if r.get("views")]
            out["competitors"].append({"handle": h, "name": prof.get("name") or "", "followers": prof.get("followers"), "posts": prof.get("posts"),
                                       "median_views": statistics.median(views) if views else None, "reels": recs})
    return out


class Apify(Provider):
    id = "apify"
    title_fa = "Apify (اسکرپر اینستاگرام)"
    description_fa = "بازدید، لایک و کامنت عمومی ریل‌های خودت و رقبا، و تعداد فالوئر؛ برای «تحقیق رقبا» و «تحقیق وایرال». حدود ۱٫۵ تا ۲٫۷ دلار برای هر ۱۰۰۰ نتیجه."
    tier, kind, auth_type = "paid", "scraper", "api_key"
    caps = PUBLIC_CAPS
    fields = {"api_key": "API token", "handle": "آیدی پیج خودت"}
    docs = "https://docs.apify.com/api/v2/act-run-sync-get-dataset-items-post"
    min_interval = 360  # each run costs money: at most every 6 hours
    retries = 2
    guide = ["تو apify.com حساب بساز (اعتبار رایگان ماهانه داره).", "Settings ← API & Integrations ← Personal API token رو کپی کن.",
             "توکن و آیدی پیجت رو اینجا بذار. رقیب‌ها از صفحهٔ «رقبا» خونده می‌شن (تا ۱۰ تا).",
             "این سرویس فقط دادهٔ عمومی می‌ده: دسترسی، ذخیره، زمان تماشا و مخاطب رو نداره."]

    def test_connection(self, creds):
        try:
            req = urllib.request.Request("https://api.apify.com/v2/users/me", headers={"Authorization": f"Bearer {creds.get('api_key', '')}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                me = json.load(r).get("data", {})
        except urllib.error.HTTPError as e:
            return {"ok": False, "account_name": "", "missing_permissions": [], "message_fa": f"Apify توکن رو قبول نکرد (HTTP {e.code})."}
        except (urllib.error.URLError, TimeoutError) as e:
            return {"ok": False, "account_name": "", "missing_permissions": [], "message_fa": f"به Apify وصل نشدیم: {e}"}
        return {"ok": True, "account_name": me.get("username", ""), "missing_permissions": [],
                "message_fa": f"وصل شد: حساب Apify «{me.get('username', '')}». اولین اجرا چند دقیقه طول می‌کشه."}

    def sync(self, user, creds, since=None):
        tok, own = creds["api_key"], creds["handle"].lstrip("@").lower()
        hs = handles_of(user, own)
        base = "https://api.apify.com/v2/acts/{}/run-sync-get-dataset-items"
        items = post(base.format("apify~instagram-reel-scraper"), tok, {"username": hs, "resultsLimit": 30})
        profs = post(base.format("apify~instagram-profile-scraper"), tok, {"usernames": hs})
        reels_by = {}
        for it in items or []:
            h = str(it.get("ownerUsername") or "").lower()
            views = it.get("videoPlayCount") or it.get("videoViewCount")
            likes = it.get("likesCount")
            reels_by.setdefault(h, []).append({"shortcode": it.get("shortCode"), "url": it.get("url") or f"https://www.instagram.com/reel/{it.get('shortCode')}/",
                                               "published": iso(it.get("timestamp")), "caption": it.get("caption") or "", "views": views,
                                               "likes": None if likes in (None, -1) else likes, "comments": it.get("commentsCount"),
                                               "duration": round(it["videoDuration"], 1) if it.get("videoDuration") else None})
        profiles = {str(p.get("username") or "").lower(): {"followers": p.get("followersCount"), "posts": p.get("postsCount"), "name": p.get("fullName")}
                    for p in profs or []}
        out = summarize(reels_by, profiles, own)
        write_norm(user["id"], self.id, out, raw={"reels": items, "profiles": profs})
        return f"Apify: {len(out['reels'])} ریل خودت، {len(out['competitors'])} رقیب"


class BrightData(Provider):
    id = "brightdata"
    title_fa = "Bright Data (دیتاست اینستاگرام)"
    description_fa = "دادهٔ عمومی پروفایل و ریل‌ها از Web Scraper API برایت‌دیتا؛ مثل Apify، بدون آمار خصوصی."
    tier, kind, auth_type = "paid", "scraper", "api_key"
    caps = PUBLIC_CAPS
    fields = {"api_key": "API token", "handle": "آیدی پیج خودت"}
    docs = "https://docs.brightdata.com/api-reference/web-scraper-api/synchronous-requests"
    min_interval = 360
    retries = 2
    guide = ["تو brightdata.com حساب بساز و از Account settings ← API tokens یه توکن بساز.", "توکن و آیدی پیجت رو اینجا بذار."]
    DATASETS = {"profiles": "gd_l1vikfch901nx3by4", "reels": "gd_lyclm20il4r5helnj"}

    def test_connection(self, creds):
        try:
            req = urllib.request.Request("https://api.brightdata.com/datasets/list", headers={"Authorization": f"Bearer {creds.get('api_key', '')}"})
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as e:
            return {"ok": False, "account_name": "", "missing_permissions": [], "message_fa": f"Bright Data توکن رو قبول نکرد (HTTP {e.code})."}
        except (urllib.error.URLError, TimeoutError) as e:
            return {"ok": False, "account_name": "", "missing_permissions": [], "message_fa": f"به Bright Data وصل نشدیم: {e}"}
        return {"ok": True, "account_name": "", "missing_permissions": [], "message_fa": "وصل شد. اولین اجرا چند دقیقه طول می‌کشه."}

    def sync(self, user, creds, since=None):
        tok, own = creds["api_key"], creds["handle"].lstrip("@").lower()
        hs = handles_of(user, own)
        url = "https://api.brightdata.com/datasets/v3/scrape?format=json&dataset_id="
        profs = post(url + self.DATASETS["profiles"], tok, [{"url": f"https://www.instagram.com/{h}/"} for h in hs])
        reels = post(url + self.DATASETS["reels"], tok, [{"url": f"https://www.instagram.com/{h}/reels/"} for h in hs])
        reels_by = {}
        for it in reels if isinstance(reels, list) else []:
            h = str(it.get("user_posted") or it.get("owner_username") or "").lower()
            link = it.get("url") or ""
            m = re.search(r"/(?:reels?|p)/([A-Za-z0-9_-]+)", link)
            reels_by.setdefault(h, []).append({"shortcode": m.group(1) if m else None, "url": link, "published": iso(it.get("date_posted")),
                                               "caption": it.get("description") or "", "views": it.get("views") or it.get("video_play_count"),
                                               "likes": it.get("likes"), "comments": it.get("num_comments"), "duration": it.get("length") or it.get("video_duration")})
        profiles = {str(p.get("account") or p.get("username") or "").lower(): {"followers": p.get("followers"), "posts": p.get("posts_count"), "name": p.get("full_name")}
                    for p in (profs if isinstance(profs, list) else [])}
        out = summarize(reels_by, profiles, own)
        write_norm(user["id"], self.id, out, raw={"reels": reels, "profiles": profs})
        return f"Bright Data: {len(out['reels'])} ریل خودت، {len(out['competitors'])} رقیب"


class RapidAPI(Provider):
    id = "rapidapi"
    title_fa = "RapidAPI (API‌های اینستاگرام)"
    description_fa = "سرویس‌های اینستاگرام بازار RapidAPI؛ هر کدوم شکل جوابش فرق داره."
    tier, kind, auth_type = "paid", "scraper", "api_key"
    caps = PUBLIC_CAPS
    fields = {"api_key": "API key", "handle": "آیدی پیج خودت"}
    docs = "https://rapidapi.com/search/instagram"
    status = "soon"
    soon_reason = "سرویس‌های اینستاگرام RapidAPI مال فروشنده‌های مختلفن و شکل جوابشون ثابت نیست؛ تا یکی رو قابل اتکا تأیید نکنیم فعال نمی‌شه. فعلاً Apify یا Bright Data."
