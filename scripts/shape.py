#!/usr/bin/env python3
"""Turn raw Metricool answers (raw/*.json) + Claude-written content (content/*.json)
into data/data.json for the dashboard page.

Raw files are the Metricool MCP answers saved exactly as returned:
  raw/reels.json            getAnalyticsDataByMetrics  IGRE02 IGRE03 IGRE06 IGRE23 IGRE11 IGRE24 IGRE27 IGRE28 IGRE21 IGRE12 IGRE10 IGRE07 IGRE29
                                                       IGRE04 IGRE05 IGRE25 IGRE26 IGRE08
  raw/account.json          getAnalyticsDataByMetrics  IGEV01 IGEV43 IGEV44 IGEV22 IGEV23 IGEV26 IGEV39 IGEV05 IGEV06 IGEV42  (date last)
  raw/performance.json      getAnalyticsDataByMetrics  IGPF01 IGPF02 IGPF03 IGPF04 IGPF05 IGPF06 IGPF09 IGPF10 IGPF11
  raw/follower_type.json    getAnalyticsDataByMetrics  IGAC01 IGAC03 IGAC05 IGAC06
  raw/profile_taps.json     getAnalyticsDataByMetrics  IGAC01 IGAC12
  raw/posts.json            getAnalyticsDataByMetrics  IGPO02 IGPO03 IGPO06 IGPO07 IGPO28 IGPO14 IGPO15 IGPO27 IGPO13 IGPO08 IGPO29
  raw/competitor_posts.json getAnalyticsDataByMetrics  IGCP01 IGCP04 IGCP11 IGCP06 IGCP07 IGCP08 IGCP09 IGCP10
  raw/best_time.json        getBestTimeToPostByNetwork instagram, Asia/Tehran, next 7 days
  raw/competitors.json      getAnalyticsDataByMetrics  IGCO02 IGCO03 IGCO07 IGCO08 IGCO12 IGCO09 IGCO10
  raw/competitor_reels.json getAnalyticsDataByMetrics  IGCR01 IGCR03 IGCR04 IGCR06 IGCR07 IGCR08 IGCR09 IGCR10
  raw/stories.json          getAnalyticsDataByMetrics  IGST02 IGST07 IGST06 IGST10 IGST09 IGST08 IGST11 IGST12 IGST13
  raw/countries.json        getAnalyticsDataByMetrics  IGDP01 IGDP02
  raw/age_gender.json       getAnalyticsDataByMetrics  IGAG01 IGAG02 IGAG03
  raw/scheduled.json        getScheduledPosts          timezone Asia/Tehran, fromDate = today 00:00, toDate = 30 days later

Reels, daily account rows, per-reel daily performance and reel snapshots are merged with the
previous data/data.json, so history older than Metricool's 30-day free window is kept.
Every run also appends one snapshot per reel whose numbers changed (reel_snapshots), which
gives each reel's view curve even when Metricool's performance connector returns nothing.
Older raw files with fewer columns still work: missing columns become null.
Everything else is replaced. content/goals.json holds the goals shown with progress bars.
Each reel gets a topic: content/reel_topics.json ({reel url: topic id}) wins, otherwise the first
topic in content/topics.json with a keyword in the caption, otherwise "other".
content/experiments.json (hook/cover A/B tests) is passed through to the page as it is.

The panel (sajadai/pipeline.py) sets SAJADAI_STATE to each user's folder: raw/
and data/ then live there, and scripts/fetch_instagram.py writes raw/ig.json from Instagram's own
API. Whatever raw/ig.json has wins over the Metricool files for the reels, days, posts and audience
it covers; older history stays. scripts/fetch_buffer.py writes raw/buffer.json (Buffer's daily post
metrics): it fills reel numbers Instagram's API didn't give, replaces Metricool's older ones, and is
the only source of follows per reel. Reels are matched across sources by their Instagram shortcode. ideas/insights/benchmarks come from $SAJADAI_STATE/content when
scripts/write_content.py has written them there, else from the repo's content/.

Usage: python3 scripts/shape.py            (run from the repo root)
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# standalone servers keep raw/, data/ and the Claude-written content outside the git checkout
STATE = os.environ.get("SAJADAI_STATE", "")
RAW = os.path.join(STATE or ROOT, "raw")
CONTENT = os.path.join(ROOT, "content")
GENERATED = os.path.join(STATE, "content") if STATE else CONTENT
OUT = os.path.join(STATE or ROOT, "data", "data.json")
TEH = timezone(timedelta(hours=3, minutes=30))


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        if isinstance(v, str):
            v = json.loads(v)
        return v
    except FileNotFoundError:
        return default


def rows_of(name):
    a = load(os.path.join(RAW, name + ".json"), {"rows": []})
    if not isinstance(a, dict) or not isinstance(a.get("rows"), list):
        sys.exit(f"raw/{name}.json: expected an object with a 'rows' list")
    return a["rows"]


def num(x):
    if x is None or x == "":
        return None
    try:
        return float(x) if "." in str(x) else int(x)
    except ValueError:
        return None


def ts(s):
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", str(s or ""))
    return f"{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}" if m else None


def day(s):
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", str(s or ""))
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def at(r, i):
    return r[i] if i < len(r) else None


def norm(t):
    return re.sub(r"\s+", " ", str(t or "").replace("‌", " ").replace("ي", "ی").replace("ك", "ک")).lower()


def topic_of(reel, topics, manual):
    if reel.get("url") in manual:
        return manual[reel["url"]]
    cap = norm(reel.get("caption"))
    for t in topics:
        if any(norm(k) in cap for k in t.get("keywords", [])):
            return t["id"]
    return "other"


def scheduled_posts():
    """Metricool's scheduled posts, one row each; fields Metricool leaves out become empty."""
    a = load(os.path.join(RAW, "scheduled.json"), {"data": []})
    out = []
    for p in a.get("data", []) if isinstance(a, dict) else []:
        pub = p.get("publicationDate") or {}
        when = pub.get("dateTime") if isinstance(pub, dict) else pub
        ig = p.get("instagramData") or {}
        out.append({"id": str(p.get("id", "")), "when": str(when or "")[:16], "text": p.get("text") or "",
                    "networks": [str(x.get("network", "")) for x in p.get("providers") or [] if isinstance(x, dict)],
                    "type": str(ig.get("type", "")) if isinstance(ig, dict) else "", "draft": bool(p.get("draft"))})
    return sorted(out, key=lambda r: r["when"])


