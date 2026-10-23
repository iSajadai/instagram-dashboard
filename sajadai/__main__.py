"""Command line for the panel.

  python -m sajadai serve [--host 127.0.0.1] [--port 8000]   the web panel (sign in, settings, dashboards, /mcp)
  python -m sajadai mcp --user NAME                          MCP over stdio for Claude Desktop / Claude Code
  python -m sajadai create-user NAME [--admin] [--password-stdin]
                                                             add a user without the browser (asks for the password,
                                                             or reads it from stdin)
  python -m sajadai import NAME PATH                         copy an existing dashboard (repo checkout or
                                                             /var/lib/sajadai-dashboard) into a user's data
  python -m sajadai refresh NAME | content NAME              run a user's data refresh / AI content now

Data lives in $SAJADAI_DATA_DIR (default: ./var in the repo).
"""
import argparse, getpass, sys

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
        if store.find_user(a.name):
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


if __name__ == "__main__":
    main()
