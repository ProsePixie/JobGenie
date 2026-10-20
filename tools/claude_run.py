#!/usr/bin/env python3
"""Run one headless Claude Code request and return its text answer.

Shared by the CV builder's short AI tasks (summary draft, translation). The two
Windows lessons from tools/draft_letter.py are built in: the CLI is resolved
through shutil.which (claude.CMD needs PATHEXT), and the prompt goes in on
stdin, because a batch shim ends an argument at the first newline.

These tasks need no tools at all: every fact they may use is in the prompt.
--restricted removes command execution; --disallowedTools removes file edits.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every headless session gets these, whatever it is for. It reads a posting,
# which is third-party text that may be written to steer it (CLAUDE.md hard
# rule 3), so it gets no way to act on that: --restricted removes command
# execution and WebFetch, --strict-mcp-config drops any MCP servers the machine
# has configured, the edit tools and WebSearch are removed, and the private
# tier cannot be read at all (hard rule 1; Read rules also cover Grep and
# Glob). A session returns its answer as text; the calling script decides
# what, if anything, gets written. The deny list is variadic, so it goes last.
SAFE_ARGS = ["--restricted", "--strict-mcp-config", "--output-format", "json",
             "--disallowedTools", "Edit", "Write", "NotebookEdit", "WebFetch",
             "WebSearch", "Read(./profile/private/**)"]


# The app runs without a console (pythonw). Every program it starts would open its
# own console window; the sign-in check did, on every window focus, and each new
# window took focus, which triggered the next check: command prompts opened
# without end (2026-10-20). A hidden console is inherited by everything below it.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

SIGN_IN_AGAIN = ("Your Claude sign-in has expired. Open a terminal, run claude, type /login, "
                 "finish signing in in the browser, then try again.")
_AUTH_RE = re.compile(r"failed to authenticate|oauth|not logged in|please run /login|"
                      r"session expired|invalid api key|authentication", re.I)


def explain(text):
    """Plain words for the one failure the user can fix himself. The raw
    message ("Failed to authenticate: OAuth session expired and could not be
    refreshed") was all the app showed when summaries and letters stopped
    working (2026-10-19)."""
    return SIGN_IN_AGAIN if _AUTH_RE.search(text or "") else text


def logged_in():
    """(True, False or None, note). None when it cannot be told. `claude auth
    status` reads the local login and costs no request, so the app can check
    before he clicks something that will fail."""
    claude = find_claude()
    if not claude:
        return None, "claude CLI not found"
    try:
        proc = subprocess.run([claude, "auth", "status", "--json"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20,
                              creationflags=NO_WINDOW)
        return bool(json.loads(proc.stdout).get("loggedIn")), ""
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None, "could not check the sign-in"


def find_claude():
    found = shutil.which("claude")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "npm" / "claude.cmd"
        if candidate.exists():
            return str(candidate)
    return None


def ask(prompt, timeout=240):
    """(ok, text). text is the answer, or the reason it failed."""
    claude = find_claude()
    if not claude:
        return False, ("claude CLI not found. Install it and log in once "
                       "(run `claude`, then /login).")
    cmd = [claude, "-p"] + SAFE_ARGS
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), input=prompt, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, "the AI request did not finish within %d seconds" % timeout
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return False, explain((proc.stderr or proc.stdout or "no output").strip()[:400])
    if proc.returncode != 0 or payload.get("is_error"):
        return False, explain(str(payload.get("result") or proc.stderr or "request failed")[:400])
    return True, str(payload.get("result") or "").strip()
