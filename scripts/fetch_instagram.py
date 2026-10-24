#!/usr/bin/env python3
"""Pull the page's stats straight from Instagram's API (Instagram API with Instagram Login) into
$SAJADAI_STATE/raw/ig.json, for scripts/shape.py. Replaces the Metricool + claude.ai routine on a
standalone server; run every 6 hours by deploy/refresh.sh.

Each run gets: the account (followers_count, which it also records per day, since Instagram's daily
follower series isn't dependable), the newest media with their insights (reels: views, reach,
saves, shares, likes, comments, average and total watch time, 3-second skip rate, reposts), the last
3 days of account insights (they settle over ~48h, so they're fetched again), and follower
demographics once the page has 100 followers. It merges with the previous ig.json, so older days
and media keep their numbers.

Token: IG_ACCESS_TOKEN in /etc/sajadai-dashboard/instagram.env (a long-lived token with
instagram_business_basic and instagram_business_manage_insights). The script refreshes it every
7 days (tokens last 60) and keeps the current one in $SAJADAI_STATE/ig-token.json.

Not available with Instagram Login: competitors (business_discovery needs Facebook Login), follows
per reel, and a best-time estimate (the page keeps Metricool's last one).

Usage: SAJADAI_STATE=/var/lib/sajadai-dashboard python3 scripts/fetch_instagram.py
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.instagram.com/v26.0"
STATE = os.environ.get("SAJADAI_STATE") or sys.exit("set SAJADAI_STATE (e.g. /var/lib/sajadai-dashboard)")
OUT = os.path.join(STATE, "raw", "ig.json")
TOKEN_STATE = os.path.join(STATE, "ig-token.json")
ENV = os.environ.get("SAJADAI_IG_ENV", "/etc/sajadai-dashboard/instagram.env")
TEH = timezone(timedelta(hours=3, minutes=30))
REFRESH_DAYS = 7
INSIGHT_DAYS = 90  # newer media get fresh insights every run; older ones keep their last numbers
REEL_METRICS = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time", "reels_skip_rate", "reposts"]
FEED_METRICS = ["views", "reach", "saved", "shares", "likes", "comments", "total_interactions", "follows", "profile_visits"]
CORE = ["views", "reach", "saved", "shares", "likes", "comments"]


class ApiError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.code = err.get("code")
        super().__init__(f"HTTP {status}: {err.get('message') or body}")


def get(path, token, **params):
    url = path if path.startswith("https://") else f"{API}/{path}?" + urllib.parse.urlencode({**params, "access_token": token})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                body = json.load(e)
            except ValueError:
                body = {}
            if e.code >= 500 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise ApiError(e.code, body) from None
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def token():
    st = load(TOKEN_STATE, {})
    tok = st.get("access_token")
    given = os.environ.get("SAJADAI_IG_TOKEN")  # the panel passes each user's token this way
    if given and st.get("source") != given[-12:]:
        # a token entered in the panel replaces whatever was refreshed from an older one
        st = {"access_token": given, "refreshed_at": None, "added_at": time.time(), "source": given[-12:]}
        save(TOKEN_STATE, st, 0o600)
        tok = given
    if not tok:
        try:
            with open(ENV, encoding="utf-8") as f:
                m = re.search(r"^\s*IG_ACCESS_TOKEN\s*=\s*['\"]?([^'\"\s]+)", f.read(), re.M)
            tok = m[1] if m else None
        except FileNotFoundError:
            pass
        if not tok:
            sys.exit(f"no Instagram token: put IG_ACCESS_TOKEN=... in {ENV}")
        st = {"access_token": tok, "refreshed_at": None, "added_at": time.time()}
        save(TOKEN_STATE, st, 0o600)
    last = st.get("refreshed_at") or st.get("added_at") or 0
    # a token can only be refreshed once it's 24h old; after that, every REFRESH_DAYS
    if time.time() - last > (REFRESH_DAYS * 86400 if st.get("refreshed_at") else 86400):
        try:
            r = get("https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode(
                {"grant_type": "ig_refresh_token", "access_token": tok}), tok)
            st = {"access_token": r["access_token"], "refreshed_at": time.time(), "expires_in": r.get("expires_in"),
                  "source": st.get("source")}
            save(TOKEN_STATE, st, 0o600)
            tok = st["access_token"]
            print("token refreshed")
        except (ApiError, KeyError) as e:
            print(f"token refresh failed, using the current one: {e}", file=sys.stderr)
    return tok


def first(obj):
    # the docs show /me wrapped in {"data": [...]}; the live API answers with a flat object
    return obj["data"][0] if isinstance(obj.get("data"), list) and obj["data"] else obj


def insights(media_id, metrics, tok):
    r = get(f"{media_id}/insights", tok, metric=",".join(metrics))
    out = {}
    for d in r.get("data", []):
        v = (d.get("values") or [{}])[0].get("value")
        if v is None and isinstance(d.get("total_value"), dict):
            v = d["total_value"].get("value")
        out[d["name"]] = v
    return out


def media_insights(m, tok):
    want = REEL_METRICS if m.get("media_product_type") == "REELS" or m.get("media_type") == "VIDEO" else FEED_METRICS
    try:
        return insights(m["id"], want, tok)
    except ApiError:
        pass  # one unsupported metric fails the whole call; take the core ones, then the rest one by one
    out = insights(m["id"], CORE, tok)
    for metric in want:
        if metric not in out:
            try:
                out.update(insights(m["id"], [metric], tok))
            except ApiError:
                out[metric] = None
    return out


def day_bounds(day):
    start = datetime.fromisoformat(day).replace(tzinfo=TEH)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp()) - 1


def account_day(user, day, tok):
    """One Tehran day of account insights; a metric Instagram won't give stays None."""
    since, until = day_bounds(day)
    base = {"period": "day", "metric_type": "total_value", "since": since, "until": until}

    def total(metric, breakdown=None):
        try:
            r = get(f"{user}/insights", tok, metric=metric, **base, **({"breakdown": breakdown} if breakdown else {}))
        except ApiError as e:
            print(f"{day} {metric} {breakdown or ''}: {e}", file=sys.stderr)
            return {}
        out = {}
        for d in r.get("data", []):
            tv = d.get("total_value") or {}
            if breakdown:
                for b in tv.get("breakdowns", []):
                    for res in b.get("results", []):
                        out[(d["name"], "|".join(res.get("dimension_values", [])))] = res.get("value")
            else:
                out[d["name"]] = tv.get("value")
        return out

    t = total("reach,views,accounts_engaged,total_interactions,profile_links_taps")
    by_type = total("views,reach", "media_product_type")
    by_follow = total("reach", "follow_type")
    fu = total("follows_and_unfollows", "follow_type")
    return {"day": day, "reach": t.get("reach"), "views": t.get("views"), "accounts_engaged": t.get("accounts_engaged"),
            "total_interactions": t.get("total_interactions"), "profile_links_taps": t.get("profile_links_taps"),
            "reels_views": by_type.get(("views", "REELS")), "reels_reach": by_type.get(("reach", "REELS")),
            "follower_reach": by_follow.get(("reach", "FOLLOWER")), "non_follower_reach": by_follow.get(("reach", "NON_FOLLOWER")),
            "follows": fu.get(("follows_and_unfollows", "FOLLOWER")), "unfollows": fu.get(("follows_and_unfollows", "NON_FOLLOWER"))}


