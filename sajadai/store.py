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
CREATE TABLE IF NOT EXISTS payments (    -- subscription payments through Zarinpal
  authority TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  plan_id TEXT NOT NULL,
  amount INTEGER NOT NULL,               -- toman
  status TEXT NOT NULL,                  -- pending, verifying, paid, failed, canceled
  ref_id TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (       -- one-time links: email verification, password reset
  hash TEXT PRIMARY KEY,                 -- sha256 of the token in the link
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL,                 -- verify or reset
  expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage (     -- AI calls per person per day: on the panel's key (counted against the free quota) or their own
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day TEXT NOT NULL,
  panel_calls INTEGER NOT NULL DEFAULT 0,
  own_calls INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS memberships (  -- who else works on a page, and as what
  page_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,                    -- owner, editor or viewer
  created_at REAL NOT NULL,
  PRIMARY KEY (page_id, user_id)
);
"""
# Columns added after the first release; an older database gets them on start.
#   users.kind      'person' (someone who signs in; also their own first page) or 'page' (an extra page, no sign-in)
#   users.owner_id  for a 'page': the person who made it
#   sessions.acting_id  the page this browser is working on (empty: the person's own)
MIGRATIONS = [("users", "kind", "TEXT NOT NULL DEFAULT 'person'"), ("users", "owner_id", "INTEGER"), ("sessions", "acting_id", "INTEGER"),
              ("users", "email", "TEXT"), ("users", "email_verified", "INTEGER NOT NULL DEFAULT 0"),
              ("users", "state", "TEXT NOT NULL DEFAULT 'active'"),   # active | waitlist (signed up while the list was on)
              ("users", "google_sub", "TEXT")]
ROLES = ("owner", "editor", "viewer")


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
            for table, col, decl in MIGRATIONS:
                if col not in {r["name"] for r in _db.execute(f"PRAGMA table_info({table})")}:
                    _db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            _db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email COLLATE NOCASE) WHERE email IS NOT NULL")
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
    """A person by their sign-in name (extra pages have names too, but nobody signs in as them)."""
    return q1("SELECT * FROM users WHERE username = ? AND kind = 'person'", username.strip())


def find_email(email):
    return q1("SELECT * FROM users WHERE email = ? COLLATE NOCASE AND kind = 'person'", (email or "").strip())


def set_user(user_id, **cols):
    """Update a few columns of a user row (email, email_verified, state, google_sub, pw)."""
    allowed = {"email", "email_verified", "state", "google_sub", "pw"}
    cols = {k: v for k, v in cols.items() if k in allowed}
    if cols:
        q(f"UPDATE users SET {', '.join(k + ' = ?' for k in cols)} WHERE id = ?", *cols.values(), user_id)


def new_token(user_id, purpose, hours):
    raw = secrets.token_urlsafe(32)
    q("DELETE FROM tokens WHERE user_id = ? AND purpose = ?", user_id, purpose)
    q("INSERT INTO tokens (hash, user_id, purpose, expires) VALUES (?, ?, ?, ?)", hashlib.sha256(raw.encode()).hexdigest(), user_id, purpose, time.time() + hours * 3600)
    return raw


def use_token(raw, purpose):
    """The user a one-time token belongs to (and the token is gone), or None."""
    h = hashlib.sha256(str(raw or "").encode()).hexdigest()
    row = q1("SELECT * FROM tokens WHERE hash = ? AND purpose = ?", h, purpose)
    if not row:
        return None
    q("DELETE FROM tokens WHERE hash = ?", h)
    return get_user(row["user_id"]) if row["expires"] > time.time() else None


def person_id(user):
    """The signed-in person behind a page: request users carry it in "person"; a plain row is the person
    itself when kind = 'person', else its owner."""
    keys = user.keys()
    if "person" in keys and user["person"]:
        return user["person"]["id"]
    if "kind" in keys and user["kind"] == "page" and user["owner_id"]:
        return user["owner_id"]
    return user["id"]


def count_ai(user_id, own):
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3.5 * 3600))
    col = "own_calls" if own else "panel_calls"
    q(f"INSERT INTO ai_usage (user_id, day, {col}) VALUES (?, ?, 1) ON CONFLICT(user_id, day) DO UPDATE SET {col} = {col} + 1", user_id, day)


def ai_used(user_id, days=1):
    """Calls on the panel's key over the last `days` days (Tehran dates)."""
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3.5 * 3600 - (days - 1) * 86400))
    r = q1("SELECT COALESCE(SUM(panel_calls), 0) AS p, COALESCE(SUM(own_calls), 0) AS o FROM ai_usage WHERE user_id = ? AND day >= ?", user_id, since)
    return {"panel": r["p"], "own": r["o"]}


def name_taken(username):
    return q1("SELECT 1 FROM users WHERE username = ?", username.strip()) is not None


def users():
    return q("SELECT * FROM users ORDER BY id")


def delete_user(user_id):
    with _lock:
        q("DELETE FROM users WHERE kind = 'page' AND owner_id = ?", user_id)  # a person's extra pages go with them
        q("DELETE FROM users WHERE id = ?", user_id)


# ---------- pages and teams ----------

def create_page(owner_id, name) -> int:
    """An extra page for a person: its own data, connections and settings; nobody signs in as it."""
    with _lock:
        handle = "page-" + secrets.token_hex(4)
        cur = db().execute("INSERT INTO users (username, pw, is_admin, created_at, prefs, kind, owner_id) VALUES (?, ?, 0, ?, ?, 'page', ?)",
                           (handle, hash_pw(secrets.token_urlsafe(24)), time.time(), json.dumps({"page_name": name}, ensure_ascii=False), owner_id))
        set_member(cur.lastrowid, owner_id, "owner")
        return cur.lastrowid


def set_member(page_id, user_id, role):
    q("INSERT INTO memberships (page_id, user_id, role, created_at) VALUES (?, ?, ?, ?) "
      "ON CONFLICT(page_id, user_id) DO UPDATE SET role = excluded.role", page_id, user_id, role, time.time())


def remove_member(page_id, user_id):
    q("DELETE FROM memberships WHERE page_id = ? AND user_id = ?", page_id, user_id)


def members(page_id):
    """Everyone on a page: the person whose own page it is (owner), then everyone added to it."""
    page = get_user(page_id)
    out = [] if not page or page["kind"] == "page" else [{"id": page["id"], "username": page["username"], "role": "owner", "self": True}]
    out += [{"id": r["id"], "username": r["username"], "role": r["role"], "self": False} for r in
            q("SELECT users.id, users.username, memberships.role FROM memberships JOIN users ON users.id = memberships.user_id "
              "WHERE memberships.page_id = ? ORDER BY memberships.created_at", page_id)]
    return out


def role_for(person_id, page_id):
    if person_id == page_id:
        return "owner"
    r = q1("SELECT role FROM memberships WHERE page_id = ? AND user_id = ?", page_id, person_id)
    return r["role"] if r else None


def pages_for(person):
    """The pages a person can open: their own first, then the ones they made or were added to."""
    out = [{"id": person["id"], "name": prefs(person).get("page_name") or person["username"], "role": "owner", "own": True, "extra": False}]
    for r in q("SELECT users.*, memberships.role AS role FROM memberships JOIN users ON users.id = memberships.page_id "
               "WHERE memberships.user_id = ? ORDER BY users.id", person["id"]):
        out.append({"id": r["id"], "name": prefs(r).get("page_name") or r["username"], "role": r["role"], "own": False,
                    "extra": r["kind"] == "page"})  # an extra page can be deleted by its owner; someone's own page can't
    return out


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


def session_acting(token):
    r = q1("SELECT acting_id FROM sessions WHERE token = ?", sha(token)) if token else None
    return r["acting_id"] if r else None


def set_acting(token, page_id):
    q("UPDATE sessions SET acting_id = ? WHERE token = ?", page_id, sha(token))


def end_session(token):
    if token:
        q("DELETE FROM sessions WHERE token = ?", sha(token))


# ---------- payments ----------

def add_payment(user_id, plan_id, amount, authority):
    now = time.time()
    q("INSERT INTO payments (authority, user_id, plan_id, amount, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
      authority, user_id, plan_id, amount, now, now)


def payment(authority):
    return q1("SELECT * FROM payments WHERE authority = ?", authority)


def claim_payment(authority) -> bool:
    """Mark a pending payment as being verified; False if someone else got there first."""
    with _lock:
        return db().execute("UPDATE payments SET status = 'verifying', updated_at = ? WHERE authority = ? AND status = 'pending'",
                            (time.time(), authority)).rowcount == 1


def update_payment(authority, status, ref_id=None):
    q("UPDATE payments SET status = ?, ref_id = COALESCE(?, ref_id), updated_at = ? WHERE authority = ?", status, ref_id, time.time(), authority)


def payments(limit=30):
    return q("SELECT payments.*, users.username FROM payments LEFT JOIN users ON users.id = payments.user_id ORDER BY created_at DESC LIMIT ?", limit)


# ---------- panel settings (admin) ----------

def setting(key, default=None):
    row = q1("SELECT value FROM settings WHERE key = ?", key)
    return unseal(row["value"], default) if row else default


def set_setting(key, value):
    q("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, seal(value))
