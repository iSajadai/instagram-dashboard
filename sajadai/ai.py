"""One way to ask the user's AI a question from the panel: the dashboard chat, a reel's critique, the studio
agents, comment analysis. Answers come back as text, or as JSON held to a schema. Failures raise AIError
with a message fit to show the user.

Each user keeps a chain of providers in order: Claude or GPT with their own API key, a free provider
(Gemini with a Google account, OpenRouter's free models, Groq, Cerebras, Mistral, GitHub Models, NVIDIA),
their own 9router (which signs in to the user's own subscriptions and serves them as one
OpenAI-compatible endpoint), a local Ollama, or any OpenAI-compatible URL. When one fails or hits its
limit, the next one answers. Without a chain the panel's shared key is used, where the plan allows it.

Claude subscriptions (Pro/Max) can't be signed in to directly: Anthropic's terms allow those tokens only
in Claude Code and claude.ai, so Claude here means an API key."""
import base64, ipaddress, json, re, socket, threading, time, urllib.parse

from . import billing, pipeline, store

HOURLY_LIMIT = 40  # requests per user per hour, so a stuck page or a curious hand can't drain the key
_calls = {}
_lock = threading.Lock()

# kind: anthropic / openai use their own SDK calls; compat is any OpenAI-compatible chat-completions API.
# prefer: patterns picked in order from the provider's model list when the user doesn't name a model.
PROVIDERS = {
    "anthropic": {"label": "Claude (کلید API)", "group": "paid", "kind": "anthropic", "key_url": "https://console.anthropic.com/settings/keys",
                  "key_hint": "sk-ant-…", "default": "claude-opus-5-5", "prefer": [r"^claude-opus-5-5$", r"^claude-sonnet-5-5$", r"opus", r"sonnet"],
                  "note": "بهترین فارسی و دقیق‌ترین جواب‌ها. پولی، با کلید API از کنسول Anthropic."},
    "openai": {"label": "GPT (کلید API)", "group": "paid", "kind": "openai", "key_url": "https://platform.openai.com/api-keys",
               "key_hint": "sk-…", "default": "gpt-5", "prefer": [r"^gpt-5(\.\d+)?$", r"^gpt-5", r"^gpt-4\.1$"],
               "note": "پولی، با کلید API از پلتفرم OpenAI."},
    "gemini": {"label": "Google Gemini (رایگان)", "group": "free", "kind": "compat", "base": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "key_url": "https://aistudio.google.com/apikey", "key_hint": "AIza…", "default": "gemini-2.5-flash",
               "prefer": [r"^gemini-\d+(\.\d+)?-flash$", r"^gemini-\d+(\.\d+)?-flash(?!.*(lite|image|tts|live|audio))", r"^gemini-\d+(\.\d+)?-pro$"],
               "note": "پیشنهاد ما برای شروع رایگان: با حساب گوگل خودت یه کلید رایگان بساز (یک دقیقه). فارسیش خوبه؛ سقف رایگانش روزانه است."},
    "openrouter": {"label": "OpenRouter (مدل‌های رایگان)", "group": "free", "kind": "compat", "base": "https://openrouter.ai/api/v1",
                   "key_url": "https://openrouter.ai/settings/keys", "key_hint": "sk-or-…",
                   "prefer": [r"deepseek.*:free$", r"qwen3.*:free$", r"gemini.*:free$", r"llama.*70b.*:free$", r":free$"],
                   "note": "ده‌ها مدل، از جمله مدل‌های «:free» بی‌هزینه. با یه حساب رایگان کلید بگیر."},
    "groq": {"label": "Groq (رایگان، خیلی سریع)", "group": "free", "kind": "compat", "base": "https://api.groq.com/openai/v1",
             "key_url": "https://console.groq.com/keys", "key_hint": "gsk_…", "prefer": [r"gpt-oss-120b", r"kimi-k2", r"llama-3\.3-70b", r"qwen"],
             "note": "سقف رایگان دقیقه‌ای داره؛ برای کارهای کوتاه و سریع خوبه."},
    "cerebras": {"label": "Cerebras (رایگان)", "group": "free", "kind": "compat", "base": "https://api.cerebras.ai/v1",
                 "key_url": "https://cloud.cerebras.ai/", "key_hint": "csk-…", "prefer": [r"gpt-oss-120b", r"qwen-3-235b", r"llama"],
                 "note": "رایگان با سقف روزانه، خیلی سریع."},
    "mistral": {"label": "Mistral (رایگان)", "group": "free", "kind": "compat", "base": "https://api.mistral.ai/v1",
                "key_url": "https://console.mistral.ai/api-keys", "prefer": [r"^mistral-large-latest$", r"^mistral-medium-latest$", r"^mistral-small-latest$"],
                "note": "پلن رایگان «Experiment» با تأیید شماره تلفن."},
    "github": {"label": "GitHub Models (رایگان)", "group": "free", "kind": "compat", "base": "https://models.github.ai/inference",
               "models_url": "https://models.github.ai/catalog/models", "key_url": "https://github.com/settings/personal-access-tokens/new",
               "key_hint": "github_pat_…", "prefer": [r"^openai/gpt-4\.1$", r"^openai/gpt-4o$", r"deepseek", r"llama"],
               "note": "با حساب گیت‌هاب: یه توکن شخصی با دسترسی models:read بساز. سقف روزانه داره."},
    "nvidia": {"label": "NVIDIA NIM (رایگان)", "group": "free", "kind": "compat", "base": "https://integrate.api.nvidia.com/v1",
               "key_url": "https://build.nvidia.com/settings/api-keys", "key_hint": "nvapi-…", "prefer": [r"deepseek-v3", r"qwen3", r"llama-3\.3-70b"],
               "note": "اعتبار رایگان برای توسعه‌دهنده‌ها."},
    "9router": {"label": "9router (حساب‌های شخصی خودت)", "group": "own", "kind": "compat", "needs_url": True, "key_optional": True,
                "url_hint": "https://my-9router.example.com/v1", "key_url": "https://github.com/decolua/9router",
                "note": "9router رو خودت راه بنداز (Docker یا Railway)، حساب ChatGPT و Gemini خودت و کلیدهای رایگان رو اونجا وصل کن و آدرس /v1 و کلیدش رو اینجا بذار. هر وقت یکی تموم شد، خودش سراغ بعدی می‌ره. حساب اشتراکی Claude رو اونجا وصل نکن: قوانین Anthropic اجازه نمی‌ده و حساب بسته می‌شه."},
    "ollama": {"label": "Ollama (مدل روی سرور خودت)", "group": "own", "kind": "compat", "needs_url": True, "key_optional": True,
               "url_hint": "http://my-server:11434/v1", "key_url": "https://ollama.com/download", "note": "مدل باز روی سرور خودت؛ بی‌هزینه ولی فارسی مدل‌های کوچیک ضعیفه."},
    "custom": {"label": "سرویس سازگار با OpenAI (سفارشی)", "group": "own", "kind": "compat", "needs_url": True, "key_optional": True,
               "url_hint": "https://…/v1", "note": "هر سرویسی که API سازگار با OpenAI داره (DeepSeek، Together، LM Studio، LiteLLM، One API…)."},
}
GROUPS = {"free": "رایگان", "paid": "پولی (کلید API)", "own": "حساب‌ها و سرورهای خودت"}
MAX_CHAIN = 6


