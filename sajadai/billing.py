"""Subscriptions, off unless the admin turns them on: plans with a price, a length and limits (how many
pages, whether the panel's shared AI key may be used), and payment through Zarinpal (v4 REST API).
With billing off everybody gets everything, as before. A user's own AI key always works."""
import json, time, urllib.error, urllib.request

from . import store

DEFAULT_PLANS = [
    {"id": "pro-1m", "name": "حرفه‌ای یک‌ماهه", "price": 290000, "days": 31, "max_pages": 3, "ai": True},
    {"id": "pro-3m", "name": "حرفه‌ای سه‌ماهه", "price": 790000, "days": 93, "max_pages": 3, "ai": True},
]
FREE = {"id": "free", "name": "رایگان", "price": 0, "days": 0, "max_pages": 1, "ai": False}
HOSTS = {False: "https://payment.zarinpal.com", True: "https://sandbox.zarinpal.com"}


class PayError(Exception):
    pass


def config():
    c = store.setting("billing", {}) or {}
    return {"enabled": bool(c.get("enabled")), "merchant": c.get("merchant", ""), "sandbox": bool(c.get("sandbox")),
            "plans": c.get("plans") or DEFAULT_PLANS, "free_pages": int(c.get("free_pages") or 1)}


def person_of(user):
    """Whose subscription covers this row: an extra page is paid for by the person who made it."""
    if user["kind"] == "page" and user["owner_id"]:
        return store.get_user(user["owner_id"]) or user
    return user


def plan_for(user):
    """The plan in force for a user or page: their paid plan while it lasts, else the free one."""
    c = config()
    p = store.prefs(person_of(user))
    plan = next((x for x in c["plans"] if x["id"] == p.get("plan_id")), None)
    if plan and (p.get("plan_until") or 0) > time.time():
        return {**plan, "until": p["plan_until"]}
    return {**FREE, "max_pages": c["free_pages"], "until": None}


def may_use_panel_ai(user):
    return not config()["enabled"] or plan_for(user)["ai"]


def max_pages(user, default):
    return plan_for(user)["max_pages"] if config()["enabled"] else default


# ---------- Zarinpal ----------

def _post(path, body, sandbox):
    req = urllib.request.Request(HOSTS[sandbox] + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "sajadai-dashboard"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # Zarinpal answers errors with 4xx and a JSON body
        try:
            return json.load(e)
        except ValueError:
            raise PayError(f"زرین‌پال جواب نداد (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError):
        raise PayError("به زرین‌پال وصل نشد")


def _err(out):
    e = out.get("errors") or {}
    return (e.get("message") if isinstance(e, dict) else None) or "خطای زرین‌پال"


def start(user, plan_id, callback_url):
    """Open a payment for a plan; returns the gateway URL to send the browser to."""
    c = config()
    if not c["enabled"] or not c["merchant"]:
        raise PayError("پرداخت فعال نیست")
    plan = next((x for x in c["plans"] if x["id"] == plan_id and x.get("price")), None)
    if not plan:
        raise PayError("این پلن وجود نداره")
    person = person_of(user)
    out = _post("/pg/v4/payment/request.json", {
        "merchant_id": c["merchant"], "amount": int(plan["price"]), "currency": "IRT", "callback_url": callback_url,
        "description": f"اشتراک {plan['name']} داشبورد اینستاگرام ({person['username']})"}, c["sandbox"])
    data = out.get("data") or {}
    if data.get("code") != 100 or not data.get("authority"):
        raise PayError(_err(out))
    store.add_payment(person["id"], plan["id"], int(plan["price"]), data["authority"])
    return f"{HOSTS[c['sandbox']]}/pg/StartPay/{data['authority']}"


def finish(authority, status):
    """The gateway's return: verify the payment and extend the plan. Returns (ok, message)."""
    pay = store.payment(authority)
    if not pay:
        return False, "پرداخت پیدا نشد"
    if pay["status"] == "paid":
        return True, "این پرداخت قبلاً ثبت شده"
    if status != "OK":
        store.update_payment(authority, "canceled")
        return False, "پرداخت انجام نشد یا لغو شد"
    if not store.claim_payment(authority):  # a second tab or a reload is already verifying this one
        return False, "این پرداخت در حال بررسیه؛ چند ثانیه بعد صفحه رو تازه کن"
    c = config()
    out = _post("/pg/v4/payment/verify.json", {"merchant_id": c["merchant"], "amount": pay["amount"], "authority": authority}, c["sandbox"])
    data = out.get("data") or {}
    if data.get("code") not in (100, 101):
        store.update_payment(authority, "failed")
        return False, _err(out)
    plan = next((x for x in c["plans"] if x["id"] == pay["plan_id"]), None)
    person = store.get_user(pay["user_id"])
    if plan and person:
        p = store.prefs(person)
        base = max(p.get("plan_until") or 0, time.time()) if p.get("plan_id") == plan["id"] else time.time()  # renewing adds on
        p.update(plan_id=plan["id"], plan_until=base + plan["days"] * 86400)
        store.set_prefs(person["id"], p)
    store.update_payment(authority, "paid", str(data.get("ref_id") or ""))
    return True, f"پرداخت موفق بود؛ کد پیگیری {data.get('ref_id')}"
