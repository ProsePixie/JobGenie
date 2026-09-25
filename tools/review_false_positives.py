#!/usr/bin/env python3
"""List what "Report as wrong" in the app has logged, for turning into an actual fix.

Reporting a bad match closes it out of the pipeline immediately, but that alone
does not change the search terms - a report is a data point, not a fix. This is
the tool that reads the accumulated data points. Nothing here edits
watch_ats.py's NEGATIVE list or watchlist.json's search_terms automatically:
every fix this project has made from a reported mismatch (Forward Deployed
Engineer, Wayve, Quantum-Systems) required looking at what the report actually
said and deciding what to change, and that stays a deliberate step - see
_test_before_adding in watchlist.json for exactly why nothing here should be
auto-applied.

    python3 tools/review_false_positives.py                 unreviewed reports
    python3 tools/review_false_positives.py --all            everything ever reported
    python3 tools/review_false_positives.py --mark-reviewed  clear the unreviewed flag
                                                         on everything currently shown
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "false-positives.jsonl"


def load():
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


def save(rows):
    """Whole-file rewrite via a temp file, so a crash cannot truncate the log -
    same pattern as web/server.py's save_pipeline()."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOG.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) +
                   ("\n" if rows else ""), encoding="utf-8")
    os.replace(str(tmp), str(LOG))


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="show reviewed reports too")
    ap.add_argument("--mark-reviewed", action="store_true",
                    help="mark everything currently shown as reviewed")
    args = ap.parse_args()

    rows = load()
    if not rows:
        print("Nothing reported yet.")
        return 0

    shown = rows if args.all else [r for r in rows if not r.get("reviewed")]
    if not shown:
        print("Nothing unreviewed. Pass --all to see everything ever reported.")
        return 0

    for r in shown:
        print("%-11s %-28s %-40s %s" % (r.get("date", ""), (r.get("company") or "")[:28],
                                        (r.get("role") or "")[:40], r.get("reason", "")))
        if r.get("url"):
            print("            %s" % r["url"])

    print()
    print("%d report(s) shown." % len(shown))

    if args.mark_reviewed:
        shown_ids = {id(r) for r in shown}
        for r in rows:
            if id(r) in shown_ids:
                r["reviewed"] = True
        save(rows)
        print("Marked reviewed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