class AIError(Exception):
    pass


def public_catalog():
    keep = ("label", "group", "key_url", "key_hint", "note", "needs_url", "key_optional", "url_hint", "default")
    return {"providers": {k: {f: v[f] for f in keep if f in v} for k, v in PROVIDERS.items()}, "groups": GROUPS}


def _rate(user_id):
    now = time.time()
    with _lock:
        recent = [t for t in _calls.get(user_id, []) if now - t < 3600]
        if len(recent) >= HOURLY_LIMIT:
            raise AIError("سقف درخواست‌های این ساعت پر شده؛ کمی بعد دوباره امتحان کن.")
        recent.append(now)
        _calls[user_id] = recent


def ask(user, system, messages, schema=None, max_tokens=8000, effort="medium", images=None):
    """messages: [{"role": "user"|"assistant", "content": str}]. Returns text, or a dict when schema is given.
    images: JPEG bytes sent with the last message (a reel's frames). Tries the user's providers in order
    and returns the first good answer."""
    cfg = pipeline.ai_config(user)
    if not cfg:
        if (store.setting("ai", {}) or {}).get("key") and not billing.may_use_panel_ai(user):
            raise AIError("هوش مصنوعی پنل برای اشتراک‌های حرفه‌ایه؛ از «تنظیمات ← هوش مصنوعی» یه سرویس رایگان (مثل Gemini) یا کلید خودت رو وصل کن، یا اشتراک رو ارتقا بده.")
        raise AIError("هنوز هوش مصنوعی وصل نشده؛ از «تنظیمات ← هوش مصنوعی» یه سرویس رایگان (مثل Gemini با حساب گوگل) یا کلید Claude/GPT خودت رو وصل کن.")
    _rate(user["id"])
    if not cfg.get("own"):
        from .accounts import check_quota
        check_quota(user)
    try:
        store.count_ai(store.person_id(user), bool(cfg.get("own")))
    except Exception:  # noqa: BLE001 — counting must never stop an answer
        pass
    errors = []
    for c in cfg["chain"]:
        try:
            return call(c, system, with_images(c, messages, images) if images else messages, schema, max_tokens, effort)
        except AIError as e:
            errors.append(f"{PROVIDERS.get(c['provider'], {}).get('label', c['provider'])}: {e}")
    if len(errors) == 1:
        raise AIError(errors[0].split(": ", 1)[1])
    raise AIError("هیچ‌کدوم از سرویس‌ها جواب ندادن. " + " | ".join(errors))