def demographics(user, tok):
    base = {"metric": "follower_demographics", "period": "lifetime", "metric_type": "total_value", "timeframe": "this_month"}

    def rows(breakdown):
        r = get(f"{user}/insights", tok, **base, breakdown=breakdown)
        out = []
        for d in r.get("data", []):
            for b in (d.get("total_value") or {}).get("breakdowns", []):
                out += [(res.get("dimension_values", []), res.get("value")) for res in b.get("results", [])]
        return out

    dem = {}
    try:
        dem["country"] = [{"key": k[0], "value": v} for k, v in rows("country") if k]
        try:
            dem["age_gender"] = [{"age": k[0], "gender": k[1], "value": v} for k, v in rows("age,gender") if len(k) == 2]
        except ApiError:  # some accounts only take one breakdown per call
            dem["age_gender"] = [{"age": k[0], "gender": "", "value": v} for k, v in rows("age") if k]
    except ApiError as e:
        print(f"demographics: {e}", file=sys.stderr)
    return dem


def probe_duration(url):
    """A video's length in seconds from its file, with ffprobe (reads the header, not the whole video)."""
    import shutil, subprocess
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url],
                           capture_output=True, text=True, timeout=60)
        return round(float(r.stdout.strip()), 1) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def main():
    tok = token()
    prev = load(OUT, {})
    try:
        me = first(get("me", tok, fields="user_id,username,account_type,followers_count,media_count"))
    except ApiError as e:
        sys.exit(f"Instagram rejected the token or the request ({e}); a new token may be needed: {ENV}")
    user = me.get("user_id") or me.get("id")
    now = datetime.now(timezone.utc)
    today = now.astimezone(TEH).date()

    media, url = [], None
    # media_url: the video file, for its duration (IG Media has no duration field; media_url can be missing for
    # licensed audio) — https://developers.facebook.com/docs/instagram-platform/reference/instagram-media
    fields = "id,caption,media_type,media_product_type,permalink,timestamp,thumbnail_url,like_count,comments_count,media_url"
    for _ in range(4):  # the newest ~200 posts are plenty for a page this size
        r = get(url, tok) if url else get("me/media", tok, fields=fields, limit=50)
        media += r.get("data", [])
        url = (r.get("paging") or {}).get("next")
        if not url:
            break
    old = {m["id"]: m for m in prev.get("media", [])}
    for m in media:
        if m.get("media_product_type") == "STORY":
            continue
        age = (now - datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))).days if m.get("timestamp") else 0
        if age <= INSIGHT_DAYS or not old.get(m["id"], {}).get("insights"):
            try:
                m["insights"] = media_insights(m, tok)
            except ApiError as e:
                print(f"media {m['id']}: {e}", file=sys.stderr)
                m["insights"] = old.get(m["id"], {}).get("insights") or {}
        else:
            m["insights"] = old[m["id"]]["insights"]
        m["duration"] = old.get(m["id"], {}).get("duration")
        if m["duration"] is None and m.get("media_url") and m.get("media_type") == "VIDEO":
            m["duration"] = probe_duration(m["media_url"])
        m.pop("media_url", None)  # signed and short-lived; not worth keeping
        old[m["id"]] = m

    daily = {d["day"]: d for d in prev.get("daily", [])}
    for i in range(3):
        d = (today - timedelta(days=i)).isoformat()
        row = account_day(user, d, tok)
        keep = daily.get(d, {})
        daily[d] = {k: (v if v is not None else keep.get(k)) for k, v in row.items()}

    followers = {f["day"]: f for f in prev.get("followers", [])}
    if me.get("followers_count") is not None:
        followers[today.isoformat()] = {"day": today.isoformat(), "followers": me["followers_count"]}

    out = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "account": {k: me.get(k) for k in ("user_id", "username", "account_type", "followers_count", "media_count")},
        "media": sorted(old.values(), key=lambda m: m.get("timestamp") or "", reverse=True),
        "daily": sorted(daily.values(), key=lambda d: d["day"]),
        "followers": sorted(followers.values(), key=lambda f: f["day"]),
        "demographics": demographics(user, tok) if (me.get("followers_count") or 0) >= 100 else prev.get("demographics", {}),
    }
    save(OUT, out)
    reels = sum(1 for m in out["media"] if m.get("media_product_type") == "REELS")
    print(f"{out['fetched_at']} ig.json: @{me.get('username')}, {me.get('followers_count')} followers, "
          f"{len(out['media'])} media ({reels} reels), {len(out['daily'])} days")
    try:  # the numbers are saved already; comments are extra and mustn't fail the refresh
        print(fetch_comments(out["media"], me.get("username"), tok, now))
    except Exception as e:  # noqa: BLE001
        print(f"comments skipped: {e}", file=sys.stderr)


