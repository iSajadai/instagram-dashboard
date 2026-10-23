"""The pre-publish critique: frames with ffmpeg, the spoken hook, pacing from timed segments, SRT, and
the images reaching each provider's format. Transcription and the model are replaced."""
import os, shutil, subprocess, sys, tempfile

os.environ["SAJADAI_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sajadai import ai, critique, ig  # noqa: E402

SEGS = [{"start": 0.4, "end": 2.6, "text": "۱۸ میلیون تومن پای یه جمله دادم."},
        {"start": 2.7, "end": 6.0, "text": "قرارداد رو بدون خوندن بند آخرش امضا کردم و همه چی رو باختم چون عجله داشتم و فکر می‌کردم مهم نیست"},
        {"start": 8.1, "end": 9.5, "text": "تو این اشتباه رو نکن."}]


def make_video(secs=10):
    name = ig.new_media_name(".mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=540x960:rate=30:duration={secs}",
                    "-f", "lavfi", "-i", f"sine=duration={secs}:sample_rate=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(ig.MEDIA_DIR / name)], check=True)
    return name


def test_srt_and_pacing():
    s = critique.srt(SEGS)
    assert s.startswith("1\n00:00:00,400 --> ") and "00:00:09,500" in s
    assert all(len(line) <= critique.SRT_CHARS for line in s.splitlines() if line and "-->" not in line and not line.isdigit())
    p = critique.pacing(SEGS, 10)
    assert p["first_word"] == 0.4 and p["gaps"] == [{"at": 6.0, "secs": 2.1}] and p["tail"] == 0.5
    assert critique.hook_text(SEGS).startswith("۱۸ میلیون") and "قرارداد" in critique.hook_text(SEGS)


def test_estimate_from_paste():
    segs = critique.estimate("هیچ‌کس بهت نمی‌گه.\nریل اولت شکست می‌خوره!", 150)
    assert len(segs) == 2 and segs[0]["start"] == 0 and segs[1]["start"] == segs[0]["end"]


def test_clean_half_spaces():
    assert "‌" in critique.clean("من می خوام")


def test_full_critique_with_frames():
    if not shutil.which("ffmpeg"):
        print("  (no ffmpeg; skipped)")
        return
    name = make_video()
    seen = {}
    critique.transcribe = lambda user, path, tmp: SEGS
    def fake_ask(user, system, messages, schema=None, max_tokens=0, effort="", images=None):
        seen["images"] = images
        return {"verdict": "اول هوک رو تیز کن", "first_frame": "ثابته", "hook": "عدد داره", "pacing": "ثانیهٔ ۶ سکوت",
                "visuals": "متن روی تصویر نیست", "fixes": ["سکوت ثانیهٔ ۶ رو ببر"], "better_hooks": ["۱۸ میلیون پای یه امضا دادم.", "سلام دوستان"]}
    critique.ai.ask = fake_ask
    import sajadai.agents as agents
    agents.wpm = lambda user: 150
    r = critique.critique({"id": 1}, name, "")
    assert 6 <= len(seen["images"]) <= 8 and all(b[:2] == b"\xff\xd8" for b in seen["images"])
    assert r["hook_score"]["overall"] > 0 and r["better_hooks"][0]["overall"] >= r["better_hooks"][-1]["overall"]
    assert r["srt"].count("-->") >= 3 and r["duration"] == 10.0


def test_images_per_provider():
    msgs = [{"role": "user", "content": "نقد کن"}]
    a = ai.with_images({"provider": "anthropic"}, msgs, [b"\xff\xd8x"])[0]["content"]
    o = ai.with_images({"provider": "openai"}, msgs, [b"\xff\xd8x"])[0]["content"]
    g = ai.with_images({"provider": "gemini"}, msgs, [b"\xff\xd8x"])[0]["content"]
    assert a[0]["type"] == "image" and a[-1]["text"] == "نقد کن"
    assert o[0]["type"] == "input_image" and o[0]["image_url"].startswith("data:image/jpeg;base64,")
    assert g[0]["type"] == "image_url" and g[-1] == {"type": "text", "text": "نقد کن"}


if __name__ == "__main__":
    bad = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                bad += 1
                print("FAIL", k, repr(e)[:400])
    sys.exit(1 if bad else 0)
