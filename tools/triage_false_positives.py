#!/usr/bin/env python3
"""Turn accumulated "Report as wrong" entries into an actual search-term fix.

Same mechanism as tools/draft_letter.py: shells out to a headless Claude Code
session pointed at this repo, so it reads CLAUDE.md and this project's own
guardrails the way any session working here would, rather than re-deriving
them. Nothing here auto-commits or auto-marks anything reviewed on its own
say-so - a bad edit to a search-term file is a git diff away from being
caught, but "did the reasoning actually hold up" still gets a human look
before it becomes permanent, the same as every other change in this project.

What it's told to do, and not do:
  - Read every currently-unreviewed report, profile/watchlist.json's own
    _test_before_adding note and avoid list, and tools/watch_ats.py's
    NEGATIVE and NEGATIVE_COMPANIES lists, before touching anything.
  - For a report that reveals a real, generalizable problem (a term matching
    the wrong industry, a company in the wrong domain entirely) - make the
    smallest correct edit to profile/watchlist.json and/or tools/
    watch_ats.py, commented the way every existing entry in those files
    already explains itself.
  - For a report that is just "not what I wanted" with no generalizable
    cause (pay too low, wrong city, disliked the company) - change nothing.
    A report is not automatically a mandate; that is the whole reason this
    review step exists rather than auto-applying the log.
  - Never touch career.json, evidence.json, personas.json, or anything
    outside those two files.

This script marks the reports it sent as reviewed once the session finishes,
regardless of whether it changed anything - a report that was correctly
judged to need no fix has still been reviewed. It does not commit anything;
`git diff` and `git add` stay a deliberate, separate step.

    py tools/triage_false_positives.py
    py tools/triage_false_positives.py --dry-run
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "false-positives.jsonl"
WATCHLIST = ROOT / "profile" / "watchlist.json"
WATCH_ATS = ROOT / "tools" / "watch_ats.py"
# Same reasoning as draft_letter.py's own copy of this constant.
CLAUDE_TIMEOUT = 570


def find_claude():
    """Same fix as draft_letter.py's own copy - subprocess.run(["claude", ...])
    fails on Windows without it, because a global npm install's claude.CMD
    shim needs PATHEXT resolution that CreateProcess does not do on its own.
    See draft_letter.py for the full explanation."""
    found = shutil.which("claude")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidate = Path(appdata) / "npm" / "claude.cmd"
        if candidate.exists():
            return str(candidate)
    return None


def load_reports():
    if not LOG.exists():
        return []
    rows = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def save_reports(rows):
    """Whole-file rewrite via a temp file, so a crash cannot truncate the log -
    same pattern as web/server.py's save_pipeline()."""
    tmp = LOG.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) +
                   ("\n" if rows else ""), encoding="utf-8")
    os.replace(str(tmp), str(LOG))


def build_prompt(reports):
    lines = [
        "Read CLAUDE.md in this project root first.",
        "Read profile/watchlist.json's _test_before_adding note and its "
        "search_terms.avoid section.",
        "Read tools/watch_ats.py's NEGATIVE and NEGATIVE_COMPANIES lists "
        "(near the top of the file) and the relevant() function that uses them.",
        "",
        "The following job matches were reported as having nothing to do with "
        "their experience. For each one, decide whether it reveals a real, "
        "generalizable problem in the search terms or the negative filtering "
        "(a term matching the wrong industry, a company in the wrong domain "
        "entirely) versus being a one-off dislike with no generalizable cause "
        "(pay, location, a company they just doesn't want). Only the first kind "
        "gets a fix.",
        "",
    ]
    for r in reports:
        lines.append("- %s | %s | reason: %s" % (
            r.get("company", "?"), r.get("role", "?"), r.get("reason", "")))
    lines += [
        "",
        "Where a fix is warranted, make the smallest correct edit to "
        "profile/watchlist.json's search_terms and/or tools/watch_ats.py's "
        "NEGATIVE or NEGATIVE_COMPANIES lists, commented in the same style "
        "every existing entry in those files already uses - explain what "
        "the report was and why this is the fix, not just what changed.",
        "Do not touch any other file. Do not add a negative company entry "
        "speculatively - only for a company a report actually named.",
        "When done, print a one-paragraph summary of what you changed and why, "
        "or state plainly that nothing warranted a change.",
    ]
    return "\n".join(lines)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the prompt and exit without calling claude")
    args = ap.parse_args()

    all_reports = load_reports()
    batch = [r for r in all_reports if not r.get("reviewed")]
    if not batch:
        print("Nothing unreviewed. Nothing to triage.")
        return 0

    prompt = build_prompt(batch)
    if args.dry_run:
        print(prompt)
        return 0

    claude = find_claude()
    if not claude:
        sys.exit("claude CLI not found or not logged in - see tools/draft_letter.py's "
                  "docstring, same requirement.")

    # Prompt on stdin: a newline ends an argument passed through the Windows
    # claude.CMD shim, so only the first line ever arrived (see draft_letter.py).
    cmd = [claude, "-p", "--restricted",
           "--permission-mode", "acceptEdits", "--output-format", "json"]
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                                 input=prompt, encoding="utf-8", errors="replace",
                                 timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("triage FAILED: claude session did not finish within %ds" % CLAUDE_TIMEOUT)
        return 1

    is_error, summary = False, ""
    try:
        payload = json.loads(result.stdout)
        is_error = bool(payload.get("is_error"))
        summary = payload.get("result") or payload.get("summary") or ""
    except ValueError:
        summary = result.stdout.strip()

    if result.returncode != 0 or is_error:
        print("triage FAILED (exit %d)" % result.returncode)
        print(summary or result.stderr.strip() or "no output from the claude CLI")
        return 1

    print("triage session: %s" % summary[:1000])

    for path, checker in ((WATCHLIST, lambda p: json.loads(p.read_text(encoding="utf-8"))),
                          (WATCH_ATS, lambda p: compile(p.read_text(encoding="utf-8"), str(p), "exec"))):
        try:
            checker(path)
        except (ValueError, SyntaxError) as exc:
            print("WARNING: %s no longer parses after this session: %s" % (path, exc))
            print("Run `git diff %s` and fix or revert before trusting it." % path)
            return 1

    # batch's dicts are the same objects load_reports() put in all_reports, not
    # copies - mutating them directly here means save_reports(all_reports) below
    # picks up the change with no risk of two reports sharing identical fields
    # (a duplicate reason string, say) getting matched by content and confused.
    for r in batch:
        r["reviewed"] = True
    save_reports(all_reports)

    print()
    print("%d report(s) marked reviewed. Nothing committed - run `git diff "
          "profile/watchlist.json tools/watch_ats.py` to see what changed, "
          "if anything." % len(batch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
