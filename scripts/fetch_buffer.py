#!/usr/bin/env python3
"""Pull Instagram post metrics from Buffer's GraphQL API (https://api.buffer.com) into
$SAJADAI_STATE/raw/buffer.json, for scripts/shape.py. Run for each user by the panel (sajadai/pipeline.py).

Buffer imports every post on a connected channel, including ones published straight from the
Instagram app (via = "network"), and refreshes their metrics about once a day: views, reach,
likes, comments, saves, shares, follows (new followers from that post) and average watch time.
It has no account-level stats (follower count, daily reach, demographics) and no 3-second view
rate; those come from scripts/fetch_instagram.py or the Metricool history.

Key: BUFFER_API_KEY in /etc/sajadai-dashboard/buffer.env (Buffer → Settings → API). The Instagram
account must be connected as a channel in Buffer.

Usage: SAJADAI_STATE=/var/lib/sajadai-dashboard python3 scripts/fetch_buffer.py
"""
import json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

API = "https://api.buffer.com"
STATE = os.environ.get("SAJADAI_STATE") or sys.exit("set SAJADAI_STATE (e.g. /var/lib/sajadai-dashboard)")
OUT = os.path.join(STATE, "raw", "buffer.json")
ENV = os.environ.get("SAJADAI_BUFFER_ENV", "/etc/sajadai-dashboard/buffer.env")
MAX_PAGES = 10

POSTS = """query($org: OrganizationId!, $channels: [ChannelId!], $after: String) {
  posts(first: 50, after: $after, input: { organizationId: $org, filter: { status: [sent], channelIds: $channels } }) {
    edges { node {
      id text sentAt externalLink via channelId
      metadata { ... on InstagramPostMetadata { type } }
      assets { thumbnail }
      metrics { type value unit }
      metricsUpdatedAt
    } }
    pageInfo { hasNextPage endCursor }
  }
}"""


def key():
    if os.environ.get("SAJADAI_BUFFER_KEY"):  # the panel passes each user's key this way
        return os.environ["SAJADAI_BUFFER_KEY"]
    try:
        with open(ENV, encoding="utf-8") as f:
            m = re.search(r"^\s*BUFFER_API_KEY\s*=\s*['\"]?([^'\"\s]+)", f.read(), re.M)
    except FileNotFoundError:
        m = None
    return m[1] if m else sys.exit(f"no Buffer key: put BUFFER_API_KEY=... in {ENV}")


def gql(k, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json",
                                                          "User-Agent": "sajadai-dashboard"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"Buffer rejected the key (HTTP {e.code}); make a new one in Buffer → Settings → API: {ENV}")
            if (e.code == 429 or e.code >= 500) and attempt < 2:
                time.sleep(int(e.headers.get("Retry-After") or 10 * (attempt + 1)))
                continue
            raise
    if out.get("errors"):
        raise RuntimeError("Buffer API: " + "; ".join(e.get("message", "?") for e in out["errors"]))
    return out["data"]


def main():
    k = key()
    orgs = gql(k, "{ account { organizations { id name } } }")["account"]["organizations"]
    channels = []
    for o in orgs:
        q = "query($org: OrganizationId!) { channels(input: { organizationId: $org }) { id name service isDisconnected } }"
        channels += [dict(c, organization=o["id"]) for c in gql(k, q, {"org": o["id"]})["channels"] if c["service"] == "instagram"]
    if not channels:
        sys.exit("Buffer has no Instagram channel: connect your Instagram account in Buffer (Channels → Connect → Instagram) and run again")
    for c in channels:
        if c["isDisconnected"]:
            print(f"warning: Buffer says Instagram channel {c['name']} is disconnected; reconnect it in Buffer", file=sys.stderr)

    posts = []
    for org in sorted({c["organization"] for c in channels}):
        ids = [c["id"] for c in channels if c["organization"] == org]
        after = None
        for _ in range(MAX_PAGES):
            page = gql(k, POSTS, {"org": org, "channels": ids, "after": after})["posts"]
            for e in page["edges"]:
                n = e["node"]
                posts.append({"id": n["id"], "type": (n.get("metadata") or {}).get("type"), "text": n.get("text") or "",
                              "sent_at": n.get("sentAt"), "url": n.get("externalLink") or "", "via": n.get("via"),
                              "thumbnail": next((a["thumbnail"] for a in n.get("assets") or [] if a.get("thumbnail")), ""),
                              "metrics": {m["type"]: m["value"] for m in n.get("metrics") or []},
                              "metrics_updated_at": n.get("metricsUpdatedAt")})
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]

    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "channels": [{k2: c[k2] for k2 in ("id", "name", "isDisconnected")} for c in channels], "posts": posts}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    with_metrics = sum(1 for p in posts if p["metrics"])
    print(f"{out['fetched_at']} buffer.json: {len(channels)} Instagram channel(s), {len(posts)} posts, {with_metrics} with metrics")


if __name__ == "__main__":
    main()
