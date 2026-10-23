"""A reel's critique before it goes out: what is actually said in the first three seconds (scored with
the Persian hook checks), how fast and where it drags (from the transcript's real timings), SRT
subtitles, and an AI read of the frames and the words together.

The transcript comes from the user's own OpenAI key (whisper-1, with segment times) or a free Groq key
(whisper-large-v3), whichever is in their AI chain; without either, a pasted script is used and the
timing is estimated at the page's speaking pace. Frames and audio are cut with ffmpeg.

Runs as a background job (critique can take a minute; a request through Cloudflare can't)."""
import json, re, shutil, subprocess, tempfile, threading, time, uuid
from pathlib import Path

from . import ai, ig, pipeline
from .fa import hooks
from .fa.human import HALF_SPACE
from .fa.text import fa_digits, normalize, words

JOBS = {}
_lock = threading.Lock()
HOOK_SECS = 3.0
SRT_CHARS = 42  # a subtitle line that still reads at a glance on a phone

CRITIQUE_SCHEMA = {"type": "object", "additionalProperties": False,
                   "required": ["verdict", "first_frame", "hook", "pacing", "visuals", "fixes", "better_hooks"],
                   "properties": {
                       "verdict": {"type": "string"}, "first_frame": {"type": "string"}, "hook": {"type": "string"},
                       "pacing": {"type": "string"}, "visuals": {"type": "string"},
                       "fixes": {"type": "array", "items": {"type": "string"}},
                       "better_hooks": {"type": "array", "items": {"type": "string"}}}}
SYSTEM = """You are a sharp Persian-speaking Instagram Reels editor reviewing a reel BEFORE it is published.
You get: frames (the first ones are from 0s, 1s and 2s, the rest spread over the video), the transcript with
timings, the Persian hook checks' scores, and the measured pace. Judge what a viewer scrolling past sees and
hears in the first 1-3 seconds, then whether the middle drags. Be concrete: name the second, the frame, the
words. verdict: one line, publish as is / fix first. first_frame: is the opening frame a reason to stop
(motion, a face, a bold text)? hook: the spoken hook against the checks. pacing: drags and dead air with times.
visuals: text on screen, framing, light, captions. fixes: up to 5 edits in order of payoff. better_hooks:
3 alternative opening lines in the creator's spoken Persian. All text in conversational Persian."""


def start(user, video, transcript=""):
    jid = uuid.uuid4().hex[:12]
    with _lock:
        for k in [k for k, j in JOBS.items() if time.time() - j["at"] > 3600]:
            JOBS.pop(k, None)
        JOBS[jid] = {"user": user["id"], "at": time.time(), "status": "running", "step": "آماده‌سازی…", "result": None, "error": None}
    threading.Thread(target=_run, args=(jid, user, video, transcript), daemon=True).start()
    return jid


def status(user, jid):
    j = JOBS.get(jid)
    if not j or j["user"] != user["id"]:
        return None
    return {k: j[k] for k in ("status", "step", "result", "error")}


def _step(jid, text):
    JOBS[jid]["step"] = text


def _run(jid, user, video, transcript):
    try:
        JOBS[jid]["result"] = critique(user, video, transcript, lambda t: _step(jid, t))
        JOBS[jid]["status"] = "done"
    except Exception as e:  # noqa: BLE001 — shown to the user as is
        JOBS[jid].update(status="failed", error=str(e) if isinstance(e, (ai.AIError, ValueError, RuntimeError)) else f"خطا: {e}")


def ffmpeg(*args, timeout=180):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg روی سرور نصب نیست.")
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("ffmpeg نتونست ویدیو رو بخونه: " + r.stderr.decode(errors="ignore")[-200:])


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, timeout=60)
    try:
        return float(r.stdout.decode().strip())
    except ValueError:
        raise RuntimeError("طول ویدیو خونده نشد؛ فایل خرابه؟")


def frames(path, dur, tmp):
    """JPEGs (480 wide) at 0, 1, 2 seconds and five more spread over the rest."""
    times = [t for t in (0.05, 1.0, 2.0) if t < dur] + [round(dur * f, 2) for f in (0.25, 0.4, 0.55, 0.7, 0.88) if dur * f > 2.5]
    out = []
    for i, t in enumerate(times):
        f = tmp / f"f{i}.jpg"
        ffmpeg("-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "5", str(f), timeout=60)
        if f.exists():
            out.append((t, f.read_bytes()))
    return out


def transcriber(user):
    """(client, model) for the first provider in the user's chain that can transcribe, else None."""
    cfg = pipeline.ai_config(user)
    import openai
    for c in (cfg or {}).get("chain", []):
        if c["provider"] == "openai":
            return openai.OpenAI(api_key=c["key"], max_retries=2, timeout=300), "whisper-1"
        if c["provider"] == "groq":
            return openai.OpenAI(api_key=c["key"], base_url=ai.PROVIDERS["groq"]["base"], max_retries=2, timeout=300), "whisper-large-v3"
    return None


def transcribe(user, path, tmp):
    t = transcriber(user)
    if not t:
        return None
    client, model = t
    audio = tmp / "a.mp3"
    ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio))
    if audio.stat().st_size > 24 * 1024 * 1024:
        raise RuntimeError("صدای این ویدیو برای تبدیل به متن خیلی طولانیه؛ متنش رو دستی بذار.")
    import openai
    try:
        with open(audio, "rb") as f:
            r = client.audio.transcriptions.create(model=model, file=f, language="fa", response_format="verbose_json",
                                                   timestamp_granularities=["segment"], prompt="ریل اینستاگرام به فارسی محاوره‌ای.")
    except openai.OpenAIError as e:
        raise RuntimeError(f"تبدیل صدا به متن نشد: {str(e)[:200]}")
    segs = getattr(r, "segments", None) or (r.get("segments") if isinstance(r, dict) else None) or []
    out = []
    for s in segs:
        g = s if isinstance(s, dict) else s.model_dump() if hasattr(s, "model_dump") else vars(s)
        text = clean(g.get("text", ""))
        if text:
            out.append({"start": round(float(g["start"]), 2), "end": round(float(g["end"]), 2), "text": text})
    return out


