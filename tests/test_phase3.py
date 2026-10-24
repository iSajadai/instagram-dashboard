"""Phase 3: public accounts. Isolation (A can never read B's data, through any GET route), sign-up modes,
email verification and password reset (SMTP replaced), rate limits, the waitlist, the free AI quota,
deleting an account, security headers."""
import json, os, re, sys, tempfile, time

os.environ["SAJADAI_DATA_DIR"] = tempfile.mkdtemp()
os.environ["SAJADAI_SCHEDULER"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient  # noqa: E402
from sajadai import accounts, agency, config, store, web  # noqa: E402

H = {"X-Requested-With": "sajadai"}
MAIL = []
agency.email = lambda to, subject, text, reply_to=None, sender_name=None: (MAIL.append((to, subject, text)) or (True, "ok"))
accounts.mail = lambda to, subject, text: (MAIL.append((to, subject, text)) or (True, "ok"))


def client():
    return TestClient(web.api, base_url="https://testserver")


store.db()
admin = client()
assert admin.post("/api/setup", json={"username": "admin", "password": "admin-pass-1"}, headers=H).status_code == 200


def signup(c, email, pw="secret-pass-1", privacy=True):
    accounts.SIGNUP.hits.clear()  # every test client has the same address; the limit itself is tested below
    return c.post("/api/signup", json={"email": email, "password": pw, "privacy": privacy}, headers=H)


def test_signup_modes():
    store.set_setting("signup_mode", "closed")
    assert signup(client(), "x@example.com").status_code == 403
    store.set_setting("signup_mode", "open")
    assert signup(client(), "bad-email").status_code == 400
    assert signup(client(), "y@example.com", privacy=False).status_code == 400
    c = client()
    r = signup(c, "Alice@Example.com")
    assert r.status_code == 200 and r.json()["next"] == "/welcome"
    assert c.get("/api/me").json()["username"] == "alice"
    assert signup(client(), "alice@example.com").status_code == 400  # one account per email


def test_isolation():
    """A and B each get data with a marker; A's every GET answer must never contain B's."""
    store.set_setting("signup_mode", "open")
    a, b = client(), client()
    signup(a, "a-user@example.com"); signup(b, "b-user@example.com")
    ida, idb = a.get("/api/me").json(), b.get("/api/me").json()
    uid_b = store.find_email("b-user@example.com")["id"]
    uid_a = store.find_email("a-user@example.com")["id"]
    for uid, mark in ((uid_a, "MARKER-AAA"), (uid_b, "MARKER-BBB")):
        d = config.user_dir(uid)
        data = json.loads((d / "data" / "data.json").read_text())
        data["reels"] = [{"url": f"https://www.instagram.com/reel/{mark}/", "caption": mark, "views": 1, "published": "2026-10-20T10:00:00"}]
        (d / "data" / "data.json").write_text(json.dumps(data))
        for name in ("goals.json", "topics.json", "experiments.json", "board.json", "ideas.json", "insights.json"):
            (d / "content" / name).write_text(json.dumps([{"id": mark.lower(), "title": mark, "label": mark, "metric": "followers", "target": 1}]))
        s = store.user_secrets(store.get_user(uid))
        s["connections"] = {"routine": {"repo": mark, "branch": "main"}}
        store.set_secrets(uid, s)
    skip = {"/api/me/ig/online", "/api/me/ig/limit"}  # these call Instagram
    leaks, checked = [], 0
    for route in web.api.routes:
        path = getattr(route, "path", "")
        if "GET" not in getattr(route, "methods", set()) or "{" in path or path in skip:
            continue
        if not (path.startswith("/api/") or path in ("/data/data.json", "/", "/settings", "/report")):
            continue
        r = a.get(path)
        checked += 1
        if "MARKER-BBB" in r.text:
            leaks.append(path)
    assert checked > 20 and not leaks, (checked, leaks)
    assert "MARKER-AAA" in a.get("/data/data.json").text
    # switching to B's page, or reading its reel/critique/job, is refused
    assert a.post("/api/me/switch", json={"page": uid_b}, headers=H).status_code in (403, 404)
    assert "MARKER-BBB" not in a.get("/api/me/reel", params={"reel": "MARKER-BBB"}).text
    # B's API token can't read A either
    tok = b.post("/api/me/token", headers=H).json().get("token")
    if tok:
        r = client().get("/api/v1/reels", headers={"Authorization": f"Bearer {tok}"})
        assert "MARKER-AAA" not in r.text and r.status_code == 200


def test_verify_and_reset():
    store.set_setting("signup_mode", "open")
    store.set_setting("smtp", {"host": "smtp.example.com", "from": "panel@example.com"})
    MAIL.clear()
    c = client()
    r = signup(c, "v@example.com")
    assert r.json().get("verify") and MAIL and "/verify?token=" in MAIL[-1][2]
    assert c.post("/api/login", json={"username": "v@example.com", "password": "secret-pass-1"}, headers=H).status_code == 403  # not verified
    tok = re.search(r"token=([\w-]+)", MAIL[-1][2]).group(1)
    r = c.get("/verify", params={"token": tok}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/welcome"
    assert client().get("/verify", params={"token": tok}).status_code == 400  # one use
    MAIL.clear()
    assert c.post("/api/password/forgot", json={"email": "nobody@example.com"}, headers=H).json()["ok"] and not MAIL  # same answer, no mail
    c.post("/api/password/forgot", json={"email": "v@example.com"}, headers=H)
    tok = re.search(r"token=([\w-]+)", MAIL[-1][2]).group(1)
    assert client().post("/api/password/reset", json={"token": tok, "password": "short"}, headers=H).status_code == 400
    assert client().post("/api/password/reset", json={"token": tok, "password": "new-secret-9"}, headers=H).status_code == 200
    assert client().post("/api/login", json={"username": "v@example.com", "password": "new-secret-9"}, headers=H).status_code == 200
    store.set_setting("smtp", {})


def test_waitlist():
    store.set_setting("signup_mode", "waitlist")
    c = client()
    r = signup(c, "w@example.com")
    assert r.json().get("waitlist")
    assert c.post("/api/login", json={"username": "w@example.com", "password": "secret-pass-1"}, headers=H).status_code == 403
    wl = admin.get("/api/admin/accounts").json()["waitlist"]
    uid = next(w["id"] for w in wl if w["email"] == "w@example.com")
    assert admin.post("/api/admin/accounts", json={"approve": [uid]}, headers=H).json()["approved"] == [uid]
    assert c.post("/api/login", json={"username": "w@example.com", "password": "secret-pass-1"}, headers=H).status_code == 200
    store.set_setting("signup_mode", "open")


def test_login_rate_limit():
    c = client()
    codes = [c.post("/api/login", json={"username": "brute@example.com", "password": "wrong-pass"}, headers=H).status_code for _ in range(9)]
    assert codes[-1] == 429 and 401 in codes


def test_signup_rate_limit():
    store.set_setting("signup_mode", "open")
    accounts.SIGNUP.hits.clear()
    codes = [client().post("/api/signup", json={"email": f"burst{i}@example.com", "password": "secret-pass-1", "privacy": True}, headers=H).status_code for i in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429, codes


def test_ai_quota():
    from sajadai import ai
    store.set_setting("ai", {"provider": "custom", "key": "k", "base_url": "http://127.0.0.1:9/v1"})
    store.set_setting("ai_quota", {"daily": 2, "monthly": 100})
    u = store.find_email("alice@example.com")
    uid = u["id"]
    store.q("DELETE FROM ai_usage WHERE user_id = ?", uid)
    store.q("INSERT INTO ai_usage (user_id, day, panel_calls) VALUES (?, ?, 2)", uid, time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3.5 * 3600)))
    try:
        ai.ask(store.get_user(uid), "s", [{"role": "user", "content": "hi"}])
        assert False, "quota not enforced"
    except ai.AIError as e:
        assert "سهمیه" in str(e)
    store.set_setting("ai", {})


def test_delete_account():
    c = client()
    signup(c, "gone@example.com")
    uid = store.find_email("gone@example.com")["id"]
    assert config.user_dir(uid).exists()
    assert c.post("/api/me/delete", json={"password": "wrong"}, headers=H).status_code == 401
    r = c.post("/api/me/delete", json={"password": "secret-pass-1"}, headers=H)
    assert r.status_code == 200 and store.get_user(uid) is None and not config.user_dir(uid).exists()
    assert c.get("/api/me").status_code == 401


def test_security_headers():
    r = client().get("/login")
    for h in ("x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy"):
        assert h in r.headers, h
    c = client()
    signup(c, "cookie@example.com")
    cookie = c.cookies.jar
    raw = signup(client(), "cookie2@example.com").headers.get("set-cookie", "")
    assert "HttpOnly" in raw and "SameSite=lax" in raw
    assert client().post("/api/login", json={"username": "a", "password": "b"}).status_code in (400, 403)  # no CSRF header


if __name__ == "__main__":
    bad = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                bad += 1
                import traceback
                print("FAIL", k, repr(e)[:500], traceback.format_exc().splitlines()[-3][:200])
    sys.exit(1 if bad else 0)
