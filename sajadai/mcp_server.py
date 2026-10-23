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

INSTRUCTIONS = """Instagram analytics for the user's page, from their dashboard (Metricool, Buffer and/or Instagram's API).
Start with `overview` for the headline numbers, then `list_reels` / `get_reel` for detail. "multiple_of_median" compares a
reel with the page's median views (above 2 = something worked). view_rate_3s_pct is the share of viewers who stayed past
3 seconds (hook strength). Data refreshes every 6 hours; `refresh_data` fetches now. Times are Tehran time."""


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

    return server
