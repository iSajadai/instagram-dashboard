"""The provider chain against a fake OpenAI-compatible server: model discovery and choice, structured
output with fallbacks (a server without json_schema, an answer in code fences, a repair round), the
next provider answering when one fails, and private addresses kept to the admin."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sajadai import ai  # noqa: E402

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["hook", "score", "kind"],
          "properties": {"hook": {"type": "string"}, "score": {"type": "integer"}, "kind": {"type": "string", "enum": ["reel", "story"]}}}
seen = []


class Fake(BaseHTTPRequestHandler):
    """/a/: no json_schema support, answers in fences. /b/: first answer misses a field (repaired).
    /dead/: always 429. /free/: lists models."""
    def log_message(self, *a):
        pass

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.endswith("/models"):
            ids = ["models/gemini-2.0-flash", "models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-2.5-pro", "models/text-embedding-004"]
            return self.reply(200, {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})
        self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        seen.append((self.path, body.get("response_format", {}).get("type") if body.get("response_format") else None, body["model"]))
        def answer(text):
            return self.reply(200, {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}]})
        if self.path.startswith("/dead/"):
            return self.reply(429, {"error": {"message": "quota", "type": "rate_limit"}})
        if self.headers.get("Authorization") != "Bearer good":
            return self.reply(401, {"error": {"message": "bad key"}})
        if not body.get("response_format") and "JSON Schema" not in body["messages"][0]["content"]:
            return answer("آماده")
        if self.path.startswith("/a/"):
            if (body.get("response_format") or {}).get("type") == "json_schema":
                return self.reply(400, {"error": {"message": "response_format json_schema not supported"}})
            return answer('بفرما:\n```json\n{"hook": "۱۸ میلیون پای یه جمله دادم", "score": "72", "kind": "reel"}\n```')
        if self.path.startswith("/b/"):
            if len(body["messages"]) > 2:
                return answer('{"hook": "درست شد", "score": 60, "kind": "story"}')
            return answer('{"hook": "نصفه", "kind": "video"}')
        answer("{}")


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def entry(path, key="good", model="m1", provider="custom"):
    return {"id": "t", "provider": provider, "key": key, "model": model, "base_url": BASE + path, "private_ok": True}


def test_json_mode_fallback_and_fences():
    seen.clear()
    d = ai.call(entry("/a/v1"), "sys", [{"role": "user", "content": "hi"}], SCHEMA, 2000)
    assert d == {"hook": "۱۸ میلیون پای یه جمله دادم", "score": 72, "kind": "reel"}, d
    assert [s[1] for s in seen] == ["json_schema", "json_object"], seen


def test_repair_round():
    d = ai.call(entry("/b/v1"), "sys", [{"role": "user", "content": "hi"}], SCHEMA, 2000)
    assert d == {"hook": "درست شد", "score": 60, "kind": "story"}, d


def test_bad_key_message():
    try:
        ai.call(entry("/a/v1", key="nope"), "sys", [{"role": "user", "content": "hi"}])
        assert False
    except ai.AIError as e:
        assert "کلید" in str(e), e


def test_chain_falls_through(monkeypatch=None):
    from sajadai import pipeline
    orig = pipeline.ai_config
    pipeline.ai_config = lambda u: {"chain": [entry("/dead/v1"), entry("/b/v1")]}
    try:
        d = ai.ask({"id": 999}, "sys", [{"role": "user", "content": "hi"}], SCHEMA, 2000)
        assert d["kind"] == "story"
        pipeline.ai_config = lambda u: {"chain": [entry("/dead/v1")]}
        try:
            ai.ask({"id": 999}, "sys", [{"role": "user", "content": "hi"}])
            assert False
        except ai.AIError as e:
            assert "سقف" in str(e), e
    finally:
        pipeline.ai_config = orig


def test_connect_discovers_and_picks():
    c, models, msg = ai.connect({"id": "t", "provider": "gemini", "key": "good", "model": "", "base_url": BASE + "/a/v1", "private_ok": True})
    assert c["model"] == "gemini-2.5-flash", c["model"]
    assert "gemini-2.5-pro" in models and "وصل شد" in msg, msg


def test_private_urls_need_admin():
    try:
        ai.check_url(BASE + "/v1", False)
        assert False
    except ai.AIError as e:
        assert "ادمین" in str(e)
    for bad in ("ftp://x.example/v1", "http://169.254.169.254/latest", "file:///etc/passwd"):
        try:
            ai.check_url(bad, False)
            assert False, bad
        except ai.AIError:
            pass
    assert ai.check_url(BASE + "/v1/", True) == BASE + "/v1"


def test_pick_model():
    assert ai.pick_model("openrouter", ["openai/gpt-4o", "meta-llama/llama-3.3-70b-instruct:free", "deepseek/deepseek-chat-v3:free"]) == "deepseek/deepseek-chat-v3:free"
    assert ai.pick_model("groq", ["llama-3.1-8b-instant", "openai/gpt-oss-120b", "whisper-large-v3"]) == "openai/gpt-oss-120b"
    assert ai.pick_model("gemini", ["gemini-2.5-flash", "gemini-3-flash", "gemini-3-flash-lite"]) == "gemini-3-flash"


def test_schema_check():
    assert ai.check_schema(SCHEMA, {"hook": "x", "score": 3, "kind": "reel"}) == []
    assert ai.check_schema(SCHEMA, {"hook": 1, "kind": "x"})
    assert ai.parse_json("<think>hmm</think>\n{\"a\": 1}") == {"a": 1}


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
