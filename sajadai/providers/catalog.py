"""Every data source the connections page offers. Sources with a public API a single creator can use are
implemented; the others are listed as «به‌زودی» with the reason (checked against each vendor's own docs,
2026-10, see docs/PROVIDERS.md)."""
import json, urllib.error, urllib.parse, urllib.request

from . import Provider

IG = "https://graph.instagram.com/v26.0"
FB = "https://graph.facebook.com/v24.0"


def _get(url, timeout=30):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except ValueError:
            err = {}
        return None, err or {"message": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError) as e:
        return None, {"message": str(getattr(e, "reason", e))}


def _script_test(name, creds):
    from .. import pipeline
    ok, msg = pipeline.test_connection(name, creds)
    return {"ok": ok, "account_name": "", "missing_permissions": [], "message_fa": msg}


# ---------- official: Meta ----------

IG_PERMS = [  # what each permission is for, and a call that needs it
    ("instagram_business_basic", "پایه: اسم پیج، فالوئر و فهرست پست‌ها", lambda tok, ig, m: f"{IG}/me?fields=user_id,username&access_token={tok}"),
    ("instagram_business_manage_insights", "آمار: بازدید، دسترسی، زمان تماشا، مخاطب‌ها", lambda tok, ig, m: f"{IG}/{ig}/insights?metric=reach&period=day&access_token={tok}"),
    ("instagram_business_manage_comments", "خوندن و جواب دادن کامنت‌ها", lambda tok, ig, m: f"{IG}/{m}/comments?limit=1&access_token={tok}" if m else None),
    ("instagram_business_content_publish", "انتشار ریل از پنل", lambda tok, ig, m: f"{IG}/{ig}/content_publishing_limit?fields=quota_usage&access_token={tok}"),
    ("instagram_business_manage_messages", "دایرکت خودکار با کلمهٔ کلیدی", lambda tok, ig, m: f"{IG}/{ig}/conversations?platform=instagram&limit=1&access_token={tok}"),
]


def check_ig_token(tok):
    me, err = _get(f"{IG}/me?fields=user_id,username,account_type,followers_count&access_token={urllib.parse.quote(tok)}")
    if err:
        msg = "توکن منقضی یا باطل شده" if err.get("code") == 190 else err.get("message", "")
        return {"ok": False, "account_name": "", "missing_permissions": [], "message_fa": "اینستاگرام توکن رو قبول نکرد: " + msg}
    ig = me.get("user_id") or me.get("id")
    media, _ = _get(f"{IG}/me/media?fields=id&limit=1&access_token={urllib.parse.quote(tok)}")
    mid = ((media or {}).get("data") or [{}])[0].get("id")
    missing = []
    for name, why, url in IG_PERMS[1:]:
        u = url(urllib.parse.quote(tok), ig, mid)
        if not u:
            continue
        _, e = _get(u)
        if e and (e.get("code") in (10, 200, 3) or "permission" in str(e.get("message", "")).lower()):
            missing.append({"name": name, "why_fa": why})
    acct = me.get("account_type") or ""
    note = " (حساب شخصیه؛ برای آمار باید Business یا Creator باشه)" if acct and acct not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR") else ""
    return {"ok": True, "account_name": "@" + str(me.get("username")), "missing_permissions": missing, "ig_user_id": ig,
            "message_fa": f"وصل شد: @{me.get('username')}، {me.get('followers_count')} فالوئر{note}"
                          + (f". {len(missing)} دسترسی کمه." if missing else ". همهٔ دسترسی‌ها هست.")}


class InstagramLogin(Provider):
    id = "instagram"
    title_fa = "Instagram API (ورود با اینستاگرام)"
    description_fa = "API رسمی اینستاگرام بدون نیاز به صفحهٔ فیسبوک: آمار حساب و هر ریل، کامنت‌ها، انتشار و دایرکت."
    tier, kind, auth_type = "free", "official", "token"
    caps = ("followers_daily", "reach", "engaged", "profile_visits", "link_taps", "age", "gender", "country", "city", "online_hours", "views", "reel_reach", "likes",
            "comments", "saves", "shares", "reposts", "avg_watch", "watch_total", "duration", "view_rate", "posts", "stories", "comments_read",
            "comment_reply", "dms", "publish")
    fields = {"token": "توکن بلندمدت (Long-lived access token)"}
    script = "fetch_instagram.py"
    docs = "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login"
    guide = ["حساب اینستاگرامت رو حرفه‌ای کن (Business یا Creator): تنظیمات ← نوع حساب.",
             "تو developers.facebook.com یه اپ از نوع Business بساز و محصول «Instagram» رو اضافه کن.",
             "تو «API setup with Instagram login» حسابت رو به‌عنوان Instagram tester اضافه کن و تو اینستاگرام دعوت رو قبول کن.",
             "«Generate token» رو بزن و همهٔ دسترسی‌ها رو تیک بزن (basic، insights، comments، content_publish، messages).",
             "توکن رو اینجا بذار؛ پنل خودش هر ۷ روز تمدیدش می‌کنه."]

    def test_connection(self, creds):
        return check_ig_token(creds.get("token", ""))


