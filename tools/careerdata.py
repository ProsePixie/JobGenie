#!/usr/bin/env python3
"""Write facts into profile/career.json safely, and record where each came from.

CLAUDE.md hard rule 2: a fact the user confirms is written into career.json
in the same turn. This is how a session does that without hand-editing JSON,
with the same checks the Career editor applies (the blocked-claims list, the
writing-style rules, known thread ids), and with every change
recorded in profile/sources.jsonl: what changed, from what, to what, when,
and on whose word. The web editor's saves are recorded there too, through
web/server.save_json_atomic, so the file answers "where did this line come
from?" for every edit made after 2026-09-24.

Paths are dotted, and a list is indexed by its entries' `id`:

    identity.phone      roles.mimecast.end      certifications.aws-cp.year

    py tools/careerdata.py get roles.mimecast.end
    py tools/careerdata.py set roles.mimecast.end 2024-01 --source "user, in chat"
    py tools/careerdata.py add-bullet mimecast --text "Built ..." --threads enablement \\
        --tags onboarding --strength 3 --source "user, in chat"
    py tools/careerdata.py history roles.mimecast

Values given to `set` are read as JSON when they parse (2021, true, ["a"])
and as plain text otherwise.
"""

import argparse
import copy
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAREER = ROOT / "profile" / "career.json"
SOURCES = ROOT / "profile" / "sources.jsonl"


# --------------------------------------------------------------------------
# paths and diffs
# --------------------------------------------------------------------------

def _step(node, seg):
    if isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and item.get("id") == seg:
                return item
        raise KeyError(seg)
    return node[seg]


def get(data, dotted):
    for seg in dotted.split("."):
        data = _step(data, seg)
    return data


def set_in(data, dotted, value):
    *parents, last = dotted.split(".")
    node = data
    for seg in parents:
        node = _step(node, seg)
    if isinstance(node, list):
        for i, item in enumerate(node):
            if isinstance(item, dict) and item.get("id") == last:
                node[i] = value
                return
        raise KeyError(last)
    if not isinstance(node, dict):
        raise KeyError(dotted)
    node[last] = value


def _keyed(items):
    if items and all(isinstance(i, dict) and i.get("id") for i in items):
        return {i["id"]: i for i in items}
    return None


def diff(old, new, path=""):
    """[(dotted path, old, new)] for every leaf that differs. Lists of entries
    with ids are compared by id, so adding a role reads as one change, not
    every later index shifting."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in list(old) + [k for k in new if k not in old]:
            sub = "%s.%s" % (path, k) if path else k
            if k not in new:
                out.append((sub, old[k], None))
            elif k not in old:
                out.append((sub, None, new[k]))
            else:
                out += diff(old[k], new[k], sub)
        return out
    if isinstance(old, list) and isinstance(new, list):
        ko, kn = _keyed(old), _keyed(new)
        if ko is not None and kn is not None:
            return diff(ko, kn, path)
    return [] if old == new else [(path, old, new)]


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def record(changes, source, sources=SOURCES):
    if not changes:
        return
    sources.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with sources.open("a", encoding="utf-8", newline="\n") as fh:
        for path, old, new in changes:
            fh.write(json.dumps({"date": stamp, "path": path, "old": old, "new": new,
                                 "source": source}, ensure_ascii=False) + "\n")


def save(data, source, path=CAREER, sources=None):
    """Write career.json atomically, in the file's own format, and record the
    change. Returns the list of changes."""
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    changes = diff(old, data)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
    record(changes, source, sources or path.parent / SOURCES.name)
    return changes


def vet(texts, threads=()):
    """The Career editor's own checks, so the CLI cannot write what the UI refuses."""
    sys.path.insert(0, str(ROOT / "web"))
    import server  # noqa: E402
    problem = server.vet_career_text(*[t for t in texts if isinstance(t, str)])
    if problem:
        return problem
    known = {t["id"] for t in server.load_json(server.PROFILE / "threads.json", {})
             .get("threads", [])}
    bad = [t for t in threads if t not in known]
    if bad:
        return "unknown thread id(s): %s" % ", ".join(bad)
    return None


def parse_value(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="command", required=True)
    g = sub.add_parser("get")
    g.add_argument("path")
    s = sub.add_parser("set")
    s.add_argument("path")
    s.add_argument("value")
    s.add_argument("--source", required=True, help='e.g. "user, in chat"')
    b = sub.add_parser("add-bullet")
    b.add_argument("role")
    b.add_argument("--text", required=True)
    b.add_argument("--text-de", default="")
    b.add_argument("--threads", default="", help="comma-separated thread ids")
    b.add_argument("--tags", default="")
    b.add_argument("--strength", type=int, default=2, choices=(1, 2, 3))
    b.add_argument("--source", required=True)
    h = sub.add_parser("history")
    h.add_argument("prefix", nargs="?", default="")
    args = ap.parse_args(argv)

    path = Path(args.file) if args.file else CAREER
    data = json.loads(path.read_text(encoding="utf-8"))
    split = lambda raw: [x.strip() for x in raw.split(",") if x.strip()]  # noqa: E731

    if args.command == "get":
        try:
            print(json.dumps(get(data, args.path), indent=2, ensure_ascii=False))
        except (KeyError, TypeError):
            sys.exit("no value at %s" % args.path)
        return 0

    if args.command == "history":
        src = path.parent / SOURCES.name
        rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines()
                if l.strip()] if src.exists() else []
        rows = [r for r in rows if r["path"].startswith(args.prefix)]
        for r in rows:
            print("%s  %-40s %s  (%s)" % (r["date"][:10], r["path"][:40],
                                         json.dumps(r["new"], ensure_ascii=False)[:60], r["source"]))
        if not rows:
            print("no recorded changes%s" % (" under " + args.prefix if args.prefix else ""))
        return 0

    new = copy.deepcopy(data)
    if args.command == "set":
        value = parse_value(args.value)
        problem = vet([value] if isinstance(value, str) else [])
        if problem:
            sys.exit(problem)
        try:
            set_in(new, args.path, value)
        except (KeyError, TypeError):
            sys.exit("no such place to write: %s (lists are indexed by entry id)" % args.path)
    else:
        try:
            role = get(new, "roles." + args.role)
        except KeyError:
            sys.exit("no role %r" % args.role)
        threads = split(args.threads)
        if not threads:
            sys.exit("--threads is required: a bullet no thread claims never renders")
        problem = vet([args.text, args.text_de], threads)
        if problem:
            sys.exit(problem)
        bullets = role.setdefault("bullets", [])
        taken = {x.get("id") for x in bullets}
        n = len(bullets) + 1
        while "%s-%d" % (args.role, n) in taken:
            n += 1
        bullet = {"id": "%s-%d" % (args.role, n), "threads": threads, "text": args.text.strip(),
                  "strength": args.strength, "tags": split(args.tags)}
        if args.text_de.strip():
            bullet["text_de"] = args.text_de.strip()
        bullets.append(bullet)

    changes = save(new, args.source, path)
    for p, old, value in changes:
        print("%s: %s -> %s" % (p, json.dumps(old, ensure_ascii=False)[:60],
                                json.dumps(value, ensure_ascii=False)[:60]))
    if not changes:
        print("no change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
