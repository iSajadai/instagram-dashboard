"""Phase 1 fixes: the routine's repo as a source (fetch_repo.py → shape.py), the data's real time, the
summary that can't contradict the dashboard, duration and watch %, the analysis fingerprint shared by
shape.py and sajadai/insights.py, and the health check's 8-hour line."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["SAJADAI_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT))
PY = sys.executable

REELS = {"rows": [
    ["20261020140744", "پایتخت استرالیا کجاست؟", "https://www.instagram.com/reel/AAA111/", 4231, 3000, 7.452, None, 40.1, 10, 20, 50, 3, 0],
    ["20261021074146", "قسمت ۲", "https://www.instagram.com/reel/BBB222/", 3439, 2500, 8.575, None, 45.0, 5, 12, 40, 2, 0],
    ["20261022091906", "قسمت ۳", "https://www.instagram.com/reel/CCC333/", 3307, 2400, 8.948, None, 50.5, 4, 9, 30, 1, 0]]}
ACCOUNT = {"rows": [[13, None, None, None, None, None, None, "20261019"], [58, None, None, None, None, None, None, "20261022"]]}


def make_repo():
    d = Path(tempfile.mkdtemp())
    (d / "raw").mkdir()
    (d / "content").mkdir()
    (d / "raw" / "reels.json").write_text(json.dumps(REELS, ensure_ascii=False))
    (d / "raw" / "account.json").write_text(json.dumps(ACCOUNT))
    (d / "raw" / "broken.json").write_text("{")
    (d / "content" / "insights.json").write_text(json.dumps([{"id": "x", "area": "هوک", "severity": "مهم", "finding": "f", "action": "a"}], ensure_ascii=False))
    for c in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "data"]):
        subprocess.run(["git", *c], cwd=d, check=True)
    return d


def run(script, state, **env):
    r = subprocess.run([PY, str(ROOT / "scripts" / script)], env={**os.environ, "SAJADAI_STATE": str(state), **env}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_repo_source_and_shape():
    repo, state = make_repo(), Path(tempfile.mkdtemp())
    (state / "content").mkdir()
    (state / "content" / "durations.json").write_text(json.dumps({"CCC333": 20.0}))
    out = run("fetch_repo.py", state, SAJADAI_DATA_REPO=str(repo))
    assert "reels" in out and "content/insights" in out
    src = json.loads((state / "raw" / "repo_source.json").read_text())
    assert len(src["commit"]) == 40 and src["committed_at"]
    run("shape.py", state)
    d = json.loads((state / "data" / "data.json").read_text())
    assert d["data_at"] == src["committed_at"], "the dashboard shows when the routine read Metricool"
    r = {x["url"].split("/")[-2]: x for x in d["reels"]}
    assert r["CCC333"]["views"] == 3307 and r["CCC333"]["duration"] == 20.0 and r["CCC333"]["watch_pct"] == 44.7
    assert r["AAA111"]["watch_pct"] is None
    s = d["auto_summary"][0]
    assert s["reels_total"] == 3 and s["median_views"] == 3439
    m = d["insights_meta"][0]
    assert m["source"] == "routine" and not m["known"]


def test_panel_analysis_not_overwritten_by_routine():
    repo, state = make_repo(), Path(tempfile.mkdtemp())
    (state / "content").mkdir()
    mine = [{"id": "mine", "area": "رشد", "severity": "خوب", "finding": "panel", "action": "x"}]
    (state / "content" / "insights.json").write_text(json.dumps(mine, ensure_ascii=False))
    (state / "content" / "insights_meta.json").write_text(json.dumps({"source": "panel", "fingerprint": "abc"}))
    run("fetch_repo.py", state, SAJADAI_DATA_REPO=str(repo))
    assert json.loads((state / "content" / "insights.json").read_text())[0]["id"] == "mine"


def test_bad_repo_message():
    r = subprocess.run([PY, str(ROOT / "scripts" / "fetch_repo.py")], env={**os.environ, "SAJADAI_STATE": tempfile.mkdtemp(), "SAJADAI_DATA_REPO": "/nonexistent/repo"},
                       capture_output=True, text=True)
    assert r.returncode != 0 and "git clone failed" in (r.stdout + r.stderr)


def test_fingerprint_same_in_shape_and_insights():
    sys.path.insert(0, str(ROOT / "scripts"))
    os.environ.setdefault("SAJADAI_STATE", tempfile.mkdtemp())
    import shape  # noqa: E402
    from sajadai import insights  # noqa: E402
    d = {"reels": [{"url": "u1", "views": 1234, "view_rate": 40.4}, {"url": "u2", "views": 99, "view_rate": None}],
         "account": [{"followers": 50}, {"followers": None}]}
    assert shape.fingerprint(d) == insights.fingerprint(d)
    d2 = json.loads(json.dumps(d))
    d2["reels"][0]["views"] = 1300
    assert shape.fingerprint(d2) != shape.fingerprint(d)


def test_health_line():
    from sajadai import pipeline, store
    store.db()
    uid = store.create_user("h1", "secret-pass-1")
    u = store.get_user(uid)
    assert pipeline.health(u)["stale"] is False  # nothing connected: nothing to warn about
    s = store.user_secrets(u)
    s["connections"] = {"routine": {"repo": "x/y", "branch": "main"}}
    store.set_secrets(uid, s)
    store.update_status(uid, last_ok_at=time.time() - 9 * 3600)
    h = pipeline.health(store.get_user(uid))
    assert h["stale"] and 8.9 < h["hours"] < 9.1
    store.update_status(uid, last_ok_at=time.time() - 3600)
    assert not pipeline.health(store.get_user(uid))["stale"]


if __name__ == "__main__":
    bad = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                bad += 1
                print("FAIL", k, repr(e)[:500])
    sys.exit(1 if bad else 0)