class MetaOwnApp(InstagramLogin):
    id = "meta_app"
    title_fa = "اپ Meta خودت (توکن دستی)"
    description_fa = "برای وقتی که خودت اپ Meta ساختی و منتظر App Review نمی‌مونی: App ID، App Secret و توکن؛ پنل توکن کوتاه‌مدت رو بلندمدت می‌کنه و تمدیدش می‌کنه."
    auth_type = "token"
    fields = {"app_id": "App ID", "app_secret": "App Secret", "token": "Access token (کوتاه یا بلندمدت)"}
    guide = ["developers.facebook.com ← My Apps ← Create App ← نوع «Business».",
             "Add product ← Instagram ← «API setup with Instagram login».",
             "تو «Roles ← Instagram testers» حساب اینستاگرامت رو اضافه کن و تو اینستاگرام (تنظیمات ← وب‌سایت‌ها و اپ‌ها) دعوت رو قبول کن.",
             "از «App settings ← Basic» مقدار App ID و App Secret رو بردار.",
             "«Generate token» رو با همهٔ دسترسی‌ها بزن و هر سه مقدار رو اینجا بذار. توکن کوتاه‌مدت خودکار ۶۰ روزه می‌شه.",
             "تا وقتی اپ «Live» نشده فقط حساب‌های tester کار می‌کنن؛ برای حساب خودت همین کافیه."]

    def exchange(self, creds):
        """Short-lived → long-lived (60 days) with the app secret: GET graph.instagram.com/access_token?grant_type=ig_exchange_token
        https://developers.facebook.com/docs/instagram-platform/reference/access_token"""
        q = urllib.parse.urlencode({"grant_type": "ig_exchange_token", "client_secret": creds.get("app_secret", ""), "access_token": creds.get("token", "")})
        r, err = _get(f"https://graph.instagram.com/access_token?{q}")
        return (r or {}).get("access_token"), err

    def test_connection(self, creds):
        long_tok, err = self.exchange(creds)
        res = check_ig_token(long_tok or creds.get("token", ""))
        if long_tok:
            res["new_creds"] = {**creds, "token": long_tok}
            res["message_fa"] += " توکن به بلندمدت (۶۰ روزه) تبدیل شد."
        elif err and "secret" in str(err.get("message", "")).lower():
            res["message_fa"] += " (App Secret قبول نشد؛ توکن همون‌طوری ذخیره می‌شه.)"
        return res

    def sync(self, user, creds, since=None):
        return None  # fetch_instagram.py with this token (pipeline passes it as the instagram source)


class FacebookGraph(Provider):
    id = "facebook"
    title_fa = "Instagram API (ورود با فیسبوک)"
    description_fa = "برای حساب‌هایی که به صفحهٔ فیسبوک وصلن: Business Discovery برای آمار عمومی رقبا."
    tier, kind, auth_type = "free", "official", "token"
    caps = ("competitors",)
    fields = {"token": "توکن کاربر یا صفحه (Facebook Login)"}
    script = "fetch_discovery.py"
    docs = "https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/business-discovery"
    guide = ["اینستاگرام حرفه‌ای رو تو Meta Business Suite به یه صفحهٔ فیسبوک وصل کن.",
             "تو Graph API Explorer اپت رو انتخاب کن و دسترسی‌های instagram_basic، instagram_manage_insights و pages_read_engagement رو بگیر.",
             "توکن رو (ترجیحاً بلندمدت) اینجا بذار و تو صفحهٔ «رقبا» آیدی رقیب‌ها رو بنویس."]

    def test_connection(self, creds):
        return _script_test("facebook", creds)


