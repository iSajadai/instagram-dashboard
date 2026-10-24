"""The coverage page: for every kind of data, which connected source gives it, whether numbers actually
arrived, and what to connect when nothing covers it."""
from . import CAPABILITIES, registry

TIER_RANK = {"free": 0, "freemium": 1, "manual": 2, "paid": 3}


def _any(rows, *keys):
    return any(any(r.get(k) not in (None, "", 0) for k in keys) for r in rows)


def received(d):
    """Which capabilities have numbers in data.json right now."""
    reels, acc = d.get("reels", []), d.get("account", [])
    has = {
        "followers_daily": sum(1 for a in acc if a.get("followers") is not None) >= 2,
        "reach": _any(acc, "reach", "reels_reach"), "engaged": _any(acc, "engaged", "accounts_engaged"),
        "profile_visits": _any(acc, "profile_visits") or bool(d.get("profile_taps")), "link_taps": bool(d.get("profile_taps")),
        "age": bool(d.get("age_gender")), "gender": bool(d.get("age_gender")), "country": bool(d.get("countries")), "city": bool(d.get("cities")),
        "online_hours": bool(d.get("online_hours")),
        "views": _any(reels, "views"), "reel_reach": _any(reels, "reach"), "likes": _any(reels, "likes"), "comments": _any(reels, "comments"),
        "saves": _any(reels, "saves"), "shares": _any(reels, "shares"), "reposts": _any(reels, "reposts"), "avg_watch": _any(reels, "avg_watch"),
        "watch_total": _any(reels, "watch_total"), "duration": _any(reels, "duration"), "view_rate": _any(reels, "view_rate"),
        "follows": _any(reels, "follows"), "follower_split": bool(d.get("follower_type")),
        "posts": bool(d.get("posts")), "stories": bool(d.get("stories")), "competitors": bool(d.get("competitors")),
    }
    return {k: bool(v) for k, v in has.items()}


def matrix(user, conns, d, scrapers_ok=True):
    provs = registry()
    connected = [p for pid, p in provs.items() if pid in conns and p.status == "ready"]
    have = received(d or {})
    groups = []
    for gid, g in CAPABILITIES.items():
        items = []
        for cap, label in g["items"].items():
            by = [p.id for p in connected if cap in p.caps]
            got = have.get(cap)
            options = sorted((p for p in provs.values() if cap in p.caps and p.status == "ready" and p.id not in conns
                              and (scrapers_ok or p.kind != "scraper")), key=lambda p: (TIER_RANK.get(p.tier, 9), ["official", "analytics", "scraper", "manual"].index(p.kind)))
            items.append({"id": cap, "label": label, "sources": by, "received": got if got is not None else bool(by),
                          "state": "ok" if (got or (got is None and by)) else ("waiting" if by else "missing"),
                          "suggest": [{"id": p.id, "title": p.title_fa, "tier": p.tier} for p in options[:3]]})
        groups.append({"id": gid, "title": g["title"], "items": items})
    return {"groups": groups, "connected": [p.id for p in connected],
            "missing": [i for g in groups for i in g["items"] if i["state"] == "missing"]}


def hint(user, conns, d, cap):
    """The one-line nudge for an empty card: «برای این عدد، X رو وصل کن»."""
    m = matrix(user, conns, d)
    for g in m["groups"]:
        for i in g["items"]:
            if i["id"] == cap and i["state"] != "ok" and i["suggest"]:
                return i["suggest"][0]
    return None