def clean(text):
    t = normalize(str(text)).strip()
    for pattern, repl in HALF_SPACE:
        t = pattern.sub(repl, t)
    return re.sub(r"\s+", " ", t)


def estimate(script, wpm):
    """Segments with estimated times from a pasted script (one per sentence, at the speaking pace)."""
    wps, t, out = wpm / 60.0, 0.0, []
    for s in re.split(r"(?<=[.!?؟…])\s+|\n+", clean(script)):
        if not s.strip():
            continue
        secs = max(len(words(s)) / wps, 0.6)
        out.append({"start": round(t, 2), "end": round(t + secs, 2), "text": s.strip()})
        t += secs
    return out


def pacing(segs, dur):
    if not segs:
        return {"wpm": 0, "first_word": None, "gaps": [], "tail": None}
    n = sum(len(words(s["text"])) for s in segs)
    talk = sum(s["end"] - s["start"] for s in segs) or 1
    gaps = [{"at": round(a["end"], 1), "secs": round(b["start"] - a["end"], 1)} for a, b in zip(segs, segs[1:]) if b["start"] - a["end"] >= 1.2]
    return {"wpm": round(n / talk * 60), "first_word": segs[0]["start"], "gaps": gaps[:6],
            "tail": round(dur - segs[-1]["end"], 1) if dur else None}


def hook_text(segs):
    """What is said in the first three seconds (whole segments that start before 3s)."""
    return " ".join(s["text"] for s in segs if s["start"] < HOOK_SECS).strip()


def srt(segs):
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    out, n = [], 0
    for s in segs:
        # long segments split into pieces of up to two lines, with the time shared by length
        ws, pieces, cur = s["text"].split(), [], ""
        for w in ws:
            if len(cur) + len(w) + 1 > SRT_CHARS * 2 and cur:
                pieces.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            pieces.append(cur)
        total, t = sum(len(p) for p in pieces) or 1, s["start"]
        for p in pieces:
            end = t + (s["end"] - s["start"]) * len(p) / total
            lines, line = [], ""
            for w in p.split():
                if len(line) + len(w) + 1 > SRT_CHARS and line:
                    lines.append(line)
                    line = w
                else:
                    line = (line + " " + w).strip()
            lines.append(line)
            n += 1
            out.append(f"{n}\n{ts(t)} --> {ts(end)}\n" + "\n".join(lines) + "\n")
            t = end
    return "\n".join(out)


def critique(user, video, transcript="", step=lambda t: None):
    path = ig.media_path(video)
    if not path:
        raise ValueError("ویدیو پیدا نشد؛ دوباره آپلود کن.")
    from .agents import wpm as voice_wpm
    wpm = voice_wpm(user)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        dur = duration(path)
        step("برداشتن فریم‌ها…")
        shots = frames(path, dur, tmp)
        segs, source = None, "paste"
        if transcript.strip():
            segs = estimate(transcript, wpm)
        else:
            step("تبدیل صدا به متن…")
            segs = transcribe(user, path, tmp)
            source = "audio"
            if segs is None:
                raise ValueError("برای تبدیل خودکار صدا به متن، کلید OpenAI یا Groq (رایگان) رو تو «تنظیمات ← هوش مصنوعی» وصل کن، یا متن ریل رو دستی بذار.")
    if not segs:
        raise ValueError("تو این ویدیو حرفی شنیده نشد؛ اگه ریل بی‌کلامه، متن روی تصویر رو دستی بذار.")
    hook = hook_text(segs) or segs[0]["text"]
    score = hooks.score(hook, wpm)
    pace = pacing(segs, dur)
    step("نقد با هوش مصنوعی…")
    facts = {"duration_s": round(dur, 1), "transcript_source": "measured from the audio" if source == "audio" else "pasted script, timing estimated",
             "segments": segs[:80], "hook_first_3s": hook,
             "hook_checks": {"overall": score["overall"], "verdict": score["verdict"], "weakest": score.get("weakest_fa"), "flags": score.get("flags")},
             "pace": pace, "frame_times_s": [t for t, _ in shots]}
    out = ai.ask(user, SYSTEM, [{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}], schema=CRITIQUE_SCHEMA,
                 max_tokens=4000, images=[b for _, b in shots])
    better = [{"text": h, **{k: v for k, v in hooks.score(h, wpm).items() if k in ("overall", "verdict_fa")}} for h in out.get("better_hooks", [])[:3]]
    return {**out, "better_hooks": sorted(better, key=lambda h: -h["overall"]), "hook_text": hook, "hook_score": score,
            "pace": pace, "segments": segs, "source": source, "duration": round(dur, 1), "srt": srt(segs),
            "summary_fa": f"{fa_digits(round(dur))} ثانیه · {fa_digits(pace['wpm'])} کلمه در دقیقه"}
