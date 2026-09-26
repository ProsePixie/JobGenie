#!/usr/bin/env python3
"""Read and update data/applications.jsonl from the command line.

One line per application, keyed by id (company--role). The web app's board
reads and writes the same file through the same functions, so an entry the
/fit or /outcome skill records here shows up on the board, and stage/outcome
consistency is enforced the same way whichever side made the change.

This exists because the skills used to say "append a line". /fit appended
one, /apply appended another for the same posting, and the board showed two
cards for one application.

Usage
    python3 tools/pipeline.py show
    python3 tools/pipeline.py show --open             only entries not yet closed
    python3 tools/pipeline.py get acme--enablement-manager
    python3 tools/pipeline.py record --company "Acme" --role "Enablement Lead" \\
        --set thread=enablement score=74 verdict=apply stage=scored \\
              'dimensions={"affinity": 80, "capability": 75}'
    python3 tools/pipeline.py record --company "Acme" --role "Enablement Lead" \\
        --set outcome=rejected-auto

`record` creates the entry if it does not exist and updates it if it does.
Values are read as JSON when they parse (numbers, true/false, null, objects)
and as plain strings otherwise.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
import server  # noqa: E402

# Fields the board's add endpoint accepts at creation.
CREATE_KEYS = {"date", "url", "stage", "persona", "thread", "score", "applied", "outcome",
               "next_action", "notes"}


def parse_sets(pairs):
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit("--set expects key=value, got %r" % pair)
        key, _, raw = pair.partition("=")
        key = key.strip()
        if key in ("id", "company", "role"):
            sys.exit("%s is set by --company/--role, not --set" % key)
        try:
            out[key] = json.loads(raw)
        except ValueError:
            out[key] = raw
    return out


def find(entries, entry_id):
    return next((e for e in entries if e["id"] == entry_id), None)


def find_by_name(entries, company, role):
    """Match on company and role, not only on a recomputed id: a stored id is
    frozen at creation, and one written under an older slug rule no longer
    equals what entry_id() computes today."""
    want = server.entry_id({"company": company, "role": role})
    return next((e for e in entries
                 if e["id"] == want or server.entry_id(e) == want), None)


def record(company, role, fields):
    existing = find_by_name(server.load_pipeline(), company, role)
    entry_id = existing["id"] if existing else server.entry_id(
        {"company": company, "role": role})
    created = False
    if not existing:
        body = {"company": company, "role": role}
        body.update({k: v for k, v in fields.items() if k in CREATE_KEYS})
        res = server.api_pipeline_add(body)
        if not res.get("ok"):
            sys.exit(res.get("err") or "could not create the entry")
        created = True

    # A score recorded by a /fit review is a reviewed score: the app's own
    # automatic one (tools/qualify.py) never replaces it.
    if fields.get("score") is not None:
        fields.setdefault("score_source", "fit")

    # Stage and outcome go through the board's own update path, which keeps
    # applied, stage and outcome from contradicting each other.
    patch = {k: v for k, v in fields.items() if k in server.EDITABLE}
    if patch:
        res = server.api_pipeline_update({"id": entry_id, "patch": patch})
        if res and not res.get("ok", True):
            sys.exit(res.get("err") or "update refused")

    # Everything else the skills record (verdict, dimensions, warm_path,
    # evidence_artifact, ...) has no rules attached and is written as given.
    extra = {k: v for k, v in fields.items() if k not in server.EDITABLE}
    if extra:
        with server.PIPELINE_LOCK:
            entries = server.load_pipeline()
            e = find(entries, entry_id)
            e.update(extra)
            e["updated"] = datetime.date.today().isoformat()
            server.save_pipeline(entries)

    return created, find(server.load_pipeline(), entry_id)


def show(open_only):
    entries = server.load_pipeline()
    if open_only:
        entries = [e for e in entries if e.get("stage") != "closed"]
    print("%d entr%s\n" % (len(entries), "y" if len(entries) == 1 else "ies"))
    for e in entries:
        score = e.get("score")
        print("  %-12s %4s  %-16s %s" % (
            e.get("stage", ""), "" if score is None else score,
            (e.get("outcome") or "")[:16], e["id"]))
        if e.get("next_action"):
            print("  %-12s       next: %s" % ("", e["next_action"][:90]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="list entries")
    s.add_argument("--open", action="store_true", help="hide closed entries")

    g = sub.add_parser("get", help="print one entry as JSON")
    g.add_argument("id")

    r = sub.add_parser("record", help="create or update one entry")
    r.add_argument("--company", required=True)
    r.add_argument("--role", required=True)
    r.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")

    args = ap.parse_args()

    if args.cmd == "show":
        show(args.open)
    elif args.cmd == "get":
        e = find(server.load_pipeline(), args.id)
        if not e:
            sys.exit("no entry with id %r. `show` lists them." % args.id)
        print(json.dumps(e, indent=2, ensure_ascii=False))
    else:
        created, e = record(args.company.strip(), args.role.strip(), parse_sets(args.set))
        print("%s %s" % ("created" if created else "updated", e["id"]))
        print(json.dumps(e, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