class Webhooks(Provider):
    id = "webhooks"
    title_fa = "Webhooks اینستاگرام (کامنت و دایرکت لحظه‌ای)"
    description_fa = "با Webhook، کامنت تازه همون لحظه به پنل می‌رسه و دایرکت خودکار با کلمهٔ کلیدی به‌جای هر ۱۰ دقیقه، چند ثانیه‌ای فرستاده می‌شه."
    tier, kind, auth_type = "free", "official", "token"
    caps = ("comments_read", "dms")
    fields = {"app_secret": "App Secret اپ Meta (برای امضای پیام‌ها)"}
    docs = "https://developers.facebook.com/docs/instagram-platform/webhooks"
    guide = ["تو اپ Meta: Instagram ← Webhooks ← «Callback URL» رو همین آدرسی بذار که پایین این کارت نوشته شده، و «Verify token» رو هم از همین‌جا کپی کن.",
             "فیلدهای comments و messages رو Subscribe کن.",
             "App Secret اپ رو اینجا بذار تا پنل فقط پیام‌های امضاشده توسط Meta رو قبول کنه.",
             "نکته: Meta برای Webhook کامنت‌ها «Advanced Access» و اپِ Live می‌خواد؛ تا اون موقع پنل هر ۱۰ دقیقه خودش چک می‌کنه."]

    def test_connection(self, creds):
        ok = len(creds.get("app_secret", "")) >= 16
        return {"ok": ok, "account_name": "", "missing_permissions": [],
                "message_fa": "ذخیره شد؛ حالا Callback URL و Verify token رو تو اپ Meta بذار." if ok else "App Secret معتبر نیست."}


# ---------- analytics tools ----------

class Metricool(Provider):
    id = "metricool"
    title_fa = "Metricool (API)"
    description_fa = "اتصال مستقیم به API متریکول: ریل‌ها، فالوئر روزانه، بهترین ساعت و رقبا."
    tier, kind, auth_type = "paid", "analytics", "api_key"
    caps = ("followers_daily", "reach", "views", "reel_reach", "likes", "comments", "saves", "shares", "reposts", "avg_watch", "view_rate",
            "posts", "stories", "age", "gender", "country", "competitors", "schedule")
    fields = {"token": "API token", "user_id": "userId", "blog_id": "blogId (brand)"}
    script = "fetch_metricool.py"
    docs = "https://app.metricool.com/resources/apidocs/index.html"
    guide = ["API متریکول فقط تو پلن Advanced و بالاتره.",
             "تو Metricool: تنظیمات حساب ← API ← توکن رو بساز.",
             "userId و blogId رو از آدرس صفحهٔ برند (…?blogId=…&userId=…) بردار و هر سه رو اینجا بذار."]

    def test_connection(self, creds):
        return _script_test("metricool", creds)


class Routine(Provider):
    id = "routine"
    title_fa = "Metricool از راه روتین Claude"
    description_fa = "روتینی تو claude.ai هر ۶ ساعت با کانکتور Metricool داده رو می‌خونه و تو یه مخزن git می‌ذاره؛ پنل هر ۱۵ دقیقه از اونجا برمی‌داره. API پلن Advanced لازم نیست."
    tier, kind, auth_type = "freemium", "analytics", "token"
    caps = ("followers_daily", "reach", "views", "reel_reach", "likes", "comments", "saves", "shares", "reposts", "avg_watch", "view_rate",
            "stories", "age", "gender", "country", "competitors")
    fields = {"repo": "مخزن (owner/name)", "branch": "شاخه"}
    secret_fields = ()
    script = "fetch_repo.py"
    docs = "https://docs.claude.com/en/docs/claude-code/routines"
    guide = ["تو claude.ai کانکتور Metricool رو وصل کن.",
             "یه روتین بساز که هر ۶ ساعت داده‌ها رو بخونه و تو مخزن (raw/*.json) commit کنه (نمونهٔ دستورش تو docs).",
             "کلید فقط‌خواندنی پنل (پایین همین کارت) رو تو تنظیمات مخزن ← Deploy keys اضافه کن.",
             "اسم مخزن و شاخه رو اینجا بذار."]

    def test_connection(self, creds):
        return _script_test("routine", creds)


