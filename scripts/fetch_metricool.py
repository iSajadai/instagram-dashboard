#!/usr/bin/env python3
"""Pull a brand's Instagram stats from Metricool's REST API (needs Metricool's Advanced plan) into
$SAJADAI_STATE/raw/, written in the same row format the claude.ai routine saved from Metricool's MCP
connector, so scripts/shape.py reads them unchanged.

Writes: reels.json, posts.json, account.json, best_time.json, competitors.json. A call that fails
leaves its file as it was and the others still run; the script fails only if reels and account both do.

Credentials (from the panel, or for a single server from the environment):
  METRICOOL_TOKEN   the API token (Metricool → Account settings → API)
  METRICOOL_USER    userId
  METRICOOL_BLOG    blogId (the brand)

Usage: SAJADAI_STATE=... METRICOOL_TOKEN=... METRICOOL_USER=... METRICOOL_BLOG=... python3 scripts/fetch_metricool.py
API reference: https://app.metricool.com/resources/apidocs/index.html
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

API = "https://app.metricool.com/api"
STATE = os.environ.get("SAJADAI_STATE") or sys.exit("set SAJADAI_STATE")
RAW = os.path.join(STATE, "raw")
TZ = os.environ.get("SAJADAI_TZ", "Asia/Tehran")
TEH = timezone(timedelta(hours=3, minutes=30))
DAYS = 30


class ApiError(Exception):
    pass


def creds():
    c = {k: os.environ.get(v) for k, v in (("token", "METRICOOL_TOKEN"), ("user", "METRICOOL_USER"), ("blog", "METRICOOL_BLOG"))}
    missing = [k for k, v in c.items() if not v]
    if missing:
        sys.exit("Metricool credentials missing: " + ", ".join(missing))
    return c


def get(c, path, **params):
    q = urllib.parse.urlencode({**params, "userId": c["user"], "blogId": c["blog"]}, doseq=True)
    req = urllib.request.Request(f"{API}{path}?{q}", headers={"X-Mc-Auth": c["token"], "Accept": "application/json",
                                                             "User-Agent": "sajadai-dashboard"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ApiError(f"Metricool rejected the credentials (HTTP {e.code}); the API needs the Advanced plan") from None
            if (e.code == 429 or e.code >= 500) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise ApiError(f"{path}: HTTP {e.code}") from None
        except urllib.error.URLError as e:
            if attempt == 2:
                raise ApiError(f"{path}: {e.reason}") from None
            time.sleep(5)


def stamp(dt):
    """'2026-10-20T14:07:44' (or with an offset) -> '20261020140744', the MCP connector's format."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", str(dt or ""))
    return "".join(m.groups()) if m else ""


def pub(o):
    p = o.get("publishedAt")
    return stamp(p.get("dateTime") if isinstance(p, dict) else p)


def secs(v):
    # Instagram gives watch time in ms; Metricool may pass it through or convert it
    return None if v is None else round(v / 1000, 3) if v > 300 else v


def items(c, path, **params):
    out, page = [], get(c, path, **params)
    for _ in range(20):
        out += page.get("data") or []
        nxt = (page.get("page") or {}).get("next")
        if not nxt:
            break
        page = get(c, nxt.replace(API, "")) if nxt.startswith("http") else get(c, path, **params, page=nxt)
    return out


