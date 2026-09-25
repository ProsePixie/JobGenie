#!/usr/bin/env python3
"""Find people you already know at a target company.

A referral outperforms a stronger cold application, and checking takes
seconds. This runs entirely locally: it reads your LinkedIn connections
export and prints only the handful of rows that match.

That locality is the point. A connections export is personal data about
several hundred other people. Filtering here means only the two or three
relevant names ever enter a conversation, instead of the whole file.

Setup
    Request your data from LinkedIn (Settings > Data privacy > Get a copy
    of your data), then drop Connections.csv into documents/linkedin/.
    That directory is gitignored.

Usage
    py tools/warm_path.py "Acme Systems"
    py tools/warm_path.py "Acme" --min-score 0.5
    py tools/warm_path.py --list-companies
    py tools/warm_path.py --file path/to/Connections.csv "Acme"
"""

import argparse
import csv
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "documents" / "linkedin" / "Connections.csv"

# Suffixes that make two names for the same employer look different.
NOISE = re.compile(
    r"\b(gmbh|ag|inc|inc\.|llc|ltd|ltd\.|limited|corp|corp\.|corporation|"
    r"co|co\.|plc|bv|b\.v\.|nv|sa|s\.a\.|as|a/s|aps|oy|ab|group|holdings?|"
    r"technologies|technology|software|solutions|labs|the)\b", re.I)


def normalise(name):
    cleaned = NOISE.sub(" ", (name or "").lower())
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return " ".join(cleaned.split())


def read_connections(path):
    """LinkedIn prefixes the export with a few notes lines before the header."""
    raw = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    start = 0
    for i, line in enumerate(raw[:15]):
        if line.lower().startswith(("first name", '"first name')):
            start = i
            break
    else:
        sys.exit("could not find a header row in %s\n"
                 "Expected a column named 'First Name'." % path)
    return list(csv.DictReader(raw[start:]))


def score(target, company):
    """0..1 similarity, with substring containment treated as a strong match."""
    t, c = normalise(target), normalise(company)
    if not t or not c:
        return 0.0
    if t == c:
        return 1.0
    # Containment by whole words: "sap" inside "sapient" or "box" inside
    # "dropbox" is a different company, not a 0.9 match.
    tw, cw = t.split(), c.split()
    if any(cw[i:i + len(tw)] == tw for i in range(len(cw) - len(tw) + 1)) or \
            any(tw[i:i + len(cw)] == cw for i in range(len(tw) - len(cw) + 1)):
        return 0.9
    return difflib.SequenceMatcher(None, t, c).ratio()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("company", nargs="?", help="target company name")
    ap.add_argument("--file", help="path to Connections.csv")
    ap.add_argument("--min-score", type=float, default=0.72,
                    help="match threshold 0..1 (default 0.72)")
    ap.add_argument("--list-companies", action="store_true",
                    help="show where your network works, most common first")
    args = ap.parse_args()

    path = Path(args.file) if args.file else DEFAULT
    if not path.exists():
        sys.exit("no connections export at %s\n"
                 "Export from LinkedIn: Settings > Data privacy > Get a copy of "
                 "your data, then place Connections.csv there." % path)

    rows = read_connections(path)
    if not rows:
        sys.exit("no rows parsed from %s" % path)

    if args.list_companies:
        counts = Counter(r.get("Company", "").strip()
                         for r in rows if r.get("Company", "").strip())
        print("%d connections across %d companies\n" % (len(rows), len(counts)))
        for company, n in counts.most_common(40):
            print("  %3d  %s" % (n, company))
        return 0

    if not args.company:
        ap.error("a company name is required (or use --list-companies)")

    matches = []
    for r in rows:
        company = (r.get("Company") or "").strip()
        if not company:
            continue
        s = score(args.company, company)
        if s >= args.min_score:
            matches.append((s, r, company))

    matches.sort(key=lambda m: -m[0])

    if not matches:
        print("No connections found at anything matching %r." % args.company)
        print("Searched %d connections. Try --min-score 0.5 to widen, or "
              "--list-companies to see where your network actually is." % len(rows))
        return 0

    print("%d possible warm path(s) at %r:\n" % (len(matches), args.company))
    for s, r, company in matches:
        name = " ".join(x for x in ((r.get("First Name") or "").strip(),
                                    (r.get("Last Name") or "").strip()) if x)
        position = (r.get("Position") or "").strip()
        since = (r.get("Connected On") or "").strip()
        print("  %-28s %s" % (name, company))
        if position:
            print("  %-28s %s" % ("", position))
        if since:
            print("  %-28s connected %s" % ("", since))
        print()

    print("These are people, not leads. Ask for a conversation before asking")
    print("for a referral, and only where the relationship actually supports it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
