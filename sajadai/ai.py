"""One way to ask the user's AI (Claude or GPT, their own key or the panel's) a question from the panel:
the dashboard chat, a reel's critique, hook/caption writing, comment analysis. Answers come back as text,
or as JSON held to a schema. Failures raise AIError with a message fit to show the user."""
import json, threading, time

from . import billing, pipeline, store

HOURLY_LIMIT = 40  # requests per user per hour, so a stuck page or a curious hand can't drain the key
_calls = {}
_lock = threading.Lock()


class AIError(Exception):
    pass


def _rate(user_id):
    now = time.time()
    with _lock:
        recent = [t for t in _calls.get(user_id, []) if now - t < 3600]
        if len(recent) >= HOURLY_LIMIT:
            raise AIError("سقف درخواست‌های این ساعت پر شده؛ کمی بعد دوباره امتحان کن.")
        recent.append(now)
        _calls[user_id] = recent


def ask(user, system, messages, schema=None, max_tokens=8000, effort="medium"):
    """messages: [{"role": "user"|"assistant", "content": str}]. Returns text, or a dict when schema is given."""
    cfg = pipeline.ai_config(user)
    if not cfg:
        if (store.setting("ai", {}) or {}).get("key") and not billing.may_use_panel_ai(user):
            raise AIError("هوش مصنوعی پنل برای اشتراک‌های حرفه‌ایه؛ از «تنظیمات ← اشتراک» ارتقا بده، یا کلید Claude یا GPT خودت رو بذار.")
        raise AIError("کلید هوش مصنوعی تنظیم نشده؛ از «تنظیمات ← هوش مصنوعی» (یا ادمین) یه کلید Claude یا GPT بذار.")
    _rate(user["id"])
    if cfg["provider"] == "openai":
        return _openai(cfg, system, messages, schema, max_tokens)
    return _claude(cfg, system, messages, schema, max_tokens, effort)


def _claude(cfg, system, messages, schema, max_tokens, effort):
    import anthropic
    client = anthropic.Anthropic(api_key=cfg["key"], max_retries=3)
    out_cfg = {"effort": effort}
    if schema:
        out_cfg["format"] = {"type": "json_schema", "schema": schema}
    try:
        msg = client.beta.messages.create(
            model=cfg["model"] or "claude-opus-5-5", max_tokens=max_tokens, system=system, messages=messages,
            output_config=out_cfg, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    except anthropic.AuthenticationError:
        raise AIError("کلید Anthropic قبول نشد؛ تو تنظیمات چکش کن.")
    except anthropic.RateLimitError:
        raise AIError("Anthropic فعلاً درخواست بیشتری قبول نمی‌کنه (سقف یا اعتبار)؛ کمی بعد دوباره امتحان کن.")
    except anthropic.APIStatusError as e:
        raise AIError(f"خطای Anthropic ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise AIError("به Anthropic وصل نشدیم؛ اینترنت سرور رو چک کن.")
    if msg.stop_reason == "refusal":
        raise AIError("مدل به این درخواست جواب نداد؛ سؤال رو جور دیگه‌ای بپرس.")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if msg.stop_reason == "max_tokens" and schema:
        raise AIError("جواب خیلی بلند شد و نصفه موند؛ دوباره امتحان کن.")
    return json.loads(text) if schema else text


def _openai(cfg, system, messages, schema, max_tokens):
    import openai
    client = openai.OpenAI(api_key=cfg["key"], max_retries=3)
    kw = {}
    if schema:
        kw["text"] = {"format": {"type": "json_schema", "name": "answer", "schema": schema, "strict": True}}
    try:
        r = client.responses.create(model=cfg["model"] or "gpt-5", instructions=system, input=messages,
                                    max_output_tokens=max_tokens, **kw)
    except openai.AuthenticationError:
        raise AIError("کلید OpenAI قبول نشد؛ تو تنظیمات چکش کن.")
    except openai.RateLimitError:
        raise AIError("OpenAI فعلاً درخواست بیشتری قبول نمی‌کنه (سقف یا اعتبار)؛ کمی بعد دوباره امتحان کن.")
    except openai.APIStatusError as e:
        raise AIError(f"خطای OpenAI ({e.status_code}): {e.message}")
    except openai.APIConnectionError:
        raise AIError("به OpenAI وصل نشدیم؛ اینترنت سرور رو چک کن.")
    text = (r.output_text or "").strip()
    if not text:
        raise AIError("مدل جوابی برنگردوند؛ دوباره امتحان کن.")
    return json.loads(text) if schema else text
