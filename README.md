# Instagram Dashboard

A self-hosted Instagram analytics dashboard with a multi-user panel, built for creators who want to know
**which reel worked, why, and what to film next** — and who want to ask Claude or ChatGPT about their own numbers.

- **Your sources, your keys.** Each user connects their own Metricool (REST API), Buffer, or Instagram API
  account in Settings — any mix. Keys are tested before saving and stored encrypted.
- **A dashboard that explains.** Every reel against the page median, view curves after publishing, rising/weak
  badges for fresh reels, what works by topic and by hook/caption feature, a funnel from views to link taps,
  goals, a 14-day calendar, an A/B experiment log, UTM links, CSV export. Persian (RTL) interface.
- **Weekly AI content plan.** Claude or GPT researches what works in your niche right now and writes reel ideas
  (hook, structure, why it should work) and insights from your numbers.
- **Telegram alerts.** A new reel taking off or falling behind, followers dropping, stale data, and a Saturday report.
- **Claude and ChatGPT connect to it.** An MCP server (hosted per user, or local for Claude Desktop) and a
  read-only API with an OpenAPI spec for ChatGPT Custom GPT Actions.

## Two ways to use it

| | Hosted panel | On your own computer |
|---|---|---|
| Who | you run it on a server for yourself, your team or your clients | one person, locally |
| Users | many; the admin adds them, or opens sign-up | just you |
| Claude / ChatGPT | MCP URL with a per-user token, or ChatGPT Actions | Claude Desktop over stdio; ChatGPT through a tunnel |

## Quick start

```bash
git clone https://github.com/<you>/instagram-dashboard.git && cd instagram-dashboard
cp .env.example .env            # optional
docker compose up -d            # → http://localhost:8000
```

Without Docker (Python 3.11+):

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python -m sajadai serve          # → http://127.0.0.1:8000
```

The first visit creates the **admin** account. Then:

1. **Admin** (optional): a shared AI key (Anthropic or OpenAI) for users who don't bring their own, a Telegram bot
   token (from @BotFather), the public URL, and whether people may sign up themselves. Add users here.
2. **Settings** (every user): connect your sources, describe your page for the AI, set your Telegram chat id and
   goals, then press "fetch data now".

### Sources

| Source | Gives | Needs |
|---|---|---|
| **Metricool** | reels, posts, daily followers, best time to post, competitors | Metricool **Advanced** plan: API token, userId, blogId |
| **Instagram API** | reels and posts, followers, daily account stats, 3-second view rate, demographics | a long-lived token from a Meta app ("Instagram API with Instagram login", scopes `instagram_business_basic`, `instagram_business_manage_insights`); refreshed automatically |
| **Buffer** | reel and post numbers, including follows per reel | Instagram connected as a channel in Buffer + a Buffer API key |

Sources combine: the freshest number wins, history is kept beyond the sources' own windows.
Data refreshes every 6 hours; AI ideas are written Saturdays at 08:30 Tehran time.

## Connect Claude or ChatGPT

In **Settings → Claude / ChatGPT**, make a token; the page shows exactly what to paste.

- **Claude** (claude.ai or Claude Desktop): Settings → Connectors → Add custom connector → `https://<your-panel>/mcp/u/<token>`
- **Claude Code**: `claude mcp add --transport http instagram-dashboard https://<your-panel>/mcp --header "Authorization: Bearer <token>"`
- **ChatGPT**: a connector with the same `/mcp/u/<token>` URL (developer mode), or a Custom GPT whose Action imports
  `https://<your-panel>/openapi.json` with API-key auth (Bearer, your token).

MCP tools: `overview`, `list_reels`, `get_reel`, `daily_stats`, `best_posting_times`, `content_plan`, `competitors`,
`refresh_data`. Everything is read-only except `refresh_data`, which fetches fresh numbers (at most every 10 minutes).

### Fully local with Claude Desktop

Run the panel locally, connect your sources in Settings, then add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "instagram-dashboard": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/instagram-dashboard/docker-compose.yml", "exec", "-T", "panel",
               "python", "-m", "sajadai", "mcp", "--user", "YOUR_USERNAME"]
    }
  }
}
```

Without Docker: `"command": "/path/to/instagram-dashboard/venv/bin/python"`, `"args": ["-m", "sajadai", "mcp", "--user", "YOUR_USERNAME"]`,
`"env": {"PYTHONPATH": "/path/to/instagram-dashboard", "SAJADAI_DATA_DIR": "/path/to/instagram-dashboard/var"}`.

ChatGPT can't reach `localhost`. To use it with a local panel, expose it with a tunnel
(e.g. `cloudflared tunnel --url http://localhost:8000`) and use the tunnel URL above.

## Running it on a server

Put the panel behind HTTPS. `deploy/nginx-panel.conf` is a reverse-proxy config for `127.0.0.1:8000`, and
`deploy/sajadai-panel.service` a systemd unit for running it without Docker. Set `SAJADAI_PUBLIC_URL` and
`SAJADAI_SECURE_COOKIES=1` in `.env`.

Back up the data folder (`./var`, or `SAJADAI_DATA_DIR`): it holds the database, the encryption key
(`secret.key`, or set `SAJADAI_SECRET_KEY`) and every user's numbers. Without the key, stored credentials can't be read.

## Command line

```
python -m sajadai serve [--host 127.0.0.1] [--port 8000]
python -m sajadai mcp --user NAME                 # MCP over stdio
python -m sajadai create-user NAME [--admin]
python -m sajadai import NAME PATH                # copy an existing dashboard folder (raw/, content/, data/) into a user
python -m sajadai refresh NAME | content NAME     # run a user's refresh / AI content now
```

## How it fits together

```
sajadai/web.py            panel (FastAPI): sign-in, dashboard, settings, admin, /api/v1, /openapi.json, /mcp
sajadai/pipeline.py       per-user jobs and the scheduler; runs scripts/ with only that user's folder and keys
sajadai/mcp_server.py     MCP tools (hosted and stdio)
scripts/fetch_*.py        Metricool / Buffer / Instagram API → raw/
scripts/shape.py          raw/ → data.json (merging sources, keeping history)
scripts/write_content.py  weekly AI ideas and insights (Claude or GPT, with web search)
scripts/notify.py         Telegram alerts and the weekly report
index.html                the dashboard page (d3 charts, Vazirmatn font, no CDN)
```

## فارسی

داشبورد تحلیل اینستاگرام با پنل چندکاربره. هر کاربر از «تنظیمات» منبع‌های خودش رو وصل می‌کنه: Metricool، Buffer یا API اینستاگرام. صفحهٔ معرفی پیجش رو برای هوش مصنوعی می‌نویسه و Claude یا ChatGPT خودش رو به داده‌هاش وصل می‌کنه.

**نصب:**
1. `docker compose up -d` رو اجرا کن، `http://localhost:8000` رو باز کن و حساب ادمین رو بساز.
2. تو «تنظیمات» کلیدها رو وارد کن.
3. اتصال به Claude و ChatGPT: «تنظیمات ← اتصال به Claude و ChatGPT».

## License

MIT — see [LICENSE](LICENSE). Vazirmatn (OFL) and d3 (ISC) are bundled under their own licenses in `assets/`.
