"""Where things live and the few settings that come from the environment (everything else is set
in the panel and kept in the database)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent           # the repo: index.html, assets/, scripts/, content/
DATA_DIR = Path(os.environ.get("SAJADAI_DATA_DIR", ROOT / "var")).resolve()
DB_PATH = DATA_DIR / "panel.db"
USERS_DIR = DATA_DIR / "users"
SCRIPTS = ROOT / "scripts"
PANEL = ROOT / "panel"                                   # login / settings / admin pages

# the public address, used in links (Telegram, MCP instructions); the panel's admin settings can override it
PUBLIC_URL = os.environ.get("SAJADAI_PUBLIC_URL", "").rstrip("/")
# set to 1 behind HTTPS so session cookies are Secure
SECURE_COOKIES = os.environ.get("SAJADAI_SECURE_COOKIES", "0") == "1"
# 0 turns off the scheduler (e.g. for a second replica, or tests)
SCHEDULER = os.environ.get("SAJADAI_SCHEDULER", "1") == "1"

REFRESH_HOURS = 6
SESSION_DAYS = 30

# Kavenegar SMS: phone sign-in with a one-time code. The API key comes from the environment,
# never the database or git. Templates are the Kavenegar "lookup" (verify) templates.
KAVENEGAR_KEY = os.environ.get("KAVENEGAR_API_KEY", "").strip()
SMS_REGISTER_TEMPLATE = os.environ.get("SAJADAI_SMS_REGISTER_TEMPLATE", "sajad-register").strip()
SMS_FORGET_TEMPLATE = os.environ.get("SAJADAI_SMS_FORGET_TEMPLATE", "sajad-forget").strip()


def user_dir(user_id: int) -> Path:
    return USERS_DIR / str(int(user_id))
