"""The dashboard as an MCP server, so Claude (Desktop, Code, claude.ai) and ChatGPT can read a user's
Instagram stats and ask for a refresh.

Two ways to run it, same tools:
  hosted  — part of the web panel at /mcp (Authorization: Bearer <token>) or /mcp/u/<token>; the token
            (Settings → "Claude / ChatGPT") picks the user. See sajadai/web.py.
  local   — `python -m sajadai mcp --user <name>` over stdio for Claude Desktop / Claude Code; reads the
            local panel's data for that user.
"""
import time

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import analysis, config, pipeline, store
from .fa import beats as fa_beats, caption as fa_caption, hooks as fa_hooks, human as fa_human

INSTRUCTIONS = """Instagram analytics for the user's page, from their dashboard (Metricool, Buffer and/or Instagram's API).
Start with `overview` for the headline numbers, then `list_reels` / `get_reel` for detail. "multiple_of_median" compares a
reel with the page's median views (above 2 = something worked). view_rate_3s_pct is the share of viewers who stayed past
3 seconds (hook strength). Data refreshes every 6 hours; `refresh_data` fetches now. Times are Tehran time.
When you write anything in Persian for this page (hooks, scripts, captions, comments, DMs): build hooks from `hook_formulas`,
check them with `score_hooks`, time scripts with `beat_sheet`, lint captions with `lint_caption`, and pass the final text
through `humanize_persian`. Never invent numbers or results for the user."""


class Unauthorized(ToolError):
    """A ToolError, so the client sees the message (any other exception reaches it as a generic error)."""


def hosted_user(ctx: Context):
    """The user whose token came with the request: Authorization: Bearer, or the token in the /mcp/u/<token> path."""
    h = {k.lower(): v for k, v in (ctx.headers or {}).items()}
    token = h.get("x-sajadai-token") or ""
    if not token and h.get("authorization", "").lower().startswith("bearer "):
        token = h["authorization"][7:].strip()
    user = store.user_by_api_token(token)
    if not user:
        raise Unauthorized("Missing or invalid dashboard token. Make one in the panel: Settings → Claude / ChatGPT.")
    return user


