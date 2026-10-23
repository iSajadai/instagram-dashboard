#!/usr/bin/env python3
"""Write the weekly AI content for the dashboard: content ideas, this week's analysis and (when
something clearly better turns up) the benchmark pages. Works with Claude (Anthropic API, the
default) or GPT (OpenAI API). Replaces the claude.ai "weekly analytics" routine; run Saturday
mornings by cron (deploy/standalone.md) or by the panel's scheduler for each user.

Numbers are computed here from data.json; the model only gets them as facts, does the outside
research with web search, and returns the result held to a JSON schema (Claude through a strict
save_content tool, GPT through structured outputs). Each file is replaced only when the answer for
it is a valid, non-empty array; benchmarks only when the model sends new ones.

Settings (all optional): SAJADAI_AI_PROVIDER (anthropic | openai), SAJADAI_AI_KEY, SAJADAI_AI_MODEL,
SAJADAI_PAGE_PROFILE. Without SAJADAI_AI_KEY the Anthropic SDK reads ANTHROPIC_API_KEY, which can also
sit in /etc/sajadai-dashboard/anthropic.env. Needs: pip install anthropic (or openai).
Usage: python3 scripts/write_content.py [--dry-run]     (--dry-run prints instead of writing)
"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import notify  # Telegram config and sending, Jalali dates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.environ.get("SAJADAI_STATE", "")
DATA = os.path.join(STATE, "data", "data.json") if STATE else os.path.join(ROOT, "data", "data.json")
OUT_DIR = os.path.join(STATE, "content") if STATE else os.path.join(ROOT, "content")
KEY_ENV = "/etc/sajadai-dashboard/anthropic.env"
# the panel passes each user's choice: SAJADAI_AI_PROVIDER (anthropic | openai | compat, with SAJADAI_AI_BASE_URL
# for any OpenAI-compatible service: Gemini, OpenRouter, Groq, the user's 9router…), SAJADAI_AI_KEY, SAJADAI_AI_MODEL,
# SAJADAI_PAGE_PROFILE (who the page is for and its style, written by the user)
PROVIDER = os.environ.get("SAJADAI_AI_PROVIDER", "anthropic")
MODEL = os.environ.get("SAJADAI_AI_MODEL") or {"anthropic": "claude-opus-5-5", "openai": "gpt-5"}.get(PROVIDER, "claude-opus-5-5")
TEH = timezone(timedelta(hours=3, minutes=30))

PROFILE = os.environ.get("SAJADAI_PAGE_PROFILE") or """"Sajadai" (handle isajadai), a Persian-language Instagram page that teaches AI from zero: a numbered series on ChatGPT/LLM basics, storytelling style, Sajad on camera with his own voice. Long-term goal: grow an audience, then introduce his AI-agent building/hiring platform — his own agents may be shown, but never name the platform."""

SYSTEM = """You write the weekly content plan for this Instagram page:

{profile}

You get this week's numbers as facts. Never invent statistics, and never state a figure that isn't in the facts. Everything the reader sees is in Persian, conversational (محاوره‌ای) for hooks, plain and clear elsewhere.

Before writing, research with web search what is working right now in English-language short-form video in this page's niche (Instagram Reels, TikTok, YouTube Shorts): formats, hook patterns, and news in the niche from the last two weeks. Prefer sources from the last two weeks and keep their URLs. Instagram pages themselves can't be fetched; only name a handle you saw named in a source."""

TASK = """Facts for this week (JSON):

{facts}

Current benchmark pages (JSON):

{benchmarks}