class Buffer(Provider):
    id = "buffer"
    title_fa = "Buffer"
    description_fa = "آمار ریل‌ها و پست‌ها از Buffer، به‌علاوهٔ فالوئر از هر ریل؛ زمان‌بندی هم از کارت بُرد."
    tier, kind, auth_type = "freemium", "analytics", "api_key"
    caps = ("views", "reel_reach", "likes", "comments", "saves", "shares", "follows", "posts", "schedule")
    fields = {"api_key": "API key"}
    script = "fetch_buffer.py"
    docs = "https://developers.buffer.com/"
    guide = ["اینستاگرام رو تو Buffer به‌عنوان Channel وصل کن.", "تو Buffer: Settings ← API ← یه کلید بساز و اینجا بذار."]

    def test_connection(self, creds):
        return _script_test("buffer", creds)


def soon(pid, title, desc, tier, kind, caps, reason, docs):
    cls = type(pid, (Provider,), {"id": pid, "title_fa": title, "description_fa": desc, "tier": tier, "kind": kind, "auth_type": "oauth",
                                  "caps": caps, "status": "soon", "soon_reason": reason, "docs": docs})
    return cls()


# ---------- files and forms ----------

class ExportFile(Provider):
    id = "export_csv"
    title_fa = "خروجی Meta Business Suite یا داشبورد حرفه‌ای"
    description_fa = "فایل CSV یا XLSX «محتوا» رو از Meta Business Suite (یا Professional Dashboard) بگیر و اینجا آپلود کن؛ ستون‌های فارسی و انگلیسی هر دو شناخته می‌شن."
    tier, kind, auth_type = "manual", "manual", "upload"
    caps = ("views", "reel_reach", "likes", "comments", "saves", "shares", "follows", "duration", "avg_watch", "posts")
    fields = {}
    upload = ".csv,.xlsx"
    docs = "https://www.facebook.com/business/help/1694926080650543"
    guide = ["business.facebook.com ← Insights ← Content.", "بازهٔ زمانی و نوع (Reels) رو انتخاب کن و «Export data» ← CSV.", "فایل رو همین‌جا آپلود کن."]


class DyiJson(Provider):
    id = "dyi_json"
    title_fa = "«Download your information» اینستاگرام (JSON)"
    description_fa = "کپشن و تاریخ همهٔ ریل‌ها و پست‌ها و تعداد فالوئر؛ آمار بازدید توش نیست."
    tier, kind, auth_type = "manual", "manual", "upload"
    caps = ("posts",)
    fields = {}
    upload = ".zip,.json"
    docs = "https://help.instagram.com/181231772500920"
    guide = ["اینستاگرام ← Accounts Center ← Your information and permissions ← Download your information.",
             "قالب JSON و بخش‌های «Content» و «Followers and following» رو انتخاب کن.", "فایل zip رو اینجا آپلود کن."]


class Screenshot(Provider):
    id = "screenshot"
    title_fa = "اسکرین‌شات Insights ریل"
    description_fa = "از صفحهٔ آمار هر ریل اسکرین‌شات بگیر؛ هوش مصنوعی عددها رو می‌خونه و قبل از ذخیره خودت تأییدشون می‌کنی."
    tier, kind, auth_type = "manual", "manual", "upload"
    caps = ("views", "reel_reach", "likes", "comments", "saves", "shares", "follows", "avg_watch", "watch_total", "view_rate")
    fields = {}
    upload = ".png,.jpg,.jpeg,.webp"
    guide = ["تو اینستاگرام ریل رو باز کن ← «View insights».", "از هر صفحهٔ آمار اسکرین‌شات بگیر (تا ۴ تا با هم).",
             "لینک ریل رو بنویس و عکس‌ها رو آپلود کن؛ عددهای پیشنهادی رو چک و ذخیره کن. (هوش مصنوعی باید وصل باشه.)"]


class ManualForm(Provider):
    id = "manual"
    title_fa = "ورود دستی"
    description_fa = "لینک ریل و عددهاش رو خودت بنویس؛ کاور و کپشن از منبع‌های وصل‌شده پر می‌شه."
    tier, kind, auth_type = "manual", "manual", "none"
    caps = ("views", "reel_reach", "likes", "comments", "saves", "shares", "follows", "avg_watch", "duration", "view_rate")
    fields = {}


def _build():
    from .scrapers import Apify, BrightData, RapidAPI
    items = [InstagramLogin(), MetaOwnApp(), FacebookGraph(), Webhooks(), Metricool(), Routine(), Buffer()]
    items += _analytics_soon()
    items += [Apify(), BrightData(), RapidAPI(), ExportFile(), DyiJson(), Screenshot(), ManualForm()]
    return {p.id: p for p in items}


def _analytics_soon():
    from .third_party import SOON
    return [soon(*row) for row in SOON]


PROVIDERS = _build()