def with_images(c, messages, images):
    """The last user message with the pictures attached, in the form this provider takes."""
    kind = PROVIDERS.get(c["provider"], {}).get("kind", "compat")
    b64 = [base64.b64encode(i).decode() for i in images]
    *head, last = messages
    text = last["content"]
    if kind == "anthropic":
        parts = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": d}} for d in b64] + [{"type": "text", "text": text}]
    elif kind == "openai":
        parts = [{"type": "input_image", "image_url": "data:image/jpeg;base64," + d} for d in b64] + [{"type": "input_text", "text": text}]
    else:
        parts = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + d}} for d in b64] + [{"type": "text", "text": text}]
    return head + [{"role": last["role"], "content": parts}]


def call(c, system, messages, schema=None, max_tokens=8000, effort="medium"):
    kind = PROVIDERS.get(c["provider"], {}).get("kind", "compat")
    if kind == "anthropic":
        return _claude(c, system, messages, schema, max_tokens, effort)
    if kind == "openai":
        return _openai(c, system, messages, schema, max_tokens)
    return _compat(c, system, messages, schema, max_tokens)


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


# ---------- OpenAI-compatible providers ----------

def check_url(url, allow_private):
    """A provider URL the server may call: http(s) only, and addresses inside the server's network
    (localhost, a LAN, cloud metadata) only for the panel's admin, so a user can't make the panel
    probe its own network."""
    u = urllib.parse.urlparse(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise AIError("آدرس باید با https:// شروع بشه (مثلاً https://my-9router.example.com/v1)")
    try:
        addrs = {ipaddress.ip_address(a[4][0].split("%")[0]) for a in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))}
    except (socket.gaierror, ValueError):
        raise AIError(f"آدرس {u.hostname} پیدا نشد")
    inside = any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified for a in addrs)
    if inside and not allow_private:
        raise AIError("آدرس‌های داخلی (localhost یا شبکهٔ داخلی) فقط برای ادمین پنل مجازه؛ آدرس عمومی 9router یا سرورت رو بذار.")
    if u.scheme == "http" and not inside:
        raise AIError("برای آدرس عمومی از https استفاده کن تا کلید رمزنگاری‌شده بره.")
    return str(url).strip().rstrip("/")


def _client(c, timeout=180, retries=1):
    import openai
    spec = PROVIDERS.get(c["provider"], {})
    base = c.get("base_url") or spec.get("base")
    if spec.get("needs_url") or c.get("base_url"):
        base = check_url(base, c.get("private_ok"))
    headers = {"HTTP-Referer": pipeline.public_url() or "https://sajad.ai", "X-Title": "Sajad AI dashboard"} if c["provider"] == "openrouter" else None
    return openai.OpenAI(api_key=c.get("key") or "none", base_url=base, max_retries=retries, timeout=timeout, default_headers=headers)