Return:
- ideas: exactly 6 reel ideas. id = short unique latin slug; priority 1-6 (1 = film first; the dashboard puts 1-4 into this week's best posting slots); title; format; length (e.g. "30–45 ثانیه"); hook = the first spoken line; beats = the structure in one line using ←; why = why it should work, tied to this week's numbers and the outside pattern; inspiration = the foreign format or trend it adapts; source_url = an https URL from your research. Adapt foreign formats to the series and the storytelling style. If the page runs a numbered series, at least one idea continues it (the captions show what's already filmed), and follow any rule in the page description. Don't repeat a topic already filmed.
- insights: 3 to 5 findings. id = latin slug; area (e.g. هوک / ذخیره / دسترسی / تعداد انتشار / رقبا); severity exactly "مهم" or "خوب"; finding = from this week's numbers, qualitative (no figures that could contradict the live tiles); action = one concrete thing to do this week.
- benchmarks: only if you found a clearly better or more current page to follow than the current list, the full new list of 8-12 pages (handle without @, name, region "خارجی" or "فارسی", focus, learn = what Sajad should take from them, url "https://www.instagram.com/<handle>/", source_url = where you saw them named). Otherwise an empty list. Never invent handles.
- summary: 2-3 sentences for the page owner's Telegram: the main lesson of the week and which idea to film first."""

STR = {"type": "string"}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ideas", "insights", "benchmarks", "summary"],
    "properties": {
        "ideas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "priority", "title", "format", "length", "hook", "beats", "why", "inspiration", "source_url"],
            "properties": {"id": STR, "priority": {"type": "integer"}, "title": STR, "format": STR, "length": STR, "hook": STR,
                           "beats": STR, "why": STR, "inspiration": STR, "source_url": STR}}},
        "insights": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "area", "severity", "finding", "action"],
            "properties": {"id": STR, "area": STR, "severity": {"type": "string", "enum": ["مهم", "خوب"]}, "finding": STR, "action": STR}}},
        "benchmarks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["handle", "name", "region", "focus", "learn", "url", "source_url"],
            "properties": {"handle": STR, "name": STR, "region": {"type": "string", "enum": ["خارجی", "فارسی"]}, "focus": STR,
                           "learn": STR, "url": STR, "source_url": STR}}},
        "summary": STR,
    },
}


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def facts(d, today):
    """This week's numbers, computed here so the model never has to do arithmetic on them."""
    reels = [r for r in d.get("reels", []) if r.get("views") is not None]
    med = median(r["views"] for r in reels) if reels else None
    week = (today - timedelta(days=7)).isoformat()

    def row(r):
        reach = r.get("reach") or 0
        return {"published": r.get("published"), "url": r.get("url"), "caption": (r.get("caption") or "")[:300],
                "topic": r.get("topic"), "views": r["views"], "multiple_of_median": round(r["views"] / med, 2) if med else None,
                "view_rate_3s_pct": r.get("view_rate"), "avg_watch_s": r.get("avg_watch"),
                "saves_per_1k_reach": round((r.get("saves") or 0) / reach * 1000, 1) if reach else None,
                "shares_per_1k_reach": round((r.get("shares") or 0) / reach * 1000, 1) if reach else None,
                "follows": r.get("follows")}

    ranked = sorted(reels, key=lambda r: r["views"], reverse=True)
    fols = [a for a in d.get("account", []) if a.get("followers") is not None]
    start = [a for a in fols if a["day"] < week]
    return {
        "today_tehran": today.isoformat(),
        "page_median_views": med,
        "reels_on_record": len(reels),
        "followers_now": fols[-1]["followers"] if fols else None,
        "followers_net_7d": fols[-1]["followers"] - start[-1]["followers"] if fols and start else None,
        "reels_last_7_days": [row(r) for r in reels if str(r.get("published") or "")[:10] >= week],
        "all_reels_ranked_by_views": [row(r) for r in ranked],
        "goals": d.get("goals", []),
    }


TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 12},
    # the answer comes back as this tool's input: strict mode checks it against the schema, and unlike
    # output_config.format it doesn't clash with the citations web search adds to text
    {"name": "save_content", "strict": True, "input_schema": SCHEMA,
     "description": "Save this week's ideas, insights, benchmarks and summary to the dashboard. Call it once, after your research, with the complete result."},
]


def ask_claude(client, prompt):
    messages = [{"role": "user", "content": prompt}]
    nudged = False
    for _ in range(6):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM.format(profile=PROFILE),
            messages=messages,
            tools=TOOLS,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            cat = msg.stop_details.category if msg.stop_details else None
            raise RuntimeError(f"Claude declined the request (category: {cat}, request {msg._request_id})")
        if msg.stop_reason == "max_tokens":
            raise RuntimeError(f"answer was cut off at max_tokens (request {msg._request_id})")
        for b in msg.content:
            if b.type == "tool_use" and b.name == "save_content":
                return json.loads(json.dumps(b.input))  # plain dicts, whatever the SDK hands back
        messages.append({"role": "assistant", "content": msg.content})
        if msg.stop_reason == "pause_turn":
            continue  # server-side web search paused a long turn; resume it as is
        if nudged:
            break
        nudged = True  # forced tool_choice isn't allowed on this model, so ask once in words
        messages.append({"role": "user", "content": "Now call save_content with the complete result."})
    raise RuntimeError("Claude didn't return the content (no save_content call)")


def ask_openai(client, prompt):
    # Responses API: web search as a hosted tool, the answer as JSON held to the same schema
    r = client.responses.create(
        model=MODEL,
        instructions=SYSTEM.format(profile=PROFILE),
        input=prompt,
        tools=[{"type": "web_search"}],
        text={"format": {"type": "json_schema", "name": "weekly_content", "schema": SCHEMA, "strict": True}},
    )
    if not r.output_text:
        raise RuntimeError(f"the OpenAI model returned no text (response {r.id}, status {r.status})")
    return json.loads(r.output_text)


