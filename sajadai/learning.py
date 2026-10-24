"""What the page's own reels teach, fed back into the next suggestions:

- spoken hooks: the first 3 seconds of each reel transcribed (when the video can be read: the Instagram
  API's media_url, with the user's OpenAI or Groq key), and the first frame kept;
- the learning loop: a published reel is linked to the board card it came from (by its caption or spoken
  hook against the card's title and hook), and each hook formula and post type gets this page's own
  median multiple, which the planner and the reel writer then favour.

Runs after every successful sync (pipeline.after_sync)."""
import json, re, shutil, subprocess, tempfile, time
from pathlib import Path

from . import analysis, config, store
from .fa import hooks
from .fa.text import normalize, words

MAX_TRANSCRIBE = 6  # per sync, newest first; each costs one short speech-to-text call


def content(uid, name, default):
    v = analysis.load(config.user_dir(uid) / "content" / name)
    return v if isinstance(v, type(default)) else default


def save(uid, name, data):
    p = config.user_dir(uid) / "content" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def code_of(url):
    m = re.search(r"/(?:reels?|p|tv)/([A-Za-z0-9_-]+)", str(url or ""))
    return m.group(1) if m else ""


# ---------- spoken hooks ----------

def media_urls(user):
    """{shortcode: fresh media_url} for the page's reels, from the Instagram API (signed links expire)."""
    from . import ig
    try:
        r = ig.call(user, "GET", "me/media", fields="id,permalink,media_url,media_product_type,media_type", limit=50)
    except ig.IGError:
        return {}
    return {code_of(m.get("permalink")): m["media_url"] for m in r.get("data", []) if m.get("media_url") and m.get("media_type") == "VIDEO"}


def first_seconds(url, tmp, secs=4):
    """The first seconds' audio (mp3) and the first frame (jpg) of a video URL, with ffmpeg."""
    audio, frame = tmp / "a.mp3", tmp / "f.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-t", str(secs), "-i", url, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio)], timeout=120)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.1", "-i", url, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", str(frame)], timeout=120)
    return (audio if audio.exists() else None), (frame if frame.exists() else None)


def spoken_hooks(uid):
    from . import critique
    user = store.get_user(uid)
    if not shutil.which("ffmpeg"):
        return 0
    t = critique.transcriber(user)
    if not t:
        return 0
    done = content(uid, "spoken_hooks.json", {})
    d = analysis.load(config.user_dir(uid) / "data" / "data.json") or {}
    todo = [r for r in sorted(d.get("reels", []), key=lambda r: r.get("published") or "", reverse=True) if code_of(r.get("url")) not in done][:MAX_TRANSCRIBE]
    if not todo:
        return 0
    urls = media_urls(user)
    frames = config.user_dir(uid) / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    client, model = t
    n = 0
    for r in todo:
        code = code_of(r.get("url"))
        if code not in urls:
            continue
        with tempfile.TemporaryDirectory() as tmpd:
            audio, frame = first_seconds(urls[code], Path(tmpd))
            text = ""
            if audio:
                try:
                    with open(audio, "rb") as f:
                        text = critique.clean(getattr(client.audio.transcriptions.create(model=model, file=f, language="fa"), "text", "") or "")
                except Exception as e:  # noqa: BLE001 — try again next sync
                    store.update_status(uid, learning_log=f"stt: {e}"[:300])
                    continue
            if frame:
                shutil.copy(frame, frames / f"{code}.jpg")
        done[code] = {"text": text, "at": int(time.time()), "frame": bool(frame)}
        n += 1
    save(uid, "spoken_hooks.json", done)
    return n


# ---------- the learning loop ----------

def tokens(text):
    return {w for w in words(normalize(str(text or "")).lower()) if len(w) > 2}


def similar(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def link_board(uid, d):
    """Cards still without a reel get the published reel whose caption or spoken hook matches them best
    (and that came out after the card was made)."""
    board = content(uid, "board.json", [])
    if not board:
        return 0
    spoken = content(uid, "spoken_hooks.json", {})
    taken = {c.get("reel") for c in board if c.get("reel")}
    reels = [r for r in d.get("reels", []) if r.get("url") and r["url"] not in taken]
    n = 0
    for c in board:
        if c.get("reel"):
            continue
        card_text = f"{c.get('title', '')} {c.get('hook', '')}"
        best, score = None, 0.0
        for r in reels:
            if c.get("created") and r.get("published") and str(r["published"])[:10] < time.strftime("%Y-%m-%d", time.gmtime(c["created"] - 86400)):
                continue
            s = max(similar(card_text, (r.get("caption") or "").split("\n")[0]), similar(c.get("hook", ""), (spoken.get(code_of(r["url"])) or {}).get("text", "")))
            if s > score:
                best, score = r, s
        if best and score >= 0.35:
            c.update(reel=best["url"], stage="published", moved=int(time.time()), linked="auto")
            reels.remove(best)
            n += 1
    if n:
        save(uid, "board.json", board)
    return n


def formula_stats(uid, d):
    """This page's own record per hook formula (caption first line, and the spoken hook when known)."""
    reels = [r for r in d.get("reels", []) if r.get("views") is not None]
    if len(reels) < 3:
        return {}
    views = sorted(r["views"] for r in reels)
    med = views[(len(views) - 1) // 2] or 1
    spoken = content(uid, "spoken_hooks.json", {})
    by = {}
    for r in reels:
        hook = (spoken.get(code_of(r["url"])) or {}).get("text") or (r.get("caption") or "").split("\n")[0]
        fid, name = hooks.classify(hook)
        if not fid:
            continue
        by.setdefault(fid, {"name": name, "multiples": []})["multiples"].append(round(r["views"] / med, 2))
    out = {}
    for fid, v in by.items():
        m = sorted(v["multiples"])
        out[str(fid)] = {"name": v["name"], "n": len(m), "median_multiple": m[(len(m) - 1) // 2]}
    return out


def run(uid):
    d = analysis.load(config.user_dir(uid) / "data" / "data.json") or {}
    if not d.get("reels"):
        return {}
    heard = spoken_hooks(uid)
    linked = link_board(uid, d)
    stats = formula_stats(uid, d)
    save(uid, "learning.json", {"at": int(time.time()), "formulas": stats, "linked": linked})
    return {"transcribed": heard, "linked": linked, "formulas": len(stats)}


def brief(uid):
    """One paragraph for the planner and the reel writer: which formulas worked for this page (3+ reels)."""
    s = content(uid, "learning.json", {}).get("formulas") or {}
    good = sorted(((v["median_multiple"], v["name"], v["n"], k) for k, v in s.items() if v["n"] >= 3), reverse=True)
    if not good:
        return ""
    lines = [f"فرمول {k} «{name}»: میانهٔ {m}× میانهٔ پیج از {n} ریل" for m, name, n, k in good[:6]]
    return "آنچه برای خود این پیج جواب داده (اولویت بده به بالایی‌ها، مگر شواهد تازه خلافش بگه):\n" + "\n".join(lines)