def _compat_error(e, label):
    import openai
    if isinstance(e, openai.AuthenticationError) or getattr(e, "status_code", 0) in (401, 403):
        return AIError(f"کلید {label} قبول نشد؛ تو تنظیمات چکش کن.")
    if isinstance(e, openai.RateLimitError):
        return AIError(f"سقف رایگان {label} فعلاً پره؛ کمی بعد، یا سرویس بعدی.")
    if isinstance(e, openai.NotFoundError):
        return AIError(f"مدل یا آدرس {label} پیدا نشد؛ مدل رو تو تنظیمات عوض کن.")
    if isinstance(e, openai.APIStatusError):
        return AIError(f"خطای {label} ({e.status_code}): {str(e.message)[:200]}")
    if isinstance(e, openai.APITimeoutError):
        return AIError(f"{label} دیر جواب داد.")
    if isinstance(e, openai.APIConnectionError):
        return AIError(f"به {label} وصل نشدیم؛ آدرس و اینترنت سرور رو چک کن.")
    return AIError(f"{label}: {e}")


def _compat(c, system, messages, schema, max_tokens):
    import openai
    label = PROVIDERS.get(c["provider"], {}).get("label", c["provider"])
    client = _client(c)
    model = c.get("model") or PROVIDERS.get(c["provider"], {}).get("default")
    if not model:
        raise AIError(f"برای {label} مدلی انتخاب نشده؛ تو تنظیمات «آزمایش» رو بزن.")
    msgs = [{"role": "system", "content": system}] + list(messages)

    def send(msgs, fmt):
        kw = {"response_format": fmt} if fmt else {}
        r = client.chat.completions.create(model=model, messages=msgs, max_tokens=max_tokens, **kw)
        if not r.choices:
            raise AIError(f"{label} جوابی برنگردوند.")
        return (r.choices[0].message.content or "").strip(), r.choices[0].finish_reason

    try:
        if not schema:
            text, _ = send(msgs, None)
            if not text:
                raise AIError(f"{label} جوابی برنگردوند.")
            return text
        # structured output where the provider supports it; otherwise JSON mode, otherwise plain text,
        # with the schema spelled out in the instructions either way
        hint = ("\n\nAnswer with ONE JSON object only (no prose, no code fences) that matches this JSON Schema exactly; "
                "every property is required; keep all text values in Persian:\n" + json.dumps(schema, ensure_ascii=False))
        hinted = [{"role": "system", "content": system + hint}] + list(messages)
        text = None
        for m, fmt in ((msgs, {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": True}}),
                       (hinted, {"type": "json_object"}), (hinted, None)):
            try:
                text, finish = send(m, fmt)
                break
            except openai.BadRequestError as e:
                if re.search(r"max_tokens|max_completion", str(e), re.I) and max_tokens > 8192:
                    max_tokens = 8192  # free tiers cap the answer length
                    text, finish = send(m, fmt)
                    break
                continue
        if text is None:
            raise AIError(f"{label} این درخواست رو قبول نکرد.")
        if finish == "length":
            raise AIError(f"جواب {label} نصفه موند (سقف طول).")
        data = parse_json(text)
        problems = check_schema(schema, data) if data is not None else ["JSON not valid"]
        if problems:  # one repair round with the same model
            fix = hinted + [{"role": "assistant", "content": text[:20000]},
                            {"role": "user", "content": "That answer doesn't match the schema: " + "; ".join(problems[:8]) +
                             ". Return the corrected complete JSON object only."}]
            text, _ = send(fix, {"type": "json_object"} if fmt else None)
            data = parse_json(text)
            problems = check_schema(schema, data) if data is not None else ["JSON not valid"]
            if problems:
                raise AIError(f"جواب {label} ساختار درستی نداشت.")
        return data
    except openai.OpenAIError as e:
        raise _compat_error(e, label)


def parse_json(text):
    """A JSON object from a model's text: plain, inside ``` fences, or after a short preamble."""
    t = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S).strip()  # reasoning models that print their thinking
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    for cand in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t else ""):
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except ValueError:
            pass
    return None


