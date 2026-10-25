"""Kavenegar SMS for phone sign-in: a one-time code sent through a pre-approved «lookup» template
(sajad-register for a new account, sajad-forget for resetting the password). The API key lives in
the environment (KAVENEGAR_API_KEY), never in the database, the UI or git."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import config


class SMSError(Exception):
    """A readable Persian message shown to the user when a code can't be sent."""


def enabled() -> bool:
    return bool(config.KAVENEGAR_KEY)


def send_code(phone: str, code: str, template: str) -> bool:
    """Send `code` to `phone` (09xxxxxxxxx) via Kavenegar verify/lookup `template`. Raises SMSError."""
    if not config.KAVENEGAR_KEY:
        raise SMSError("سرویس پیامک هنوز تنظیم نشده.")
    params = urllib.parse.urlencode({"receptor": phone, "token": code, "template": template})
    url = f"https://api.kavenegar.com/v1/{config.KAVENEGAR_KEY}/verify/lookup.json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:            # Kavenegar returns JSON with the reason on 4xx
        try:
            data = json.load(e)
        except Exception:                          # noqa: BLE001
            raise SMSError(f"ارسال پیامک ناموفق بود (کد {e.code}).")
    except Exception:                              # noqa: BLE001
        raise SMSError("ارسال پیامک ناموفق بود؛ بعداً دوباره امتحان کن.")
    ret = (data or {}).get("return") or {}
    if ret.get("status") != 200:
        raise SMSError(ret.get("message") or "ارسال پیامک ناموفق بود.")
    return True
