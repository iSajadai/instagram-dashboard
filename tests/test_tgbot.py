"""The Telegram bot against a fake Bot API: linking with a one-time code, commands, the board buttons,
switching pages, and questions going to the assistant."""
import json, os, sys, tempfile, time

os.environ["SAJADAI_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sajadai import config, store, tgbot  # noqa: E402

store.db()
sent = []


def fake_api(token, method, **params):
    sent.append((method, params))
    return {"username": "sj_test_bot"} if method == "getMe" else True


tgbot.api = fake_api
uid = store.create_user("sajad", "secret-pass-1", is_admin=True) if hasattr(store, "create_user") else None
u = store.get_user(uid if isinstance(uid, int) else uid["id"]) if uid is not None else store.users()[0]
p = store.prefs(u)
p["page_name"] = "سجاد"
store.set_prefs(u["id"], p)
d = config.user_dir(u["id"])
(d / "content").mkdir(parents=True, exist_ok=True)
(d / "data").mkdir(parents=True, exist_ok=True)
(d / "data" / "data.json").write_text(json.dumps({"reels": [], "account": [], "ideas": [{"priority": 1, "title": "ریل پرامپت", "hook": "پرامپت خوب کوتاهه"}]}), encoding="utf-8")
(d / "content" / "board.json").write_text(json.dumps([{"id": "c1", "title": "ریل شب یلدا", "stage": "idea", "due": "2026-12-21"},
                                                      {"id": "c2", "title": "منتشرشده", "stage": "published"}], ensure_ascii=False), encoding="utf-8")
CHAT = 555001


def msg(text):
    sent.clear()
    tgbot.handle("T", {"update_id": 1, "message": {"chat": {"id": CHAT, "type": "private"}, "text": text}})
    return [p.get("text", "") for m, p in sent if m == "sendMessage"]


def test_unlinked_chat_is_told_how():
    out = msg("سلام")
    assert out and "وصل نیست" in out[0] and str(CHAT) in out[0]


def test_link_with_code():
    code = tgbot.link_code(u)
    out = msg(f"/start {code}")
    assert "وصل شد" in out[0] and "سجاد" in out[0]
    assert store.prefs(store.get_user(u["id"]))["telegram_chat"] == str(CHAT)
    assert "منقضی" in msg(f"/start {code}")[0], "a code works once"


def test_commands():
    assert "ریل پرامپت" in msg("/ideas")[0]
    assert "۷ روز اخیر" in msg("/stats")[0]
    assert "خالیه" in msg("/queue")[0]


def test_board_button_moves_card():
    msg("/board")
    kb = next(p for m, p in sent if m == "sendMessage")["reply_markup"]["inline_keyboard"]
    assert len(kb) == 1 and kb[0][0]["callback_data"] == f"mv:{u['id']}:c1"
    sent.clear()
    tgbot.handle("T", {"update_id": 2, "callback_query": {"id": "q", "data": f"mv:{u['id']}:c1", "message": {"chat": {"id": CHAT}, "message_id": 9}}})
    board = json.loads((d / "content" / "board.json").read_text(encoding="utf-8"))
    assert board[0]["stage"] == "script"
    assert any(m == "editMessageText" for m, _ in sent) and "سناریو" in next(p for m, p in sent if m == "answerCallbackQuery")["text"]


def test_other_chat_cannot_move_cards():
    tgbot.handle("T", {"update_id": 3, "callback_query": {"id": "q", "data": f"mv:{u['id']}:c1", "message": {"chat": {"id": 999}, "message_id": 9}}})
    assert json.loads((d / "content" / "board.json").read_text(encoding="utf-8"))[0]["stage"] == "script"


def test_question_goes_to_assistant():
    seen = {}
    def fake_ask(user, system, messages, **k):
        seen["q"] = messages[-1]["content"]
        return "بهترین ریل **ریل پرامپت** بود."
    tgbot.ai.ask = fake_ask
    import sajadai.web as web
    web.page_context = lambda user: {"page": "سجاد"}
    out = msg("این هفته کدوم ریل بهتر بود؟")
    assert seen["q"] == "این هفته کدوم ریل بهتر بود؟" and out[0] == "بهترین ریل ریل پرامپت بود."
    assert any(m == "sendChatAction" for m, _ in sent)


def test_group_chats_ignored():
    sent.clear()
    tgbot.handle("T", {"update_id": 4, "message": {"chat": {"id": -100, "type": "group"}, "text": "/stats"}})
    assert not sent


if __name__ == "__main__":
    bad = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                bad += 1
                print("FAIL", k, repr(e)[:400])
    sys.exit(1 if bad else 0)
