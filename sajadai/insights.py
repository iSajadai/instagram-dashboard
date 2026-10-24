"""The analysis on the insights page, kept in step with the numbers: after every successful sync, when the
reels or their numbers changed, the AI writes it again from the current data and records which data it
read (content/insights_meta.json: when, how many reels, a fingerprint). Without an AI connected, the
old analysis stays and the page says it was written from older data.

Next to it the page always shows a summary computed from data.json (no AI), so counts and dates can't
contradict the dashboard."""
import hashlib, json, time

from . import analysis, config, pipeline, store

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["insights"],
          "properties": {"insights": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                 "required": ["id", "area", "severity", "finding", "action"],
                                                                 "properties": {"id": {"type": "string"}, "area": {"type": "string"},
                                                                                "severity": {"type": "string", "enum": ["مهم", "متوسط", "خوب"]},
                                                                                "finding": {"type": "string"}, "action": {"type": "string"}}}}}}
SYSTEM = """You analyse an Instagram creator's numbers and write 3 to 5 findings in conversational Persian.
Use ONLY the data given: count reels from the list (never say "only one reel" when the list has more), name reels by
their caption start and date, and cite the numbers behind each finding. multiple_of_median compares a reel with the
page's median views; view_rate_3s_pct is the share who stayed past 3 seconds. If a comparison rests on fewer than 3
reels on a side, say it's too early to conclude. Each item: id (short latin slug), area (هوک / نگه‌داشتن / ذخیره /
اشتراک / زمان انتشار / رشد / محتوا), severity (مهم / متوسط / خوب), finding (what the numbers show), action (one
concrete thing to do this week)."""


def fingerprint(d):
    """What the analysis depends on: each reel and its rounded numbers, and the last follower count."""
    reels = sorted((r.get("url") or "", round((r.get("views") or 0), -1), round(r.get("view_rate") or 0)) for r in d.get("reels", []))
    fol = [a.get("followers") for a in d.get("account", []) if a.get("followers") is not None][-1:]
    return hashlib.sha256(json.dumps([reels, fol]).encode()).hexdigest()[:16]


def meta_path(uid):
    return config.user_dir(uid) / "content" / "insights_meta.json"


def facts(d):
    return {"reels_in_last_30_days": analysis.reels_list(d, 50, days=30), "last_7_days": analysis.overview(d, 7),
            "last_30_days": analysis.overview(d, 30), "best_posting_times": analysis.best_times(d, 5)}


def regenerate(uid):
    from . import ai
    user = store.get_user(uid)
    d = analysis.load(config.user_dir(uid) / "data" / "data.json") or {}
    if not d.get("reels"):
        return False
    out = ai.ask(user, SYSTEM, [{"role": "user", "content": json.dumps(facts(d), ensure_ascii=False)}], schema=SCHEMA, max_tokens=4000, effort="medium")
    items = [i for i in out.get("insights", []) if i.get("finding")][:6]
    if not items:
        return False
    content = config.user_dir(uid) / "content"
    content.mkdir(parents=True, exist_ok=True)
    (content / "insights.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {"generated_at": int(time.time()), "data_at": d.get("data_at") or d.get("generated_at"), "reels": len(d.get("reels", [])),
            "fingerprint": fingerprint(d), "source": "panel"}
    meta_path(uid).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    pipeline.run_script(uid, "shape.py", {})
    return True


def refresh_if_changed(uid):
    """After a sync: write the analysis again when the numbers moved and an AI is connected."""
    d = analysis.load(config.user_dir(uid) / "data" / "data.json") or {}
    meta = analysis.load(meta_path(uid)) or {}
    if not d.get("reels") or meta.get("fingerprint") == fingerprint(d):
        return False
    if not pipeline.ai_config(store.get_user(uid)):
        return False
    try:
        return regenerate(uid)
    except Exception as e:  # noqa: BLE001 — the old analysis stays; the page says it's from older data
        store.update_status(uid, insights_log=f"error: {e}"[:300])
        return False


def status(d, meta):
    """For the page: when the analysis was written, from which data, and whether the data changed since."""
    return {"generated_at": meta.get("generated_at"), "data_at": meta.get("data_at"), "reels": meta.get("reels"),
            "source": meta.get("source") or "routine", "stale": bool(meta.get("fingerprint")) and meta.get("fingerprint") != fingerprint(d),
            "known": bool(meta.get("fingerprint"))}