def save(name, obj):
    os.makedirs(RAW, exist_ok=True)
    p = os.path.join(RAW, name + ".json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def reels(c, rng):
    rows = []
    for r in items(c, "/v2/analytics/reels/instagram", **rng):
        skip = r.get("reelsSkipRate")
        # columns as shape.py reads them: published caption url views reach avg_watch retention view_rate shares saves
        # likes comments reposts reel_id cover watch_total duration engagement
        rows.append([pub(r), r.get("content") or "", r.get("url") or "", r.get("views"), r.get("reach"),
                     secs(r.get("averageWatchTime")), None, None if skip is None else round(100 - skip, 1),
                     r.get("shares"), r.get("saved"), r.get("likes"), r.get("comments"), r.get("reposts"),
                     str(r.get("reelId") or ""), r.get("imageUrl") or "", secs(r.get("videoViewTotalTime")),
                     r.get("durationSeconds"), r.get("engagement")])
    return {"rows": rows}


def posts(c, rng):
    rows = []
    for p in items(c, "/v2/analytics/posts/instagram", **rng):
        # published caption url type views reach saves shares likes comments follows
        rows.append([pub(p), p.get("content") or "", p.get("url") or "", p.get("type") or "", p.get("views"), p.get("reach"),
                     p.get("saved"), p.get("shares"), p.get("likes"), p.get("comments"), p.get("follows")])
    return {"rows": rows}


def account(c, start, end):
    """One row per day: followers gained lost reels reels_views reels_reach reels_shares views reach engaged, date last."""
    days = {}

    def put(day, i, v):
        days.setdefault(day, [None] * 10)[i] = v

    def timeline(subject, metric, i):
        try:
            r = get(c, "/v2/analytics/timelines", network="instagram", subject=subject, metric=metric, timezone=TZ,
                    **{"from": start.strftime("%Y-%m-%dT%H:%M:%S"), "to": end.strftime("%Y-%m-%dT%H:%M:%S")})
        except ApiError as e:
            print(f"timeline {subject}/{metric}: {e}", file=sys.stderr)
            return
        for series in r.get("data") or []:
            for v in series.get("values") or []:
                d = str(v.get("dateTime") or "")[:10].replace("-", "")
                if len(d) == 8:
                    put(d, i, v.get("value"))

    try:  # absolute follower count: only the older stats endpoint has it, as [timestamp-or-date, value] pairs
        for pair in get(c, "/stats/timeline/igFollowers", start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d")) or []:
            t, v = pair[0], pair[1]
            d = (datetime.fromtimestamp(int(t) / 1000, TEH).strftime("%Y%m%d") if str(t).isdigit() and len(str(t)) > 8
                 else str(t).replace("-", "")[:8])
            put(d, 0, float(v) if v not in (None, "") else None)
    except (ApiError, ValueError, TypeError, IndexError) as e:
        print(f"followers: {e}", file=sys.stderr)
    for subject, metric, i in (("account", "followers_gained", 1), ("account", "followers_lost", 2), ("reels", "count", 3),
                               ("reels", "videoviews", 4), ("reels", "reach", 5), ("reels", "shares", 6)):
        timeline(subject, metric, i)
    if not days:
        raise ApiError("no daily account data")
    return {"rows": [vals + [d] for d, vals in sorted(days.items())]}


def best_time(c, start):
    r = get(c, "/v2/scheduler/besttimes/instagram", timezone=TZ, start=start.strftime("%Y-%m-%dT%H:%M:%S"),
            end=(start + timedelta(days=7) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S"))
    return {"data": r.get("data") or []}


def competitors(c, rng):
    rows = []
    for x in get(c, "/v2/analytics/competitors/instagram", limit=20, **rng).get("data") or []:
        # screen_name display_name followers posts reels likes engagement
        rows.append([x.get("screenName") or "", x.get("displayName") or "", x.get("followers"), x.get("posts"), x.get("reels"),
                     x.get("likes"), x.get("engagement")])
    return {"rows": rows}


def main():
    c = creds()
    now = datetime.now(TEH).replace(microsecond=0)
    start = now - timedelta(days=DAYS)
    rng = {"from": start.strftime("%Y-%m-%dT%H:%M:%S"), "to": now.strftime("%Y-%m-%dT%H:%M:%S"), "timezone": TZ}
    try:
        get(c, "/admin/simpleProfiles")  # checks the credentials before anything is written
    except ApiError as e:
        sys.exit(str(e))
    ok = {}
    for name, fn in (("reels", lambda: reels(c, rng)), ("posts", lambda: posts(c, rng)),
                     ("account", lambda: account(c, start, now)), ("best_time", lambda: best_time(c, now)),
                     ("competitors", lambda: competitors(c, rng))):
        try:
            data = fn()
            save(name, data)
            ok[name] = len(data.get("rows", data.get("data", [])))
        except ApiError as e:
            print(f"{name}: {e} (kept the previous file)", file=sys.stderr)
    if "reels" not in ok and "account" not in ok:
        sys.exit("Metricool: neither reels nor account data came back")
    print(f"{now.isoformat()} metricool: " + ", ".join(f"{k} {v}" for k, v in ok.items()))


if __name__ == "__main__":
    main()
