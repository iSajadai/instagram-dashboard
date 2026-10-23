"""Publishing queue, keyword automation and online-followers hours against a fake Instagram (ig.call
replaced), so no request leaves the machine."""
import os, sys, tempfile, time
from datetime import datetime, timedelta, timezone

os.environ["SAJADAI_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sajadai import config, ig  # noqa: E402

USER = {"id": 7}
calls = []
state = {"status": "IN_PROGRESS", "used": 0}


def fake_call(user, method, path, data=None, **params):
    calls.append((method, path, data, params))
    if path == "me":
        return {"user_id": "1789", "username": "isajadai"}
    if path.endswith("content_publishing_limit"):
        return {"data": [{"quota_usage": state["used"], "config": {"quota_total": 50}}]}
    if path == "1789/media":
        return {"id": "C1"}
    if path == "C1":
        return {"status_code": state["status"]}
    if path.endswith("media_publish"):
        return {"id": "M1"}
    if path == "M1":
        return {"permalink": "https://www.instagram.com/reel/abc/"}
    if path.endswith("/comments"):
        now = datetime.now(timezone.utc)
        return {"data": [
            {"id": "c1", "text": "پرامپـت لطفاً!", "timestamp": now.isoformat(), "username": "ali", "from": {"id": "u1"}},
            {"id": "c2", "text": "PROMPT", "timestamp": now.isoformat(), "username": "sara", "from": {"id": "u2"}},
            {"id": "c3", "text": "پرامپت‌نویسی سخته", "timestamp": now.isoformat(), "username": "reza", "from": {"id": "u3"}},
            {"id": "c4", "text": "پرامپت", "timestamp": (now - timedelta(days=9)).isoformat(), "username": "old", "from": {"id": "u4"}},
            {"id": "c5", "text": "پرامپت", "timestamp": now.isoformat(), "username": "isajadai", "from": {"id": "1789"}},
        ]}
    if path.endswith("/messages") or path.endswith("/replies"):
        return {"ok": True}
    raise AssertionError(path)


ig.call = fake_call
ig.token = lambda user: "T"


def test_publish_flow():
    name = ig.new_media_name(".mp4")
    (ig.MEDIA_DIR / name).write_bytes(b"\x00\x00\x00\x18ftypmp42")
    ig.save_queue(USER, [{"id": "q1", "video": name, "cover": "", "caption": "سلام", "when": time.time() - 1, "status": "scheduled"}])
    assert ig.queue_tick(USER, "https://dash.example.com") == []
    q = ig.load_queue(USER)[0]
    assert q["status"] == "processing" and q["container"] == "C1"
    create = next(c for c in calls if c[1] == "1789/media")
    assert create[3]["video_url"] == f"https://dash.example.com/m/{name}" and create[3]["media_type"] == "REELS"
    assert ig.queue_tick(USER, "https://dash.example.com") == []  # still processing
    state["status"] = "FINISHED"
    done = ig.queue_tick(USER, "https://dash.example.com")
    assert done and done[0]["status"] == "published" and done[0]["permalink"].endswith("/abc/")
    assert not (ig.MEDIA_DIR / name).exists(), "video deleted after publishing"


def test_publish_needs_https_and_respects_limit():
    name = ig.new_media_name(".mp4")
    (ig.MEDIA_DIR / name).write_bytes(b"x")
    ig.save_queue(USER, [{"id": "q2", "video": name, "caption": "", "when": time.time() - 1, "status": "scheduled"}])
    done = ig.queue_tick(USER, "http://localhost:8000")
    assert done and done[0]["status"] == "failed" and "https" in done[0]["note"]
    state["used"] = 50
    ig.save_queue(USER, [{"id": "q3", "video": name, "caption": "", "when": time.time() - 1, "status": "scheduled"}])
    ig.queue_tick(USER, "https://dash.example.com")
    q = ig.load_queue(USER)[0]
    assert q["status"] == "scheduled" and q["when"] > time.time() + 3000 and "سقف" in q["note"]
    state["used"] = 0


def test_failed_processing():
    state["status"] = "ERROR"
    ig.save_queue(USER, [{"id": "q4", "video": "x", "status": "processing", "container": "C1", "ig_id": "1789", "started": time.time()}])
    done = ig.queue_tick(USER, "https://dash.example.com")
    assert done[0]["status"] == "failed" and "H.264" in done[0]["note"]
    state["status"] = "IN_PROGRESS"


def test_keyword_match():
    assert ig.keyword_hit("پرامپت", "پرامپـت لطفاً!")
    assert ig.keyword_hit("prompt", "PROMPT")
    assert ig.keyword_hit("پرامپت", "پرامپت")
    assert not ig.keyword_hit("پرامپت", "پرامپت‌نویسی سخته")  # a longer word isn't the keyword
    assert ig.keyword_hit("كتاب", "کتاب رو می‌خوام")  # Arabic kaf / Persian kaf


def test_auto_once_per_person():
    calls.clear()
    ig.save_auto(USER, {"rules": [{"id": "r1", "media_id": "M9", "keyword": "پرامپت", "message": "لینک", "public_reply": True, "active": True},
                                  {"id": "r2", "media_id": "M9", "keyword": "prompt", "message": "link", "active": True}], "sent": {}, "log": []})
    out = ig.auto_tick(USER)
    who = sorted((e["rule"], e["user"]) for e in out)
    assert who == [("r1", "ali"), ("r2", "sara")], who
    dms = [c for c in calls if c[1].endswith("/messages")]
    assert {d[2]["recipient"]["comment_id"] for d in dms} == {"c1", "c2"}
    assert any(c[1] == "c1/replies" for c in calls)  # public reply on r1 only
    assert not any(c[1] == "c2/replies" for c in calls)
    calls.clear()
    assert ig.auto_tick(USER) == [] and not [c for c in calls if c[1].endswith("/messages")]
    assert ig.load_auto(USER)["rules"][0]["count"] == 1


def test_pacific_to_tehran():
    assert ig.is_pdt(datetime(2026, 7, 1, tzinfo=timezone.utc)) and not ig.is_pdt(datetime(2026, 12, 1, tzinfo=timezone.utc))


if __name__ == "__main__":
    bad = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                bad += 1
                print("FAIL", k, repr(e)[:400])
    sys.exit(1 if bad else 0)