def check_schema(schema, data, path="$"):
    """Problems with data against the strict schemas the agents use (types, required, enums); numbers
    sent as strings are fixed in place. An empty list means it fits."""
    out = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(data, dict):
            return [f"{path} should be an object"]
        for k in schema.get("required", []):
            if k not in data:
                out.append(f"{path}.{k} missing")
        for k, sub in schema.get("properties", {}).items():
            if k in data:
                if sub.get("type") in ("integer", "number") and isinstance(data[k], str) and re.fullmatch(r"-?\d+(\.\d+)?", data[k].strip()):
                    data[k] = float(data[k]) if sub["type"] == "number" else int(float(data[k]))
                out += check_schema(sub, data[k], f"{path}.{k}")
    elif t == "array":
        if not isinstance(data, list):
            return [f"{path} should be an array"]
        for i, x in enumerate(data):
            sub = schema.get("items", {})
            if sub.get("type") in ("integer", "number") and isinstance(x, str) and re.fullmatch(r"-?\d+(\.\d+)?", x.strip()):
                data[i] = x = float(x) if sub["type"] == "number" else int(float(x))
            out += check_schema(sub, x, f"{path}[{i}]")
    elif t == "string":
        if not isinstance(data, str):
            out.append(f"{path} should be a string")
        elif "enum" in schema and data not in schema["enum"]:
            out.append(f"{path} must be one of {schema['enum']}")
    elif t == "integer":
        if isinstance(data, float) and data.is_integer():
            return []
        if not isinstance(data, int) or isinstance(data, bool):
            out.append(f"{path} should be an integer")
    elif t == "number":
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            out.append(f"{path} should be a number")
    elif t == "boolean" and not isinstance(data, bool):
        out.append(f"{path} should be true/false")
    return out[:20]


# ---------- connecting a provider: find its models, pick one, check it answers ----------

def list_models(c):
    spec = PROVIDERS[c["provider"]]
    if spec["kind"] == "anthropic":
        import anthropic
        return [m.id for m in anthropic.Anthropic(api_key=c["key"], max_retries=1, timeout=30).models.list(limit=100)]
    if spec["kind"] == "openai":
        import openai
        return [m.id for m in openai.OpenAI(api_key=c["key"], max_retries=1, timeout=30).models.list()]
    if spec.get("models_url"):  # GitHub Models lists its catalog elsewhere
        import urllib.request
        req = urllib.request.Request(spec["models_url"], headers={"Authorization": "Bearer " + (c.get("key") or ""), "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode())
        return [m["id"] for m in (d if isinstance(d, list) else d.get("data", [])) if m.get("id")]
    ids = [m.id for m in _client(c, timeout=30).models.list()]
    return [i[len("models/"):] if i.startswith("models/") else i for i in ids]


def pick_model(provider, models):
    def version(m):  # newest first among equal matches: gemini-3-flash before gemini-2.5-flash
        return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m)[:2]] or [0.0]
    for pat in PROVIDERS[provider].get("prefer", []):
        hits = [m for m in models if re.search(pat, m) and not re.search(r"preview|exp|embed|vision|guard|tts|whisper|image|audio|moderation", m, re.I)]
        if hits:
            return sorted(hits, key=version, reverse=True)[0]
    return PROVIDERS[provider].get("default") or (models[0] if models else "")


def connect(c):
    """Test a provider entry: list its models, choose one when none is given, and check a short answer
    in Persian comes back. Returns (entry, models, message); raises AIError."""
    import anthropic, openai
    label = PROVIDERS[c["provider"]]["label"]
    models = []
    try:
        models = list_models(c)
    except AIError:
        raise
    except (anthropic.AuthenticationError, openai.AuthenticationError):
        raise AIError(f"کلید {label} قبول نشد.")
    except Exception:  # noqa: BLE001 — some providers don't list models; the test answer below still decides
        models = []
    if not c.get("model"):
        c["model"] = pick_model(c["provider"], models)
    if not c["model"]:
        raise AIError(f"مدلی از {label} پیدا نشد؛ اسم مدل رو دستی بنویس.")
    try:
        reply = call(c, "Reply in Persian with one short word.", [{"role": "user", "content": "سلام! فقط بنویس: آماده"}], None, 400, "low")
    except AIError as e:
        raise AIError(f"{e} (مدل: {c['model']})")
    return c, models[:200], f"وصل شد: {label} · {c['model']} · جواب آزمایشی: «{str(reply)[:40]}»"