COMMENTS_OUT = os.path.join(STATE, "raw", "ig_comments.json")
COMMENT_DAYS, COMMENT_POSTS = 30, 25


def fetch_comments(media, username, tok, now):
    """Comments (with replies) on the posts of the last 30 days, for the panel's comment page. Needs the
    instagram_business_manage_comments permission on the token; without it the reason is saved instead."""
    recent = [m for m in media if m.get("timestamp") and m.get("comments_count") and m.get("media_product_type") != "STORY"
              and (now - datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))).days <= COMMENT_DAYS][:COMMENT_POSTS]
    out = {"fetched_at": now.isoformat(timespec="seconds"), "username": username, "error": None, "posts": []}
    for m in recent:
        try:
            r = get(f"{m['id']}/comments", tok, fields="id,text,timestamp,username,like_count,replies{id,text,timestamp,username}", limit=50)
        except ApiError as e:
            if e.status in (400, 403) or e.code in (10, 200):
                out["error"] = "permission"  # the token wasn't made with instagram_business_manage_comments
                break
            print(f"comments {m['id']}: {e}", file=sys.stderr)
            continue
        comments = [{"id": c["id"], "text": c.get("text", ""), "at": c.get("timestamp"), "user": c.get("username"), "likes": c.get("like_count"),
                     "replies": [{"text": x.get("text", ""), "user": x.get("username"), "at": x.get("timestamp")} for x in (c.get("replies") or {}).get("data", [])]}
                    for c in r.get("data", [])]
        out["posts"].append({"id": m["id"], "url": m.get("permalink"), "caption": (m.get("caption") or "")[:300], "published": m.get("timestamp"), "comments": comments})
    save(COMMENTS_OUT, out)
    if out["error"]:
        return "ig_comments.json: no permission to read comments (instagram_business_manage_comments)"
    return f"ig_comments.json: {sum(len(p['comments']) for p in out['posts'])} comments on {len(out['posts'])} posts"


if __name__ == "__main__":
    main()
