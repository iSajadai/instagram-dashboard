#!/usr/bin/env python3
"""Competitors without Metricool: Instagram's Business Discovery (Instagram API with Facebook Login) for
the accounts listed in content/competitor_handles.json, into raw/bd_competitors.json and
raw/bd_competitor_reels.json (the same rows shape.py reads from Metricool, plus each reel's views).

Business Discovery isn't offered with Instagram Login: it needs a Facebook Page linked to the page's
Instagram professional account and a token with instagram_basic, instagram_manage_insights and
pages_read_engagement (SAJADAI_FB_TOKEN). The Instagram account id is found from the token's Pages
when SAJADAI_FB_IG_ID isn't set. Only public business and creator accounts can be looked up.

Usage: SAJADAI_STATE=… SAJADAI_FB_TOKEN=… python3 scripts/fetch_discovery.py
"""
import json, os, statistics, sys, urllib.error, urllib.parse, urllib.request

API = "https://graph.facebook.com/v24.0"
STATE = os.environ.get("SAJADAI_STATE") or sys.exit("set SAJADAI_STATE")
RAW = os.path.join(STATE, "raw")
HANDLES = os.path.join(STATE, "content", "competitor_handles.json")
MEDIA_FIELDS = "caption,comments_count,like_count,media_product_type,permalink,timestamp,view_count"


def get(path, **params):
    url = f"{API}/{path}?" + urllib.parse.urlencode({**params, "access_token": os.environ["SAJADAI_FB_TOKEN"]})
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error", {})
        except ValueError:
            err = {}
        raise RuntimeError(f"HTTP {e.code}: {err.get('message') or e.reason}") from None


def ig_account():
    if os.environ.get("SAJADAI_FB_IG_ID"):
        return os.environ["SAJADAI_FB_IG_ID"]
    for page in get("me/accounts", fields="name,instagram_business_account", limit=50).get("data", []):
        if page.get("instagram_business_account"):
            return page["instagram_business_account"]["id"]
    sys.exit("no Instagram professional account is linked to this token's Facebook Pages")


def handles():
    try:
        with open(HANDLES, encoding="utf-8") as f:
            h = json.load(f)
    except (FileNotFoundError, ValueError):
        return []
    return [str(x).strip().lstrip("@").lower() for x in h if str(x).strip()][:20]


def lookup(ig_id, handle):
    fields = f"business_discovery.username({handle}){{username,name,followers_count,media_count,media.limit(30){{{MEDIA_FIELDS}}}}}"
    return get(ig_id, fields=fields)["business_discovery"]


def main():
    hs = handles()
    if not hs:
        print("no competitor handles (content/competitor_handles.json)")
        return
    ig_id = ig_account()
    comps, reels, problems = [], [], []
    for h in hs:
        try:
            b = lookup(ig_id, h)
        except RuntimeError as e:
            problems.append(f"@{h}: {e}")
            continue
        media = (b.get("media") or {}).get("data", [])
        followers = b.get("followers_count") or 0
        rs = [m for m in media if m.get("media_product_type") == "REELS"]
        views = [m["view_count"] for m in rs if m.get("view_count") is not None]
        median = statistics.median(views) if views else None
        likes = sum(m.get("like_count") or 0 for m in media)
        inter = [(m.get("like_count") or 0) + (m.get("comments_count") or 0) for m in media]
        eng = round(sum(inter) / len(inter) / followers * 100, 2) if inter and followers else None
        # screen_name display_name followers posts reels likes engagement median_views
        comps.append([b.get("username") or h, b.get("name") or "", followers, b.get("media_count"), len(rs), likes, eng, median])
        for m in rs:
            i = (m.get("like_count") or 0) + (m.get("comments_count") or 0)
            # competitor text url published likes comments interactions engagement views
            reels.append([b.get("username") or h, (m.get("caption") or "")[:1000], m.get("permalink") or "", m.get("timestamp"),
                          m.get("like_count"), m.get("comments_count"), i, round(i / followers * 100, 2) if followers else None, m.get("view_count")])
    os.makedirs(RAW, exist_ok=True)
    for name, rows in (("bd_competitors", comps), ("bd_competitor_reels", reels)):
        with open(os.path.join(RAW, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"rows": rows, "problems": problems}, f, ensure_ascii=False)
    print(f"business discovery: {len(comps)} accounts, {len(reels)} reels" + (f"; skipped: {'; '.join(problems)}" if problems else ""))
    if problems and not comps:
        sys.exit("no competitor could be looked up: " + "; ".join(problems))


if __name__ == "__main__":
    main()
