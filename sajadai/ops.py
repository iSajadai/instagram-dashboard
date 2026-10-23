"""Keeping the panel alive: a daily backup of everything in the data folder (the database through
SQLite's online backup, every user's files, the server key), the last 7 kept in DATA_DIR/backups; a
health check for uptime monitors (/healthz); and alerts to the admins (bell + Telegram) when
something breaks."""
import os, shutil, sqlite3, tarfile, tempfile, time, urllib.parse, urllib.request
from datetime import datetime

from . import config, store

KEEP = 7
BACKUPS = config.DATA_DIR / "backups"
BACKUP_HOUR = (3, 30)  # Tehran
_last_tick = {"at": 0.0}
_sent = {}


def tick():
    _last_tick["at"] = time.time()


def backups():
    BACKUPS.mkdir(parents=True, exist_ok=True)
    return sorted((p for p in BACKUPS.glob("backup-*.tar.gz")), reverse=True)


def backup():
    """One .tar.gz of the data folder; returns its path. The database is copied with SQLite's backup
    API, so a write in the middle can't leave a broken copy."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUPS, 0o700)
    name = "backup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".tar.gz"
    out = BACKUPS / name
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = os.path.join(tmp, "panel.db")
        dst = sqlite3.connect(db_copy)
        with store._lock:
            store.db().backup(dst)
        dst.close()
        part = out.with_suffix(".part")
        with tarfile.open(part, "w:gz") as tar:
            tar.add(db_copy, arcname="panel.db")
            for item in sorted(config.DATA_DIR.iterdir()):
                # the live database files are replaced by the copy above; older backups don't go inside new ones
                if item.name == "backups" or item.name.startswith("panel.db"):
                    continue
                tar.add(item, arcname=item.name)
        os.chmod(part, 0o600)
        os.replace(part, out)
    for old in backups()[KEEP:]:
        old.unlink(missing_ok=True)
    return out


def run_backup():
    try:
        p = backup()
        store.set_setting("ops", {**(store.setting("ops", {}) or {}), "backup_at": time.time(), "backup_ok": True,
                                  "backup_msg": f"{p.name} ({p.stat().st_size // 1024} KB)"})
        return True, p.name
    except Exception as e:  # noqa: BLE001 - report whatever went wrong
        store.set_setting("ops", {**(store.setting("ops", {}) or {}), "backup_at": time.time(), "backup_ok": False, "backup_msg": str(e)[:500]})
        alert_admins("⚠️ پشتیبان‌گیری روزانه ناموفق بود", str(e)[:500])
        return False, str(e)


def backup_due(now_teh):
    ops = store.setting("ops", {}) or {}
    last = ops.get("backup_at") or 0
    return (now_teh.hour, now_teh.minute) >= BACKUP_HOUR and datetime.fromtimestamp(last, now_teh.tzinfo).date() != now_teh.date()


def health():
    """What an uptime monitor needs: the database answers, the scheduler is running, the disk has room."""
    out = {"ok": True, "time": int(time.time())}
    try:
        store.q1("SELECT 1 AS one")
        out["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, db=str(e)[:200])
    if config.SCHEDULER:
        age = time.time() - _last_tick["at"] if _last_tick["at"] else None
        out["scheduler_seconds_ago"] = None if age is None else int(age)
        if age is not None and age > 600:  # it wakes every minute
            out.update(ok=False, scheduler="stalled")
    du = shutil.disk_usage(config.DATA_DIR)
    out["disk_free_mb"] = du.free // 2 ** 20
    if du.free < 200 * 2 ** 20:
        out.update(ok=False, disk="low")
    ops = store.setting("ops", {}) or {}
    out["last_backup"] = {"at": int(ops["backup_at"]), "ok": ops.get("backup_ok")} if ops.get("backup_at") else None
    return out


def alert_admins(title, text, every_hours=6):
    """The bell of every admin, and their Telegram when the panel's bot is set up. The same title goes out
    at most once every few hours, so a problem that persists doesn't flood anyone."""
    if time.time() - _sent.get(title, 0) < every_hours * 3600:
        return
    _sent[title] = time.time()
    from . import pipeline  # imported here: pipeline's scheduler imports this module
    bot = store.setting("telegram_bot")
    for u in store.users():
        if not u["is_admin"]:
            continue
        pipeline.add_notice(u["id"], title, text, "system")
        chat = store.prefs(u).get("telegram_chat")
        if bot and chat:
            try:
                body = urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n\n{text}"[:4000]}).encode()
                urllib.request.urlopen(f"https://api.telegram.org/bot{bot}/sendMessage", data=body, timeout=20).close()
            except Exception:  # noqa: BLE001 - the bell still has it
                pass


def tell_user(user, title, text, kind="system"):
    """One user's bell, and their Telegram when the panel's bot is set up and they gave a chat id."""
    from . import pipeline
    pipeline.add_notice(user["id"], title, text, kind)
    bot, chat = store.setting("telegram_bot"), store.prefs(user).get("telegram_chat")
    if bot and chat:
        try:
            body = urllib.parse.urlencode({"chat_id": chat, "text": f"{title}\n\n{text}"[:4000]}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{bot}/sendMessage", data=body, timeout=20).close()
        except Exception:  # noqa: BLE001 - the bell still has it
            pass


def describe():
    return [{"name": p.name, "size_kb": p.stat().st_size // 1024, "at": int(p.stat().st_mtime)} for p in backups()]
