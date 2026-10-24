"""Phase 2: the sources behind one interface. Export parsing (CSV in English and Persian, XLSX, Download
your information), merging by source priority with the disagreement log, a scraper (Apify, HTTP replaced),
coverage, the sync queue, webhooks, the Instagram permission check, and a source going away."""
import base64, hashlib, hmac, io, json, os, subprocess, sys, tempfile, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["SAJADAI_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT))
from sajadai import config, store  # noqa: E402
from sajadai.providers import files, read_norm, registry, write_norm  # noqa: E402

store.db()
UID = store.create_user("p2", "secret-pass-1")
STATE = config.user_dir(UID)
(STATE / "raw").mkdir(parents=True, exist_ok=True)
(STATE / "content").mkdir(parents=True, exist_ok=True)

EN = ("Post ID,Account username,Description,Duration (sec),Publish time,Permalink,Post type,Views,Reach,Likes,Shares,Follows,Comments,Saves\n"
      "1,isajadai,پایتخت استرالیا؟,31,10/20/2026 14:07,https://www.instagram.com/reel/AAA111/,IG reel,4300,3100,52,10,4,3,21\n"
      "2,isajadai,کاروسل,,10/21/2026 09:00,https://www.instagram.com/p/PPP222/,IG carousel,,800,40,2,1,5,30\n")
FA = ("شناسه,توضیحات,مدت,زمان انتشار,پیوند,نوع,بازدید,دسترسی,لایک,اشتراک,کامنت,ذخیره\n"
      "1,قسمت ۲,۲۸,2026-10-21 07:41,https://www.instagram.com/reel/BBB222/,ریل,۳٬۴۵۰,۲٬۵۰۰,۴۰,۵,۲,۱۲\n")


def run_shape():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "shape.py")], env={**os.environ, "SAJADAI_STATE": str(STATE)}, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((STATE / "data" / "data.json").read_text())


def xlsx(rows):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        cells = "".join("<row>" + "".join(f'<c r="{chr(65 + i)}{n + 1}" t="inlineStr"><is><t>{v}</t></is></c>' for i, v in enumerate(r)) + "</row>" for n, r in enumerate(rows))
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{cells}</sheetData></worksheet>')
    return b.getvalue()


def test_parse_exports():
    en = files.parse_export(EN.encode(), "export.csv")
    assert len(en["reels"]) == 1 and len(en["posts"]) == 1
    r = en["reels"][0]
    assert r["shortcode"] == "AAA111" and r["views"] == 4300 and r["reach"] == 3100 and r["duration"] == 31 and r["published"] == "2026-10-20T14:07:00"
    fa = files.parse_export(FA.encode("utf-8"), "export.csv")["reels"][0]
    assert fa["shortcode"] == "BBB222" and fa["views"] == 3450 and fa["duration"] == 28, fa
    x = files.parse_export(xlsx([["Permalink", "Post type", "Views", "Likes"], ["https://www.instagram.com/reel/CCC333/", "IG reel", "1.2K", "9"]]), "a.xlsx")
    assert x["reels"][0]["views"] == 1200


def test_parse_dyi():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("your_instagram_activity/content/reels.json", json.dumps({"ig_reels_media": [{"media": [{"title": "Ù\u0082Ø³Ù\u0085Øª", "creation_timestamp": 1792500000, "uri": "media/reels/1.mp4"}]}]}))
        z.writestr("connections/followers_and_following/followers_1.json", json.dumps([{"string_list_data": [{"value": "a"}]}] * 57))
    d = files.parse_dyi(b.getvalue(), "dyi.zip")
    assert d["followers"] == 57 and len(d["reels"]) == 1 and d["reels"][0]["caption"] == "قسمت"


def test_merge_priority_and_disagreement():
    (STATE / "raw" / "reels.json").write_text(json.dumps({"rows": [["20261020140744", "پایتخت", "https://www.instagram.com/reel/AAA111/", 4231, 3000, 7.4, None, 40.1, 10, 20, 50, 3, 0]]}))
    (STATE / "raw" / "account.json").write_text(json.dumps({"rows": [[57, None, None, None, None, None, None, "20261022"]]}))
    write_norm(UID, "export_csv", {"reels": [{"shortcode": "AAA111", "views": 4300, "duration": 31, "follows": 4}, {"shortcode": "BBB222", "views": 3450}]})
    write_norm(UID, "apify", {"reels": [{"shortcode": "AAA111", "views": 9999}]})
    d = run_shape()
    r = {x["url"].split("/")[-2]: x for x in d["reels"]}
    a = r["AAA111"]
    assert a["views"] == 4231 and a["_src"]["views"] == "metricool", a["_src"]  # analytics beats a scraper and a file
    assert a["duration"] == 31 and a["_src"]["duration"] == "export_csv"  # a file fills what nobody else gave
    assert a["watch_pct"] == round(7.4 / 31 * 100, 1)
    assert r["BBB222"]["views"] == 3450  # a reel only the export knows about
    log = json.loads((STATE / "raw" / "discrepancies.json").read_text())
    assert any(x["reel"] == "AAA111" and x["field"] == "views" and "apify" in x for x in log)


