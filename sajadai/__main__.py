"""Command line for the panel.

  python -m sajadai serve [--host 127.0.0.1] [--port 8000]   the web panel (sign in, settings, dashboards, /mcp)
  python -m sajadai mcp --user NAME                          MCP over stdio for Claude Desktop / Claude Code
  python -m sajadai create-user NAME [--admin] [--password-stdin]
                                                             add a user without the browser (asks for the password,
                                                             or reads it from stdin)
  python -m sajadai import NAME PATH                         copy an existing dashboard (repo checkout or
                                                             /var/lib/sajadai-dashboard) into a user's data
  python -m sajadai refresh NAME | content NAME              run a user's data refresh / AI content now
  python -m sajadai build-skills                             copy the Persian tools into skills/ig-fa-tools (the Claude skills)

Data lives in $SAJADAI_DATA_DIR (default: ./var in the repo).
"""
import argparse, getpass, shutil, sys

from . import config, pipeline, store


def user_or_exit(name):
    u = store.find_user(name)
    if not u:
        sys.exit(f"no user named {name!r} (users: {', '.join(x['username'] for x in store.users()) or 'none yet'})")
    return u


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m sajadai", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    m = sub.add_parser("mcp")
    m.add_argument("--user", required=True)
    c = sub.add_parser("create-user")
    c.add_argument("name")
    c.add_argument("--admin", action="store_true")
    c.add_argument("--password-stdin", action="store_true", help="read the password from stdin (for install scripts)")
    i = sub.add_parser("import")
    i.add_argument("name")
    i.add_argument("path")
    for name in ("refresh", "content"):
        sub.add_parser(name).add_argument("name")
    sub.add_parser("build-skills")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("sajadai.web:app", host=a.host, port=a.port, proxy_headers=True, forwarded_allow_ips="*")
    elif a.cmd == "mcp":
        from . import mcp_server
        u = user_or_exit(a.user)
        uid = u["id"]
        # stdio belongs to one person on their own machine: every call is for this user
        mcp_server.build(lambda ctx: store.get_user(uid)).run()
    elif a.cmd == "create-user":
        pw = sys.stdin.readline().rstrip("\n") if a.password_stdin else getpass.getpass("password (8+ characters): ")
        if len(pw) < 8:
            sys.exit("password too short")
        if store.name_taken(a.name):
            sys.exit(f"{a.name!r} already exists")
        uid = store.create_user(a.name, pw, a.admin, prefs={"page_name": a.name})
        pipeline.ensure_user_dir(uid)
        print(f"created {a.name} (id {uid}){' as admin' if a.admin else ''}; data in {config.user_dir(uid)}")
    elif a.cmd == "import":
        u = user_or_exit(a.name)
        pipeline.import_legacy(u["id"], a.path)
        ok, out = pipeline.run_script(u["id"], "shape.py", {})
        print(out)
        sys.exit(0 if ok else 1)
    elif a.cmd == "refresh":
        u = user_or_exit(a.name)
        ok = pipeline.refresh(u["id"])
        print(store.status(store.get_user(u["id"])).get("refresh_log", ""))
        sys.exit(0 if ok else 1)
    elif a.cmd == "content":
        u = user_or_exit(a.name)
        ok = pipeline.write_content(u["id"])
        print(store.status(store.get_user(u["id"])).get("content_log", ""))
        sys.exit(0 if ok else 1)
    elif a.cmd == "build-skills":
        build_skills()


TOOLS_ENTRY = '''#!/usr/bin/env python3
"""Persian Instagram tools for the ig-*-fa Claude skills: hook scores, beat timing, the caption linter,
the humanizer, swipe ranking, the 26 formulas and the profile rubric. Standard library only.
Built from sajadai/fa by `python -m sajadai build-skills`; edit it there, not here."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fa.cli import main  # noqa: E402

main()
'''


def build_skills():
    """skills/ig-fa-tools gets a copy of sajadai/fa (it imports nothing else) and fa_tools.py to run it."""
    src = config.ROOT / "sajadai" / "fa"
    dst = config.ROOT / "skills" / "ig-fa-tools"
    shutil.rmtree(dst / "fa", ignore_errors=True)
    shutil.copytree(src, dst / "fa", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dst / "fa_tools.py").write_text(TOOLS_ENTRY, encoding="utf-8")
    print(f"built {dst}")


if __name__ == "__main__":
    main()
