"""Sending a reel plan to Buffer (https://api.buffer.com, GraphQL) with the user's own key: either as
an idea in Buffer's Ideas board (text only, no video needed) or as a scheduled Instagram reel, which
Instagram only accepts with a video, so it needs a public video URL. Nothing here reads metrics;
that is scripts/fetch_buffer.py."""
import json, urllib.error, urllib.request

API = "https://api.buffer.com"


class PublishError(Exception):
    pass


def gql(key, query, variables=None):
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "sajadai-dashboard"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise PublishError("Buffer کلید رو قبول نکرد؛ تو تنظیمات کلید تازه بذار")
        raise PublishError(f"Buffer جواب نداد (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError):
        raise PublishError("به Buffer وصل نشد؛ چند دقیقهٔ دیگه دوباره امتحان کن")
    if out.get("errors"):
        raise PublishError("Buffer: " + "; ".join(e.get("message", "?") for e in out["errors"]))
    return out["data"]


def channels(key):
    """The Instagram channels connected in Buffer, with their organization."""
    out = []
    for o in gql(key, "{ account { organizations { id name } } }")["account"]["organizations"]:
        q = "query($org: OrganizationId!) { channels(input: { organizationId: $org }) { id name service isDisconnected } }"
        out += [{"id": c["id"], "name": c["name"], "organization": o["id"], "disconnected": bool(c.get("isDisconnected"))}
                for c in gql(key, q, {"org": o["id"]})["channels"] if c["service"] == "instagram"]
    return out


def _result(payload, ok_type):
    """Buffer answers a mutation with a union: the success object or one of several error objects."""
    if payload.get("__typename") == ok_type:
        return payload
    raise PublishError("Buffer: " + (payload.get("message") or payload.get("__typename") or "خطای ناشناخته"))


CREATE_IDEA = """mutation($input: CreateIdeaInput!) { createIdea(input: $input) {
  __typename
  ... on Idea { id }
  ... on IdeaResponse { idea { id } }
  ... on InvalidInputError { message } ... on UnauthorizedError { message } ... on UnexpectedError { message } ... on LimitReachedError { message }
} }"""


def send_idea(key, organization, title, text, date=None):
    content = {"title": title, "text": text, "services": ["instagram"]}
    if date:
        content["date"] = date
    p = gql(key, CREATE_IDEA, {"input": {"organizationId": organization, "content": content}})["createIdea"]
    if p.get("__typename") == "IdeaResponse":
        return {"kind": "idea", "id": (p.get("idea") or {}).get("id")}
    return {"kind": "idea", "id": _result(p, "Idea")["id"]}


CREATE_POST = """mutation($input: CreatePostInput!) { createPost(input: $input) {
  __typename
  ... on PostActionSuccess { post { id dueAt status } }
  ... on InvalidInputError { message } ... on UnauthorizedError { message } ... on UnexpectedError { message }
  ... on LimitReachedError { message } ... on NotFoundError { message } ... on RestProxyError { message }
} }"""


def schedule_reel(key, channel, text, video_url, due_at, draft=False, first_comment=""):
    """A reel at a set time (ISO 8601 with offset). As a draft it waits in Buffer for a final look."""
    ig = {"type": "reel", "shouldShareToFeed": True}
    if first_comment:
        ig["firstComment"] = first_comment
    inp = {"channelId": channel, "text": text, "mode": "customScheduled", "dueAt": due_at, "schedulingType": "automatic",
           "needsApproval": False, "saveToDraft": bool(draft), "source": "sajadai-dashboard",
           "assets": [{"video": {"url": video_url}}], "metadata": {"instagram": ig}}
    post = _result(gql(key, CREATE_POST, {"input": inp})["createPost"], "PostActionSuccess")["post"]
    return {"kind": "draft" if draft else "post", "id": post["id"], "due_at": post.get("dueAt"), "status": post.get("status")}
