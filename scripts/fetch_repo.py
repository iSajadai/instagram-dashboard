#!/usr/bin/env python3
"""Pull a page's data from the git repo a Claude routine keeps fresh (the routine reads Metricool through
claude.ai's Metricool connector, which works on plans without Metricool's REST API, and commits
raw/*.json and content/*.json every 6 hours). Copies those files into $SAJADAI_STATE so shape.py
builds the panel's data.json from them, and writes raw/repo_source.json with the commit it came from.

Env: SAJADAI_DATA_REPO (git URL or owner/name), SAJADAI_DATA_BRANCH (default main), SAJADAI_REPO_KEY
(an SSH deploy key with read access; optional for public repos), SAJADAI_REPO_ONLY=1 when the page has
no other source (then the repo's own data.json, with its full history, becomes the base).

Usage: SAJADAI_STATE=… SAJADAI_DATA_REPO=owner/name python3 scripts/fetch_repo.py
"""
import json, os, shutil, subprocess, sys, time
from datetime import datetime, timezone

STATE = os.environ.get("SAJADAI_STATE") or sys.exit("set SAJADAI_STATE")
REPO = os.environ.get("SAJADAI_DATA_REPO") or sys.exit("set SAJADAI_DATA_REPO")
BRANCH = os.environ.get("SAJADAI_DATA_BRANCH") or "main"
KEY = os.environ.get("SAJADAI_REPO_KEY") or ""
CACHE = os.path.join(STATE, "repo_cache")
RAW_FILES = ("reels", "account", "best_time", "competitors", "competitor_reels", "stories", "countries", "age_gender", "scheduled", "posts")
CONTENT_FILES = ("ideas", "insights", "benchmarks")


def url():
    if REPO.startswith(("git@", "https://", "ssh://", "/", "file://")):
        return REPO
    return f"git@github.com:{REPO}.git" if KEY else f"https://github.com/{REPO}.git"


def git(*args, cwd=None):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if KEY:
        known = os.path.join(os.path.dirname(KEY), "known_hosts")
        env["GIT_SSH_COMMAND"] = f"ssh -i {KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known}"
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["?"]
        if "Permission denied" in r.stderr or "Repository not found" in r.stderr or "could not read" in r.stderr:
            sys.exit(f"no access to {REPO}: add the panel's deploy key to the repo (read access). git: {msg[0]}")
        sys.exit(f"git {args[0]} failed: {msg[0]}")
    return r.stdout.strip()


def valid_raw(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(d, dict) and (isinstance(d.get("rows"), list) or isinstance(d.get("data"), list))


def valid_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            return isinstance(json.load(f), list)
    except (OSError, ValueError):
        return False


def main():
    if os.path.isdir(os.path.join(CACHE, ".git")):
        git("fetch", "--depth", "1", "origin", BRANCH, cwd=CACHE)
        git("reset", "--hard", "FETCH_HEAD", cwd=CACHE)
    else:
        shutil.rmtree(CACHE, ignore_errors=True)
        git("clone", "--depth", "1", "--branch", BRANCH, url(), CACHE)
    commit = git("rev-parse", "HEAD", cwd=CACHE)
    committed = git("log", "-1", "--format=%cI", cwd=CACHE)
    # the newest commit can be a code change; the routine's data.json says when it actually read Metricool
    try:
        with open(os.path.join(CACHE, "data", "data.json"), encoding="utf-8") as f:
            committed = json.load(f).get("generated_at") or committed
    except (OSError, ValueError):
        pass
    raw = os.path.join(STATE, "raw")
    content = os.path.join(STATE, "content")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(content, exist_ok=True)
    copied = []
    for name in RAW_FILES:
        src = os.path.join(CACHE, "raw", name + ".json")
        if os.path.exists(src) and valid_raw(src):
            shutil.copy2(src, os.path.join(raw, name + ".json"))
            copied.append(name)
    try:
        with open(os.path.join(content, "insights_meta.json"), encoding="utf-8") as f:
            panel_insights = json.load(f).get("source") == "panel"
    except (OSError, ValueError, AttributeError):
        panel_insights = False
    for name in CONTENT_FILES:
        if name == "insights" and panel_insights:
            continue  # the panel writes its own analysis after every sync; the routine's weekly one would be older
        src = os.path.join(CACHE, "content", name + ".json")
        if os.path.exists(src) and valid_list(src):
            shutil.copy2(src, os.path.join(content, name + ".json"))
            copied.append("content/" + name)
    base = os.path.join(CACHE, "data", "data.json")
    if os.environ.get("SAJADAI_REPO_ONLY") == "1" and os.path.exists(base):
        # the routine's data.json carries every snapshot it has taken; shape.py merges the raw files on top
        os.makedirs(os.path.join(STATE, "data"), exist_ok=True)
        shutil.copy2(base, os.path.join(STATE, "data", "data.json"))
    if "reels" not in copied and "account" not in copied:
        sys.exit(f"{REPO}@{commit[:7]} has no usable raw/reels.json or raw/account.json")
    with open(os.path.join(raw, "repo_source.json"), "w", encoding="utf-8") as f:
        json.dump({"repo": REPO, "branch": BRANCH, "commit": commit, "committed_at": committed,
                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": copied}, f)
    print(f"repo {REPO}@{commit[:7]} ({committed}): {', '.join(copied)}")


if __name__ == "__main__":
    main()
