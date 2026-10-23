"""Read-only summaries of a user's data.json, shared by the MCP tools and the JSON API, so Claude and
ChatGPT get answers ready to use instead of the raw file. Same definitions as the dashboard page."""
import json, re
from datetime import datetime, timedelta, timezone
from statistics import median

TEH = timezone(timedelta(hours=3, minutes=30))
DAY_FA = {1: "دوشنبه", 2: "سه‌شنبه", 3: "چهارشنبه", 4: "پنجشنبه", 5: "جمعه", 6: "شنبه", 7: "یکشنبه"}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _day(s):
    return str(s or "")[:10]


def _since(days):
    return (datetime.now(TEH).date() - timedelta(days=days - 1)).isoformat() if days else ""


def _r1(x):
    return None if x is None else round(x, 1)


def scored(d):
    """Every reel with its multiple of the page median, save rate, shares per 1,000 reached, follows per 1,000 views."""
    reels = d.get("reels", [])
    views = [r["views"] for r in reels if r.get("views") is not None]
    med = median(views) if views else None
    out = []
    for r in reels:
        v, reach = r.get("views"), r.get("reach")
        out.append({
            "published": r.get("published"), "url": r.get("url"), "caption": (r.get("caption") or "")[:300],
            "topic": r.get("topic"), "views": v, "reach": reach,
            "multiple_of_median": _r1(v / med) if med and v is not None else None,
            "view_rate_3s_pct": r.get("view_rate"), "avg_watch_s": r.get("avg_watch"),
            "save_rate_pct": _r1((r.get("saves") or 0) / v * 100) if v else None,
            "shares_per_1k_reach": _r1((r.get("shares") or 0) / reach * 1000) if reach else None,
            "follows": r.get("follows"),
            "follows_per_1k_views": _r1(r["follows"] / v * 1000) if r.get("follows") is not None and v else None,
            "likes": r.get("likes"), "comments": r.get("comments"), "saves": r.get("saves"), "shares": r.get("shares"),
        })
    return sorted(out, key=lambda r: str(r["published"]), reverse=True), med


def overview(d, days=30):
    """Headline numbers for the last `days` days (0 = everything), top and weakest reels, goal progress."""
    reels, med = scored(d)
    since = _since(days)
    inr = [r for r in reels if _day(r["published"]) >= since]
    views = sum(r["views"] or 0 for r in inr)
    reach = sum(r["reach"] or 0 for r in inr)
    vr = [r["view_rate_3s_pct"] for r in inr if r["view_rate_3s_pct"] is not None]
    fols = [a for a in d.get("account", []) if a.get("followers") is not None]
    before = [a for a in fols if a["day"] < since]
    first = next((a for a in fols if a["day"] >= since), None)
    base = before[-1] if before else first
    ranked = sorted([r for r in inr if r["views"] is not None], key=lambda r: r["views"], reverse=True)
    brief = lambda r: {k: r[k] for k in ("published", "url", "caption", "views", "multiple_of_median", "view_rate_3s_pct", "follows")}
    return {
        "updated_at": d.get("generated_at"),
        "range_days": days or "all",
        "followers": fols[-1]["followers"] if fols else None,
        "followers_net": fols[-1]["followers"] - base["followers"] if fols and base else None,
        "reels": len(inr),
        "reel_views": views,
        "page_median_views": med,
        "avg_view_rate_3s_pct": _r1(sum(vr) / len(vr)) if vr else None,
        "save_rate_pct": _r1(sum(r["saves"] or 0 for r in inr) / views * 100) if views else None,
        "shares_per_1k_reach": _r1(sum(r["shares"] or 0 for r in inr) / reach * 1000) if reach else None,
        "top_reels": [brief(r) for r in ranked[:3]],
        "weakest_reels": [brief(r) for r in ranked[-3:][::-1]] if len(ranked) > 3 else [],
        "goals": goals(d),
    }


def goals(d):
    today = datetime.now(TEH).date()
    wk = (today - timedelta(days=6)).isoformat()
    fols = [a for a in d.get("account", []) if a.get("followers") is not None]
    out = []
    for g in d.get("goals", []):
        cur = None
        if g.get("metric") == "followers" and fols:
            cur = fols[-1]["followers"]
        elif g.get("metric") == "reels_7d":
            cur = sum(1 for r in d.get("reels", []) if _day(r.get("published")) >= wk)
        elif g.get("metric") == "views_7d":
            cur = sum(a.get("reels_views") or 0 for a in d.get("account", []) if a["day"] >= wk)
        out.append({"label": g.get("label"), "metric": g.get("metric"), "target": g.get("target"), "current": cur,
                    "percent": min(100, round(cur / g["target"] * 100)) if cur is not None and g.get("target") else None,
                    "deadline": g.get("deadline")})
    return out


def reels_list(d, limit=20, sort="published", days=0):
    reels, _ = scored(d)
    since = _since(days)
    reels = [r for r in reels if _day(r["published"]) >= since]
    key = {"views": "views", "multiple": "multiple_of_median", "view_rate": "view_rate_3s_pct", "follows": "follows",
           "saves": "save_rate_pct"}.get(sort)
    if key:
        reels.sort(key=lambda r: (r[key] is not None, r[key] or 0), reverse=True)
    return reels[: max(1, min(limit, 200))]


def shortcode(s):
    m = re.search(r"/(?:reels?|p|tv)/([A-Za-z0-9_-]+)", str(s or ""))
    return m[1] if m else str(s or "").strip("/ ")


def reel(d, url_or_code):
    """One reel's numbers and its view curve (views by hours since publishing, from the 6-hourly snapshots)."""
    code = shortcode(url_or_code)
    reels, _ = scored(d)
    r = next((x for x in reels if shortcode(x["url"]) == code), None)
    if not r:
        return None
    try:
        pub = datetime.fromisoformat(str(r["published"])[:19]).replace(tzinfo=TEH)
    except ValueError:
        pub = None
    curve = []
    for s in d.get("reel_snapshots", []):
        if s.get("url") == r["url"] and pub and s.get("views") is not None:
            at = datetime.fromisoformat(s["at"].replace("Z", "+00:00"))
            curve.append({"hours": round((at - pub).total_seconds() / 3600, 1), "views": s["views"]})
    return {**r, "caption": next((x.get("caption") for x in d.get("reels", []) if x.get("url") == r["url"]), r["caption"]),
            "view_curve": curve}


def daily(d, days=30):
    since = _since(days)
    taps = {t["day"]: t.get("taps") for t in d.get("profile_taps", [])}
    return [{**{k: a.get(k) for k in ("day", "followers", "gained", "lost", "reels", "reels_views", "reels_reach", "views", "reach", "engaged")},
             "link_taps": taps.get(a["day"])} for a in d.get("account", []) if a["day"] >= since]


def best_times(d, top=5):
    cells = sorted(d.get("best_time", []), key=lambda c: c.get("value") or 0, reverse=True)[:top]
    return [{"day": DAY_FA.get(c["day_of_week"], c["day_of_week"]), "hour_tehran": f"{c['hour']:02d}:00", "score": c.get("value")} for c in cells]


def content(d):
    return {"ideas": sorted(d.get("ideas", []), key=lambda i: i.get("priority") or 99), "insights": d.get("insights", []),
            "benchmark_pages": d.get("benchmarks", []), "experiments": d.get("experiments", [])}


def competitors(d):
    return {"competitors": d.get("competitors", []),
            "top_competitor_reels": sorted(d.get("competitor_reels", []), key=lambda r: r.get("interactions") or 0, reverse=True)[:10]}