def build(resolve_user):
    """resolve_user(ctx) -> the users row the call is for."""
    server = MCPServer(name="sajadai-dashboard", title="Instagram dashboard", instructions=INSTRUCTIONS, version="1.0")

    def data(ctx):
        user = resolve_user(ctx)
        return user, analysis.load(config.user_dir(user["id"]) / "data" / "data.json")

    @server.tool(description="Headline numbers for the last `days` days (0 = all): followers and net change, reel count and views, "
                             "3-second view rate, save rate, shares per 1,000 reached, top and weakest reels, goal progress.")
    def overview(ctx: Context, days: int = 30) -> dict:
        return analysis.overview(data(ctx)[1], days)

    @server.tool(description="Reels with their numbers. sort: published (newest first), views, multiple, view_rate, follows or saves. "
                             "days limits to reels published in the last N days (0 = all).")
    def list_reels(ctx: Context, limit: int = 20, sort: str = "published", days: int = 0) -> dict:
        return {"reels": analysis.reels_list(data(ctx)[1], limit, sort, days)}

    @server.tool(description="One reel's full numbers, caption and view curve (views by hours after publishing). "
                             "`reel` is its Instagram URL or shortcode.")
    def get_reel(ctx: Context, reel: str) -> dict:
        r = analysis.reel(data(ctx)[1], reel)
        return r or {"error": "No reel with that URL or shortcode in the dashboard."}

    @server.tool(description="Daily account numbers for the last `days` days: followers, gained, lost, reels published, reel views and "
                             "reach, total views and reach, accounts engaged, profile link taps. Empty fields mean the source doesn't give them.")
    def daily_stats(ctx: Context, days: int = 30) -> dict:
        return {"days": analysis.daily(data(ctx)[1], days)}

    @server.tool(description="The best hours to post in the coming week (Tehran time), from Metricool's estimate when connected.")
    def best_posting_times(ctx: Context, top: int = 5) -> dict:
        return {"best_times": analysis.best_times(data(ctx)[1], top)}

    @server.tool(description="This week's AI-written content plan: reel ideas (with hooks and structure), insights with an action each, "
                             "pages worth learning from, and the user's A/B experiments.")
    def content_plan(ctx: Context) -> dict:
        return analysis.content(data(ctx)[1])

    @server.tool(description="Competitors tracked in Metricool and their most-engaging reels (empty without Metricool competitors).")
    def competitors(ctx: Context) -> dict:
        return analysis.competitors(data(ctx)[1])

    @server.tool(description="Fetch fresh numbers from the user's connected sources now (takes up to a minute). "
                             "Use when the user asks for the latest numbers; data otherwise refreshes every 6 hours.")
    async def refresh_data(ctx: Context) -> dict:
        user = resolve_user(ctx)
        last = store.status(user).get("refresh_at") or 0
        if time.time() - last < 600:  # once per 10 minutes is plenty, and keeps the sources' rate limits safe
            return {"ok": True, "note": "Refreshed less than 10 minutes ago; numbers are current.", "refreshed_at": last}
        ok = await anyio.to_thread.run_sync(pipeline.refresh, user["id"])  # the fetchers take up to a minute
        s = store.status(store.get_user(user["id"]))
        return {"ok": ok, "log": s.get("refresh_log", "")[-1500:]}

    # ---------- Persian writing tools (no AI, run on the server): use them on anything you write for this page ----------

    @server.tool(description="Persian Reel hook formulas (26, localized from instagram-agent-skill): id, name, template, example, "
                             "on-screen card, what each is for and how it gets ruined. Write hooks from these.")
    def hook_formulas(ctx: Context) -> dict:
        resolve_user(ctx)
        return {"formulas": fa_hooks.formulas()}

    @server.tool(description="Score Persian Reel hooks before filming: five checks out of 100 (length, specificity, stakes, payload first, "
                             "speaking to the viewer) plus dealbreakers (greeting, «تو این ویدیو», «اسکرول نکن», hashtag, emoji), and which of "
                             "the 26 formulas each uses. Under 50 = not a hook yet; rewrite instead of polishing.")
    def score_hooks(ctx: Context, hooks: list[str]) -> dict:
        resolve_user(ctx)
        return {"ranked": [dict(r, formula=fa_hooks.classify(r["text"])) for r in fa_hooks.rank(hooks[:20])]}

    @server.tool(description="Time a Persian Reel script (one beat per line) at a speaking rate (words per minute, default 150): timecodes per "
                             "beat, and flags for a hook over 3s, a beat over 4s, three abstract beats in a row, a missing loop, and the gap to target seconds.")
    def beat_sheet(ctx: Context, script: str, target_seconds: float = 0, wpm: int = 150) -> dict:
        resolve_user(ctx)
        return fa_beats.analyse(script[:8000], wpm, target_seconds or None)

    @server.tool(description="Lint a Persian Instagram caption: the ~125 characters the feed shows before «... more», first line, hashtags "
                             "(max 5), dead links, number of asks, the comment keyword, emoji density, half-spaces, and search phrases.")
    def lint_caption(ctx: Context, caption: str, search_phrases: list[str] | None = None) -> dict:
        resolve_user(ctx)
        return fa_caption.analyse(caption[:5000], search_phrases or [])

    @server.tool(description="Humanize Persian text: removes invisible characters (keeps the half-space and fixes missing ones), em dashes, "
                             "curly quotes, bureaucratic and stock AI phrases, flags structural tells to rewrite by hand, and scores it before "
                             "and after on five checks. Run it on every caption, script, comment or DM you write in Persian.")
    def humanize_persian(ctx: Context, text: str, formal: bool = False) -> dict:
        resolve_user(ctx)
        return fa_human.run(text[:12000], casual=not formal)

    return server