def user_file(name, default):
    """A file the user edits (goals, topics, experiments): theirs in $SAJADAI_STATE/content when the
    panel saved one, else the repo's defaults."""
    v = load(os.path.join(GENERATED, name), None)
    return v if v is not None else load(os.path.join(CONTENT, name), default)


def generated(name):
    """A Claude-written content file: the server's copy when there is one, else the repo's."""
    v = load(os.path.join(GENERATED, name), None)
    return v if isinstance(v, list) else load(os.path.join(CONTENT, name), [])


def teh(iso):
    """Instagram's UTC timestamp as Tehran wall-clock time, the way Metricool gives reel times."""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(TEH).strftime("%Y-%m-%dT%H:%M:%S")


def ms(x):
    return None if x is None else round(x / 1000, 1)


def ig_media(ig):
    """raw/ig.json (scripts/fetch_instagram.py) as reel rows and feed-post rows."""
    reels, posts = [], []
    for m in ig.get("media", []):
        i = m.get("insights") or {}
        is_reel = m.get("media_product_type") == "REELS" or (not m.get("media_product_type") and m.get("media_type") == "VIDEO")
        base = {"published": teh(m.get("timestamp")), "caption": m.get("caption") or "", "url": m.get("permalink") or "",
                "views": i.get("views"), "reach": i.get("reach"), "saves": i.get("saved"), "shares": i.get("shares"),
                "likes": i.get("likes", m.get("like_count")), "comments": i.get("comments", m.get("comments_count"))}
        if not base["url"]:
            continue
        if is_reel:
            skip = i.get("reels_skip_rate")
            reels.append({**base, "avg_watch": ms(i.get("ig_reels_avg_watch_time")), "retention": None,
                          # Instagram reports the share skipped in the first 3 seconds; Metricool's rate is the rest
                          "view_rate": None if skip is None else round(100 - skip, 1),
                          "reposts": i.get("reposts"), "reel_id": str(m.get("id", "")), "cover": m.get("thumbnail_url") or "",
                          "watch_total": ms(i.get("ig_reels_video_view_total_time")), "duration": None,
                          "engagement": None})
        else:
            posts.append({**base, "type": m.get("media_type") or "", "follows": i.get("follows")})
    return reels, posts


