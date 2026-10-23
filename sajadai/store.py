"""SQLite storage: users, sessions and panel settings. Keys and tokens a user enters (Metricool,
Buffer, Instagram, AI) are encrypted with a server key before they're written."""
import base64, hashlib, hmac, json, os, secrets, sqlite3, threading, time

from cryptography.fernet import Fernet, InvalidToken

from . import config

_lock = threading.RLock()
_db = None
_fernet = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL COLLATE NOCASE,
  pw TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  prefs TEXT NOT NULL DEFAULT '{}',      -- not secret: profile, Telegram chat, AI provider/model
  secrets TEXT NOT NULL DEFAULT '',      -- encrypted JSON: connection keys and the user's own AI key
  api_token TEXT,                        -- sha256 of the user's API/MCP token
  status TEXT NOT NULL DEFAULT '{}'      -- last refresh / content run and their output
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,                -- sha256 of the cookie value
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL                    -- encrypted JSON
);
"""


def db():
    global _db
    with _lock:
        if _db is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(config.DATA_DIR, 0o700)
            _db = sqlite3.connect(config.DB_PATH, check_same_thread=False, isolation_level=None)
            _db.row_factory = sqlite3.Row
            _db.execute("PRAGMA foreign_keys = ON")
            _db.execute("PRAGMA journal_mode = WAL")
            _db.executescript(SCHEMA)
        return _db


def q(sql, *args):
    with _lock:
        return db().execute(sql, args).fetchall()


def q1(sql, *args):
    rows = q(sql, *args)
    return rows[0] if rows else None


# ---------- encryption ----------

def fernet():
    """The server key: SAJADAI_SECRET_KEY, or one generated once into the data directory."""
    global _fernet
    if _fernet is None:
        key = os.environ.get("SAJADAI_SECRET_KEY")
        if not key:
            path = config.DATA_DIR / "secret.key"
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(Fernet.generate_key())
                os.chmod(path, 0o600)
            key = path.read_bytes().decode().strip()
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def seal(obj) -> str:
    return fernet().encrypt(json.dumps(obj).encode()).decode()


def unseal(text, default=None):
    if not text:
        return default
    try:
        return json.loads(fernet().decrypt(text.encode()))
    except (InvalidToken, ValueError):
        return default


# ---------- passwords and tokens ----------

def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(got, base64.b64decode(h))
    except ValueError:
        return False


def sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- users ----------

def user_count() -> int:
    return q1("SELECT COUNT(*) AS n FROM users")["n"]


def create_user(username: str, pw: str, is_admin=False, prefs=None) -> int:
    with _lock:
        cur = db().execute("INSERT INTO users (username, pw, is_admin, created_at, prefs) VALUES (?, ?, ?, ?, ?)",
                           (username.strip(), hash_pw(pw), int(is_admin), time.time(), json.dumps(prefs or {}, ensure_ascii=False)))
        return cur.lastrowid


def get_user(user_id):
    return q1("SELECT * FROM users WHERE id = ?", user_id)


def find_user(username):
    return q1("SELECT * FROM users WHERE username = ?", username.strip())


def users():
    return q("SELECT * FROM users ORDER BY id")


def delete_user(user_id):
    q("DELETE FROM users WHERE id = ?", user_id)


def set_password(user_id, pw):
    q("UPDATE users SET pw = ? WHERE id = ?", hash_pw(pw), user_id)
    q("DELETE FROM sessions WHERE user_id = ?", user_id)  # signed-in browsers have to log in again


def prefs(user) -> dict:
    return json.loads(user["prefs"] or "{}")


def set_prefs(user_id, p: dict):
    q("UPDATE users SET prefs = ? WHERE id = ?", json.dumps(p, ensure_ascii=False), user_id)


def user_secrets(user) -> dict:
    return unseal(user["secrets"], {})


def set_secrets(user_id, s: dict):
    q("UPDATE users SET secrets = ? WHERE id = ?", seal(s), user_id)


def status(user) -> dict:
    return json.loads(user["status"] or "{}")


def update_status(user_id, **kw):
    with _lock:
        row = get_user(user_id)
        if row:
            s = {**status(row), **kw}
            db().execute("UPDATE users SET status = ? WHERE id = ?", (json.dumps(s, ensure_ascii=False), user_id))


def new_api_token(user_id) -> str:
    """A fresh API/MCP token for the user; only its hash is kept, so it's shown once."""
    token = "sj_" + secrets.token_urlsafe(32)
    q("UPDATE users SET api_token = ? WHERE id = ?", sha(token), user_id)
    return token


def user_by_api_token(token):
    return q1("SELECT * FROM users WHERE api_token = ?", sha(token)) if token else None


# ---------- sessions ----------

def new_session(user_id) -> str:
    token = secrets.token_urlsafe(32)
    q("INSERT INTO sessions (token, user_id, expires) VALUES (?, ?, ?)", sha(token), user_id, time.time() + config.SESSION_DAYS * 86400)
    q("DELETE FROM sessions WHERE expires < ?", time.time())
    return token


def session_user(token):
    if not token:
        return None
    return q1("SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ? AND sessions.expires > ?",
              sha(token), time.time())


def end_session(token):
    if token:
        q("DELETE FROM sessions WHERE token = ?", sha(token))


# ---------- panel settings (admin) ----------

def setting(key, default=None):
    row = q1("SELECT value FROM settings WHERE key = ?", key)
    return unseal(row["value"], default) if row else default


def set_setting(key, value):
    q("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, seal(value))
