"""The dashboard in the panel's Telegram bot: link a chat from settings with one tap (t.me/<bot>?start=<code>),
then ask about the page in plain Persian (the same assistant as the dashboard, with the page's numbers),
or use /stats /reels /ideas /board /queue /pages. Board cards move to their next stage from buttons.

The bot long-polls Telegram from a thread in the panel (no webhook to set up). Each chat can be linked to
several pages (an agency); /pages switches between them."""
import json, re, secrets, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import timedelta

from . import ai, analysis, config, pages, store

STAGES = [("idea", "ایده"), ("script", "سناریو"), ("filmed", "فیلم‌برداری شد"), ("published", "منتشر شد")]
_history = {}  # chat → last messages with the assistant
LINK_TTL = 900


def api(token, method, **params):
    data = urllib.parse.urlencode({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=70) as r:
        return json.load(r).get("result")


# ---------- linking a chat to a page ----------

def link_code(user):
    """A one-time code for t.me/<bot>?start=<code>, good for 15 minutes."""
    codes = {k: v for k, v in (store.setting("tg_codes", {}) or {}).items() if v[1] > time.time()}
    code = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
    codes[code] = [user["id"], time.time() + LINK_TTL]
    store.set_setting("tg_codes", codes)
    return code


def bot_name(token):
    cached = store.setting("tg_bot_name")
    if cached and cached[0] == token[-8:]:
        return cached[1]
    name = (api(token, "getMe") or {}).get("username")
    store.set_setting("tg_bot_name", [token[-8:], name])
    return name


def redeem(code, chat):
    codes = store.setting("tg_codes", {}) or {}
    v = codes.pop(code, None)
    store.set_setting("tg_codes", codes)
    if not v or v[1] < time.time():
        return None
    user = store.get_user(v[0])
    p = store.prefs(user)
    p["telegram_chat"] = str(chat)
    store.set_prefs(user["id"], p)
    cur = store.setting("tg_current", {}) or {}
    cur[str(chat)] = user["id"]
    store.set_setting("tg_current", cur)
    return store.get_user(user["id"])


def linked(chat):
    return [u for u in store.users() if store.prefs(u).get("telegram_chat") == str(chat)]


def current(chat):
    us = linked(chat)
    if not us:
        return None, us
    want = (store.setting("tg_current", {}) or {}).get(str(chat))
    return next((u for u in us if u["id"] == want), us[0]), us


def name_of(u):
    return store.prefs(u).get("page_name") or u["username"]


# ---------- answers ----------

def data(u):
    return analysis.load(config.user_dir(u["id"]) / "data" / "data.json") or {}


def stats(u):
    d = data(u)
    t = pages.today()
    cur = pages.period(d, (t - timedelta(days=6)).isoformat(), t.isoformat())
    prev = pages.period(d, (t - timedelta(days=13)).isoformat(), (t - timedelta(days=7)).isoformat())

    def ch(a, b):
        if a is None or not b:
            return ""
        pct = round((a - b) / b * 100)
        return f" ({'▲' if pct >= 0 else '▼'} {pages.fa(abs(pct))}٪)"
    lines = [f"📊 {name_of(u)} · ۷ روز اخیر", "",
             f"بازدید ریل‌ها: {pages.fa(cur['views'])}{ch(cur['views'], prev['views'])}",
             f"ریل منتشرشده: {pages.fa(cur['n'])}",
             f"فالوئر: {pages.fa(cur['followers'])}" + (f" (خالص {pages.fa(cur['followers_net'])})" if cur["followers_net"] is not None else "")]
    if cur.get("view_rate") is not None:
        lines.append(f"ماندن بعد از ۳ ثانیه: {pages.fa(cur['view_rate'], 1, '٪')}")
    if cur.get("save_rate") is not None:
        lines.append(f"نرخ ذخیره: {pages.fa(cur['save_rate'], 1, '٪')}")
    return "\n".join(lines)


def reels(u):
    rs = analysis.reels_list(data(u), 30)[:6]
    if not rs:
        return "تو ۳۰ روز اخیر ریلی نیست."
    out = ["🎬 ریل‌های اخیر", ""]
    for r in rs:
        cap = (r.get("caption") or r.get("first_line") or "ریل").split("\n")[0][:50]
        mult = r.get("multiple_of_median")
        out.append(f"• {cap}\n  {pages.fa(r.get('views'))} بازدید" + (f" · {pages.fa(mult, 1)}× میانه" if mult else "") + (f"\n  {r['url']}" if r.get("url") else ""))
    return "\n".join(out)


def ideas(u):
    ids = sorted(data(u).get("ideas", []), key=lambda i: i.get("priority") or 99)[:5]
    if not ids:
        return "ایدهٔ این هفته هنوز نوشته نشده."
    return "💡 ایده‌های این هفته\n\n" + "\n\n".join(f"{pages.fa(i + 1)}. {x.get('title') or ''}\n«{x.get('hook') or ''}»" for i, x in enumerate(ids))


def board_path(u):
    return config.user_dir(u["id"]) / "content" / "board.json"


def board(u):
    items = [i for i in (analysis.load(board_path(u)) or []) if isinstance(i, dict) and i.get("stage") != "published"] if isinstance(analysis.load(board_path(u)), list) else []
    if not items:
        return "🗂 بُرد تولید خالیه (یا همه منتشر شدن).", None
    items.sort(key=lambda i: (i.get("due") or "9999", [s for s, _ in STAGES].index(i.get("stage", "idea"))))
    lines, kb = ["🗂 بُرد تولید (منتشرنشده‌ها)", ""], []
    for it in items[:8]:
        ix = [s for s, _ in STAGES].index(it.get("stage", "idea"))
        due = f" · سررسید {pages.jdate(it['due'], year=False)}" if it.get("due") else ""
        lines.append(f"• [{STAGES[ix][1]}] {it.get('title', '')[:60]}{due}")
        if ix + 1 < len(STAGES):
            kb.append([{"text": f"{it.get('title', '')[:24]} ← {STAGES[ix + 1][1]}", "callback_data": f"mv:{u['id']}:{it['id']}"[:64]}])
    return "\n".join(lines), {"inline_keyboard": kb} if kb else None


def move_card(u, card):
    items = analysis.load(board_path(u))
    if not isinstance(items, list):
        return None
    for it in items:
        if it.get("id") == card:
            ix = [s for s, _ in STAGES].index(it.get("stage", "idea"))
            if ix + 1 >= len(STAGES):
                return it
            it["stage"], it["moved"] = STAGES[ix + 1][0], int(time.time())
            board_path(u).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
            return it
    return None


def queue(u):
    from . import ig
    q = [i for i in reversed(ig.load_queue(u))][:6]
    if not q:
        return "📤 صف انتشار خالیه."
    label = {"scheduled": "⏳ زمان‌بندی‌شده", "processing": "⚙️ در حال پردازش", "published": "✅ منتشر شد", "failed": "⚠️ منتشر نشد"}
    return "📤 صف انتشار\n\n" + "\n".join(f"{label.get(i['status'], i['status'])} · {(i.get('caption') or 'بدون کپشن').splitlines()[0][:50] if i.get('caption') else 'بدون کپشن'}"
                                         + (f"\n  {i['permalink']}" if i.get("permalink") else "") for i in q)


HELP = """سلام! من دستیار داشبورد اینستاگرامتم.
هر سؤالی دربارهٔ پیجت داری همین‌جا بپرس، مثلاً «این هفته کدوم ریل بهتر بود و چرا؟»

دستورها:
/stats آمار ۷ روز اخیر
/reels ریل‌های اخیر
/ideas ایده‌های این هفته
/board بُرد تولید (با دکمهٔ جابه‌جایی)
/queue صف انتشار
/pages عوض کردن پیج"""


def ask(u, chat, text):
    from .web import CHAT_SYSTEM, page_context
    h = _history.setdefault(chat, [])[-6:]
    msgs = h + [{"role": "user", "content": text[:2000]}]
    try:
        answer = ai.ask(u, CHAT_SYSTEM.format(context=json.dumps(page_context(u), ensure_ascii=False)), msgs, max_tokens=2000)
    except ai.AIError as e:
        return "⚠️ " + str(e)
    answer = re.sub(r"\*\*(.+?)\*\*", r"\1", str(answer))  # plain text: Telegram would show the stars
    _history[chat] = (msgs + [{"role": "assistant", "content": answer}])[-8:]
    return answer


# ---------- the loop ----------

def handle(token, upd):
    if "callback_query" in upd:
        cq = upd["callback_query"]
        chat = cq["message"]["chat"]["id"]
        m = re.fullmatch(r"(mv|pg):(\d+):?(.*)", cq.get("data") or "")
        us = {u["id"]: u for u in linked(chat)}
        note = ""
        if m and int(m.group(2)) in us:
            u = us[int(m.group(2))]
            if m.group(1) == "pg":
                cur = store.setting("tg_current", {}) or {}
                cur[str(chat)] = u["id"]
                store.set_setting("tg_current", cur)
                note = f"پیج فعلی: {name_of(u)}"
                api(token, "sendMessage", chat_id=chat, text=f"✅ از این به بعد دربارهٔ «{name_of(u)}» جواب می‌دم.")
            else:
                it = move_card(u, m.group(3))
                note = f"«{it['title'][:30]}» رفت به «{dict(STAGES)[it['stage']]}»" if it else "کارت پیدا نشد"
                text, kb = board(u)
                api(token, "editMessageText", chat_id=chat, message_id=cq["message"]["message_id"], text=text, **({"reply_markup": kb} if kb else {}))
        api(token, "answerCallbackQuery", callback_query_id=cq["id"], text=note[:190])
        return
    msg = upd.get("message") or {}
    chat, text = (msg.get("chat") or {}).get("id"), (msg.get("text") or "").strip()
    if not chat or not text or (msg.get("chat") or {}).get("type") != "private":
        return

    def say(t, kb=None):
        for i in range(0, len(t), 3900):
            api(token, "sendMessage", chat_id=chat, text=t[i:i + 3900], disable_web_page_preview="true", **({"reply_markup": kb} if kb and i == 0 else {}))
    m = re.fullmatch(r"/start(?:\s+(\S+))?", text)
    if m and m.group(1):
        u = redeem(m.group(1), chat)
        say(f"✅ وصل شد به پیج «{name_of(u)}». گزارش‌ها و هشدارها هم از این به بعد همین‌جا میاد.\n\n" + HELP if u
            else "این لینک اتصال منقضی شده؛ از تنظیمات پنل («تلگرام») یه لینک تازه بگیر.")
        return
    u, us = current(chat)
    if not u:
        say("این چت هنوز به داشبوردی وصل نیست. تو پنل برو «تنظیمات ← تلگرام» و دکمهٔ «اتصال با یک لمس» رو بزن.\n"
            f"(chat id این گفت‌وگو: {chat})")
        return
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if cmd in ("/start", "/help"):
        say(HELP)
    elif cmd == "/stats":
        say(stats(u))
    elif cmd == "/reels":
        say(reels(u))
    elif cmd == "/ideas":
        say(ideas(u))
    elif cmd == "/board":
        t, kb = board(u)
        say(t, kb)
    elif cmd == "/queue":
        say(queue(u))
    elif cmd == "/pages":
        if len(us) < 2:
            say(f"فقط یه پیج به این چت وصله: {name_of(u)}")
        else:
            say("کدوم پیج؟", {"inline_keyboard": [[{"text": ("✓ " if x["id"] == u["id"] else "") + name_of(x), "callback_data": f"pg:{x['id']}"}] for x in us]})
    elif cmd:
        say("این دستور رو نمی‌شناسم.\n\n" + HELP)
    else:
        api(token, "sendChatAction", chat_id=chat, action="typing")
        say(ask(u, chat, text))


def loop(stop):
    """Long-poll the panel's bot. Waits while no bot is set; picks up a new token by itself."""
    token_seen, offset = None, None
    while not stop.is_set():
        token = store.setting("telegram_bot")
        if not token:
            stop.wait(30)
            continue
        if token != token_seen:
            try:
                api(token, "deleteWebhook")
            except Exception:  # noqa: BLE001
                pass
            token_seen, offset = token, store.setting("tg_offset")
        try:
            ups = api(token, "getUpdates", timeout=50, allowed_updates=["message", "callback_query"], **({"offset": offset} if offset else {})) or []
        except urllib.error.HTTPError as e:
            stop.wait(60 if e.code in (401, 404, 409) else 10)  # bad token, or another process polling the same bot
            continue
        except Exception:  # noqa: BLE001 — network
            stop.wait(10)
            continue
        for upd in ups:
            offset = upd["update_id"] + 1
            try:
                handle(token, upd)
            except Exception as e:  # noqa: BLE001 — one bad update mustn't stop the bot
                print("telegram bot:", repr(e)[:300], flush=True)
        if ups:
            store.set_setting("tg_offset", offset)