def shortcode(url):
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]+)", str(url or ""))
    return m[1] if m else None


def buffer_rows(buf):
    """raw/buffer.json (scripts/fetch_buffer.py) as {shortcode: reel fields} and feed-post rows."""
    def watch(v):
        # Instagram reports average watch time in ms; Buffer may pass it through or convert it
        return None if v is None else round(v / 1000, 1) if v > 300 else round(v, 1)

    reels, posts = {}, []
    for p in buf.get("posts", []):
        code, m = shortcode(p.get("url")), p.get("metrics") or {}
        if not code:
            continue
        row = {"published": teh(p.get("sent_at")), "caption": p.get("text") or "", "cover": p.get("thumbnail") or "",
               "views": m.get("views"), "reach": m.get("reach"), "likes": m.get("likes", m.get("reactions")),
               "comments": m.get("comments"), "saves": m.get("saves"), "shares": m.get("shares"),
               "follows": m.get("follows"), "avg_watch": watch(m.get("averageTimeWatched"))}
        if p.get("type") == "reel" or "/reel" in p.get("url", ""):
            reels[code] = row
        else:
            posts.append({**row, "url": p["url"], "type": (p.get("type") or "").upper()})
    return reels, posts


def main():
    prev = load(OUT, {})

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reel_cols = ["published", "caption", "url", "views", "reach", "avg_watch", "retention", "view_rate",
                 "shares", "saves", "likes", "comments", "reposts", "reel_id", "cover", "watch_total",
                 "duration", "engagement"]
    text_cols = ("caption", "url", "reel_id", "cover")
    reels = {}
    for r in prev.get("reels", []):
        reels[r["url"]] = r
    for r in rows_of("reels"):
        o = {}
        for i, c in enumerate(reel_cols):
            v = at(r, i)
            o[c] = str(v or "") if c in text_cols else ts(v) if c == "published" else num(v)
        if o["url"]:
            old = reels.get(o["url"], {})
            if old.get("follows") is not None:
                o["follows"] = old["follows"]
            reels[o["url"]] = o
    # Instagram's own API (standalone servers) wins over Metricool for every reel it returns
    ig = load(os.path.join(RAW, "ig.json"), None)
    ig_reels, ig_posts = ig_media(ig) if ig else ([], [])
    for o in ig_reels:
        old = reels.get(o["url"], {})
        reels[o["url"]] = {**old, **{k: v for k, v in o.items() if v is not None or k not in old}}
    # Buffer (daily) fills what Instagram's API didn't give and is fresher than Metricool's history;
    # follows per reel only Buffer has
    buf = load(os.path.join(RAW, "buffer.json"), None)
    buf_reels, buf_posts = buffer_rows(buf) if buf else ({}, [])
    by_code = {shortcode(u): u for u in reels}
    from_ig = {o["url"] for o in ig_reels}
    for code, b in buf_reels.items():
        url = by_code.get(code) or f"https://www.instagram.com/reel/{code}/"
        o = reels.setdefault(url, {"url": url})
        for k, v in b.items():
            if v is None or v == "":
                continue
            if k in ("caption", "published", "cover"):  # identity fields: only fill what's missing
                if not o.get(k):
                    o[k] = v
            elif k == "follows" or o.get(k) is None or url not in from_ig:
                o[k] = v

    # per-reel daily performance (views/interactions per day after publishing, follows per reel)
    perf = {(r["id"], r["day"]): r for r in prev.get("reel_daily", [])}
    for r in rows_of("performance"):
        pid, d = str(at(r, 0) or ""), day(str(at(r, 3) or "")[:8])
        if not pid or not d:
            continue
        perf[(pid, d)] = {"id": pid, "published": ts(at(r, 1)), "format": at(r, 2) or "", "day": d,
                          "views": num(at(r, 4)), "interactions": num(at(r, 5)), "saves": num(at(r, 6)),
                          "shares": num(at(r, 7)), "follows": num(at(r, 8))}
    follows = {}
    for p in perf.values():
        if p["follows"] is not None:
            follows[p["id"]] = follows.get(p["id"], 0) + p["follows"]
    for r in reels.values():
        if r.get("reel_id") in follows:
            r["follows"] = follows[r["reel_id"]]
        r.setdefault("follows", None)
    topics = user_file("topics.json", [])
    manual = user_file("reel_topics.json", {})
    for r in reels.values():
        r["topic"] = topic_of(r, topics, manual)

    # one snapshot per reel per run, only when something moved
    snaps = prev.get("reel_snapshots", [])
    last = {}
    for s in snaps:
        last[s["url"]] = s
    for r in reels.values():
        s = {"url": r["url"], "at": now, "views": r.get("views"), "reach": r.get("reach"),
             "saves": r.get("saves"), "shares": r.get("shares")}
        l = last.get(r["url"])
        if r.get("views") is not None and (not l or any(l.get(k) != s[k] for k in ("views", "reach", "saves", "shares"))):
            snaps.append(s)

    acc_cols = ["followers", "gained", "lost", "reels", "reels_views", "reels_reach", "reels_shares",
                "views", "reach", "engaged"]
    account = {r["day"]: r for r in prev.get("account", [])}
    for r in rows_of("account"):
        d = day(r[-1]) if r else None
        if not d:
            continue
        vals = r[:-1]  # date is last, so an older file with fewer columns leaves the new ones null
        if d not in account and all(not num(v) for v in vals):
            continue  # Metricool pads the window with all-zero days from before the page existed
        o = account.get(d, {"day": d})
        for i, c in enumerate(acc_cols):
            v = num(at(vals, i))
            if v is not None or c not in o:
                o[c] = v
        account[d] = o

    bt = load(os.path.join(RAW, "best_time.json"), {"data": []})
    best_time = [{"day_of_week": int(d["dayOfWeek"]), "hour": int(h["hourOfDay"]), "value": num(h["value"])}
                 for d in bt.get("data", []) for h in d.get("bestTimesByHour", [])]

    competitors = [{"screen_name": str(at(r, 0) or ""), "display_name": at(r, 1) or "", "followers": num(at(r, 2)),
                    "posts": num(at(r, 3)), "reels": num(at(r, 4)), "likes": num(at(r, 5)), "engagement": num(at(r, 6))}
                   for r in rows_of("competitors")]
    competitor_reels = [{"competitor": str(at(r, 0) or ""), "text": at(r, 1) or "", "url": str(at(r, 2) or ""),
                         "published": at(r, 3), "likes": num(at(r, 4)), "comments": num(at(r, 5)),
                         "interactions": num(at(r, 6)), "engagement": num(at(r, 7))}
                        for r in rows_of("competitor_reels")]
    stories = [{"published": ts(at(r, 0)), "type": at(r, 1) or "", "permalink": str(at(r, 2) or ""),
                "reach": num(at(r, 3)), "impressions": num(at(r, 4)), "exits": num(at(r, 5)),
                "replies": num(at(r, 6)), "taps_back": num(at(r, 7)), "taps_forward": num(at(r, 8))}
               for r in rows_of("stories")]
    countries = [{"country": str(at(r, 0) or ""), "followers": num(at(r, 1))} for r in rows_of("countries")]
    age_gender = [{"age": str(at(r, 0) or ""), "gender": str(at(r, 1) or ""), "followers": num(at(r, 2))}
                  for r in rows_of("age_gender")]

    ftype = {}
    for r in rows_of("follower_type"):
        d = day(at(r, 0))
        if d:
            ftype[(d, str(at(r, 1) or ""))] = {"day": d, "type": str(at(r, 1) or ""), "views": num(at(r, 2)), "reach": num(at(r, 3))}
    for f in prev.get("follower_type", []):
        ftype.setdefault((f["day"], f["type"]), f)
    taps = {f["day"]: f for f in prev.get("profile_taps", [])}
    for r in rows_of("profile_taps"):
        d = day(at(r, 0))
        if d:
            taps[d] = {"day": d, "taps": num(at(r, 1))}
    if ig:
        for f in ig.get("followers", []):  # followers_count recorded by every fetch, last one of the day
            account.setdefault(f["day"], {"day": f["day"]})["followers"] = f["followers"]
        for d in ig.get("daily", []):
            o = account.setdefault(d["day"], {"day": d["day"]})
            for k, src in (("gained", "follows"), ("lost", "unfollows"), ("reels_views", "reels_views"),
                           ("reels_reach", "reels_reach"), ("views", "views"), ("reach", "reach"), ("engaged", "accounts_engaged")):
                if d.get(src) is not None:
                    o[k] = d[src]
            o["reels"] = sum(1 for r in ig_reels if (r["published"] or "")[:10] == d["day"])
            if d.get("profile_links_taps") is not None:
                taps[d["day"]] = {"day": d["day"], "taps": d["profile_links_taps"]}
            for t, src in (("follower", "follower_reach"), ("non_follower", "non_follower_reach")):
                if d.get(src) is not None:
                    ftype[(d["day"], t)] = {"day": d["day"], "type": t, "views": None, "reach": d[src]}
    posts = [{"published": ts(at(r, 0)), "caption": at(r, 1) or "", "url": str(at(r, 2) or ""), "type": at(r, 3) or "",
              "views": num(at(r, 4)), "reach": num(at(r, 5)), "saves": num(at(r, 6)), "shares": num(at(r, 7)),
              "likes": num(at(r, 8)), "comments": num(at(r, 9)), "follows": num(at(r, 10))}
             for r in rows_of("posts")]
    competitor_posts = [{"competitor": str(at(r, 0) or ""), "text": at(r, 1) or "", "url": str(at(r, 2) or ""),
                         "published": ts(at(r, 3)) or at(r, 3), "likes": num(at(r, 4)), "comments": num(at(r, 5)),
                         "interactions": num(at(r, 6)), "engagement": num(at(r, 7))}
                        for r in rows_of("competitor_posts")]
    posts = ig_posts or buf_posts or posts
    if ig:
        dem = ig.get("demographics") or {}
        if dem.get("country"):
            countries = [{"country": c["key"], "followers": c["value"]} for c in dem["country"]]
        if dem.get("age_gender"):
            age_gender = [{"age": a["age"], "gender": a["gender"], "followers": a["value"]} for a in dem["age_gender"]]

    out = {
        "generated_at": now,
        "reels": sorted(reels.values(), key=lambda r: r.get("published") or ""),
        "account": sorted(account.values(), key=lambda r: r["day"]),
        "best_time": best_time,
        "competitors": competitors,
        "competitor_reels": competitor_reels,
        "stories": stories,
        "countries": countries,
        "age_gender": age_gender,
        "reel_daily": sorted(perf.values(), key=lambda r: (r["id"], r["day"])),
        "reel_snapshots": snaps,
        "follower_type": sorted(ftype.values(), key=lambda r: (r["day"], r["type"])),
        "profile_taps": sorted(taps.values(), key=lambda r: r["day"]),
        "posts": posts,
        "competitor_posts": competitor_posts,
        "scheduled": scheduled_posts(),
        "topics": topics,
        "experiments": user_file("experiments.json", []),
        "goals": user_file("goals.json", []),
        "ideas": generated("ideas.json"),
        "insights": generated("insights.json"),
        "benchmarks": generated("benchmarks.json"),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"data/data.json: {len(out['reels'])} reels, {len(out['account'])} days, "
          f"{len(best_time)} best-time cells, {len(competitors)} competitors, {len(stories)} stories, "
          f"{len(snaps)} reel snapshots, {len(perf)} reel-days, {len(posts)} posts")


if __name__ == "__main__":
    main()