def test_source_goes_away():
    (STATE / "raw" / "norm" / "export_csv.json").unlink()
    d = run_shape()
    r = {x["url"].split("/")[-2]: x for x in d["reels"]}
    assert r["AAA111"]["views"] == 4231 and r["BBB222"]["views"] == 3450  # history stays; nothing breaks


def test_apify_sync():
    from sajadai.providers import scrapers
    calls = []

    def fake_post(url, token, payload, timeout=320):
        calls.append(url)
        if "reel-scraper" in url:
            return [{"ownerUsername": "isajadai", "shortCode": "AAA111", "url": "https://www.instagram.com/reel/AAA111/", "timestamp": "2026-10-20T10:37:44.000Z",
                     "caption": "پایتخت", "videoPlayCount": 4500, "likesCount": -1, "commentsCount": 3, "videoDuration": 30.96},
                    {"ownerUsername": "rival", "shortCode": "RRR1", "url": "https://www.instagram.com/reel/RRR1/", "videoPlayCount": 90000, "likesCount": 900, "commentsCount": 40}]
        return [{"username": "isajadai", "followersCount": 61}, {"username": "rival", "followersCount": 12000, "fullName": "Rival"}]
    scrapers.post = fake_post
    (STATE / "content" / "competitor_handles.json").write_text(json.dumps(["rival"]))
    msg = registry()["apify"].sync({"id": UID}, {"api_key": "x", "handle": "isajadai"})
    assert "۱" in msg or "1" in msg
    n = read_norm(UID, "apify")
    assert n["reels"][0]["likes"] is None and n["reels"][0]["duration"] == 31.0 and n["account_days"][0]["followers"] == 61
    assert n["competitors"][0]["handle"] == "rival" and n["competitors"][0]["median_views"] == 90000
    assert list((STATE / "raw" / "payloads" / "apify").glob("*.json")), "raw answer kept"
    d = run_shape()
    assert any(c["screen_name"] == "rival" and c["followers"] == 12000 for c in d["competitors"])


def test_coverage():
    from sajadai.providers.coverage import matrix
    d = json.loads((STATE / "data" / "data.json").read_text())
    m = matrix({"id": UID}, {"apify": {}}, d)
    items = {i["id"]: i for g in m["groups"] for i in g["items"]}
    assert items["views"]["state"] == "ok"
    assert items["age"]["state"] == "missing" and items["age"]["suggest"][0]["id"] == "instagram"
    assert all(s["id"] != "apify" for s in items["competitors"]["suggest"])


def test_queue_dedupes():
    from sajadai import jobs
    assert jobs.enqueue(99, "refresh", delay=3600) is True
    assert jobs.enqueue(99, "refresh") is False
    assert any(p["user"] == 99 for p in jobs.pending())


def test_webhook_signature():
    from fastapi.testclient import TestClient
    from sajadai import web
    s = store.user_secrets(store.get_user(UID))
    s["connections"] = {"webhooks": {"app_secret": "s3cret-app-secret-123", "verify_token": "vt-123"}}
    store.set_secrets(UID, s)
    c = TestClient(web.api)
    r = c.get("/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "vt-123", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"
    assert c.get("/webhooks/instagram", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "42"}).status_code == 403
    body = json.dumps({"object": "instagram", "entry": [{"id": "1789", "time": 1, "field": "comments", "value": {"id": "c1", "text": "پرامپت"}}]}).encode()
    good = "sha256=" + hmac.new(b"s3cret-app-secret-123", body, hashlib.sha256).hexdigest()
    assert c.post("/webhooks/instagram", content=body, headers={"x-hub-signature-256": "sha256=bad"}).status_code == 403
    assert c.post("/webhooks/instagram", content=body, headers={"x-hub-signature-256": good}).status_code == 200


def test_ig_permission_check():
    from sajadai.providers import catalog

    def fake_get(url, timeout=30):
        if "/me?fields" in url:
            return {"user_id": "1789", "username": "isajadai", "account_type": "MEDIA_CREATOR", "followers_count": 58}, None
        if "me/media" in url:
            return {"data": [{"id": "m1"}]}, None
        if "conversations" in url or "content_publishing_limit" in url:
            return None, {"code": 10, "message": "Application does not have permission for this action"}
        return {"data": []}, None
    catalog._get = fake_get
    r = catalog.check_ig_token("tok")
    names = sorted(m["name"] for m in r["missing_permissions"])
    assert r["ok"] and r["account_name"] == "@isajadai" and names == ["instagram_business_content_publish", "instagram_business_manage_messages"], r


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
                print("FAIL", k, repr(e)[:400], traceback.format_exc().splitlines()[-3][:200])
    sys.exit(1 if bad else 0)