def ask_compat(client, prompt):
    """An OpenAI-compatible service has no web search, so the week is written from the page's own numbers.
    Structured output where the service supports it, else JSON mode, else plain text with the schema spelled out."""
    import openai
    system = SYSTEM.format(profile=PROFILE) + (
        "\n\nNo web search is available in this run: build every idea and insight on the page's own numbers above. "
        "For benchmarks, give only widely known figures and say in the source that they're general knowledge, not a fresh search. "
        "Answer with ONE JSON object only, no prose and no code fences, matching this JSON Schema (all properties required):\n"
        + json.dumps(SCHEMA, ensure_ascii=False))
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    text = None
    for fmt in ({"type": "json_schema", "json_schema": {"name": "weekly_content", "schema": SCHEMA, "strict": True}}, {"type": "json_object"}, None):
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, max_tokens=16000, **({"response_format": fmt} if fmt else {}))
            text = (r.choices[0].message.content or "").strip() if r.choices else ""
            break
        except openai.BadRequestError:
            continue
    if not text:
        raise RuntimeError("the AI service returned no text")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except ValueError:
        raise RuntimeError("the AI service's answer wasn't valid JSON")


def ask(prompt):
    """The weekly content from the configured provider; failures end the script with a readable message."""
    key = os.environ.get("SAJADAI_AI_KEY")
    if PROVIDER == "compat":
        import openai
        try:
            return ask_compat(openai.OpenAI(api_key=key or "none", base_url=os.environ.get("SAJADAI_AI_BASE_URL"), max_retries=3, timeout=900), prompt)
        except openai.AuthenticationError:
            sys.exit("the AI service's key is missing or invalid")
        except openai.RateLimitError as e:
            sys.exit(f"the AI service's free limit is used up for now ({e.message})")
        except openai.APIStatusError as e:
            sys.exit(f"AI service error {e.status_code}: {e.message}")
        except openai.APIConnectionError:
            sys.exit("couldn't reach the AI service (network or address)")
        except RuntimeError as e:
            sys.exit(str(e))
    if PROVIDER == "openai":
        import openai
        try:
            return ask_openai(openai.OpenAI(api_key=key, max_retries=4), prompt)
        except openai.AuthenticationError:
            sys.exit("OpenAI API key is missing or invalid")
        except openai.RateLimitError as e:
            sys.exit(f"rate limited by the OpenAI API, or out of credit ({e.message})")
        except openai.APIStatusError as e:
            sys.exit(f"OpenAI API error {e.status_code}: {e.message}")
        except openai.APIConnectionError:
            sys.exit("couldn't reach the OpenAI API (network)")
        except (RuntimeError, ValueError) as e:
            sys.exit(str(e))
    import anthropic
    try:
        return ask_claude(anthropic.Anthropic(api_key=key, max_retries=4) if key else anthropic.Anthropic(max_retries=4), prompt)
    except anthropic.AuthenticationError:
        sys.exit("Anthropic API key is missing or invalid (the panel's AI key, ANTHROPIC_API_KEY or " + KEY_ENV + ")")
    except anthropic.RateLimitError as e:
        sys.exit(f"rate limited by the Anthropic API; try again later ({e.message})")
    except anthropic.APIStatusError as e:
        sys.exit(f"Anthropic API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("couldn't reach the Anthropic API (network)")
    except RuntimeError as e:
        sys.exit(str(e))


def write(name, rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(argv):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        try:
            with open(KEY_ENV, encoding="utf-8") as f:
                m = re.search(r"^\s*ANTHROPIC_API_KEY\s*=\s*['\"]?([^'\"\s]+)", f.read(), re.M)
            if m:
                os.environ["ANTHROPIC_API_KEY"] = m[1]
        except FileNotFoundError:
            pass
    d = load_json(DATA, None)
    if not d:
        sys.exit(f"{DATA}: no data")
    today = datetime.now(TEH).date()
    bench_path = os.path.join(OUT_DIR, "benchmarks.json")
    benchmarks = load_json(bench_path, None) or load_json(os.path.join(ROOT, "content", "benchmarks.json"), [])
    prompt = TASK.format(facts=json.dumps(facts(d, today), ensure_ascii=False, indent=1),
                         benchmarks=json.dumps(benchmarks, ensure_ascii=False, indent=1))
    out = ask(prompt)

    if "--dry-run" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if len(out["ideas"]) >= 3:
        write("ideas.json", out["ideas"])
    if out["insights"]:
        write("insights.json", out["insights"])
    if len(out["benchmarks"]) >= 8:
        write("benchmarks.json", out["benchmarks"])
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} wrote {len(out['ideas'])} ideas, "
          f"{len(out['insights'])} insights, {'new' if len(out['benchmarks']) >= 8 else 'unchanged'} benchmarks")

    env = notify.load_env()
    if env:
        top = sorted(out["ideas"], key=lambda i: i["priority"])[:2]
        lines = ["💡 ایده‌ها و تحلیل این هفته آماده‌ست", "", out["summary"], ""]
        lines += [f"{notify.fa(i['priority'])}. {i['title']}\n«{i['hook']}»" for i in top]
        notify.send(env, "\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
