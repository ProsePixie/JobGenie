#!/usr/bin/env python3
"""Check that nothing from the private tier has reached a generated file.

CLAUDE.md hard rule 1 keeps profile/private/ out of every prompt, and so out
of every document. This enforces the second half mechanically. It reads the
private tier locally and scans outputs for anything from it:

    terms      every line of profile/private/leak-terms.txt: reference names,
               a salary number, an address, anything that must never appear
    emails     any email address found in the private files
    phones     any phone number (8+ digits) found in the private files
    amounts    any money-like number (1,000 or more, "65.000", "65k") found in
               the private files; years are ignored

Findings name the file, the line, and the category, and NEVER the matched
text: the output of this script may be read by a model, so it must not
carry what it protects. Do not change it to print matches.

leak-terms.txt is written by the user, one term per line. Lines starting
with # are comments. A line starting with ! allows a value that is public
by decision (e.g. !70000 if the public target band equals a private figure).

README.md and .gitkeep in the private folder are documentation and skipped.
PDFs and other binary files there are not parsed; list anything in them
that must not leak in leak-terms.txt.

Usage
    python3 tools/leak_check.py                         scan applications/, build/, data/, profile/
    python3 tools/leak_check.py applications/acme       scan one package

Exit status 1 when anything is found.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "profile" / "private"
DEFAULT_TARGETS = ["applications", "build", "data", "profile"]
TEXT_SUFFIXES = {".md", ".txt", ".html", ".json", ".jsonl", ".csv"}
SKIP_NAMES = {"README.md", ".gitkeep"}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d \t().\-/]{6,}\d")
AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d{4,})(?:\s?(k|tsd\.?|tausend))?(?![\d])",
                       re.I)


def _amounts(text):
    out = set()
    for m in AMOUNT_RE.finditer(text):
        digits = re.sub(r"[.,]", "", m.group(1))
        value = int(digits)
        if m.group(2):
            value *= 1000
        if 1950 <= value <= 2035 and not m.group(2) and len(m.group(1)) == 4:
            continue          # a year, not an amount
        if value >= 1000:
            out.add(value)
    for m in re.finditer(r"(?<![\d.,])(\d{2,3})\s?(k|tsd\.?)(?![a-z])", text, re.I):
        out.add(int(m.group(1)) * 1000)
    return out


def _digits(s):
    return re.sub(r"\D", "", s)


def _phone_key(number):
    """The trailing digits, so +49 170 ... and 0170 ... are the same number."""
    d = _digits(number)
    return d[-9:] if len(d) >= 10 else d


def _emails(text):
    return {e.rstrip(".").lower() for e in EMAIL_RE.findall(text)}


def load_secrets(private=PRIVATE):
    """What must not leak, gathered locally. Never returned to a caller that prints."""
    secrets = {"terms": [], "emails": set(), "phones": set(), "amounts": set(), "allowed": set()}
    if not private.exists():
        return secrets, 0
    unparsed = 0
    for path in sorted(private.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        if path.name == "leak-terms.txt":
            for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("!"):
                    secrets["allowed"].add(line[1:].strip().lower())
                else:
                    secrets["terms"].append(line)
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            unparsed += 1
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        secrets["emails"].update(_emails(text))
        secrets["phones"].update(k for k in (_phone_key(p) for p in PHONE_RE.findall(text))
                                 if len(k) >= 8)
        # Phone numbers first, so their digit groups are not read as amounts.
        secrets["amounts"].update(_amounts(PHONE_RE.sub(" ", text)))
    allowed = secrets["allowed"]
    secrets["terms"] = [t for t in secrets["terms"] if t.lower() not in allowed]
    secrets["emails"] -= allowed
    secrets["amounts"] = {a for a in secrets["amounts"] if str(a) not in allowed}
    secrets["phones"] = {p for p in secrets["phones"] if p not in allowed}
    return secrets, unparsed


def scan_text(text, secrets):
    """[(line_number, category)]: where something private appears. No content."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        for i, term in enumerate(secrets["terms"], 1):
            if term.lower() in low:
                hits.append((n, "leak-terms.txt line %d" % i))
        if any(e in low for e in secrets["emails"]):
            hits.append((n, "email from the private tier"))
        squashed = _digits(line)
        if squashed and any(p in squashed for p in secrets["phones"]):
            hits.append((n, "phone number from the private tier"))
        if secrets["amounts"] and _amounts(PHONE_RE.sub(" ", line)) & secrets["amounts"]:
            hits.append((n, "amount from the private tier"))
    return hits


def scan(targets, secrets, private=PRIVATE):
    findings = []
    for target in targets:
        paths = [target] if target.is_file() else sorted(target.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                path.resolve().relative_to(private.resolve())
                continue          # the private tier itself is not a leak
            except ValueError:
                pass
            text = path.read_text(encoding="utf-8", errors="replace")
            findings += [(path, n, cat) for n, cat in scan_text(text, secrets)]
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="files or folders (default: the whole working tree)")
    ap.add_argument("--private", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    private = Path(args.private) if args.private else PRIVATE
    secrets, unparsed = load_secrets(private)
    count = len(secrets["terms"]) + len(secrets["emails"]) + len(secrets["phones"]) \
        + len(secrets["amounts"])
    if not count:
        print("leak check: nothing to check against. Add the values that must never appear "
              "to profile/private/leak-terms.txt (one per line).")
        return 0

    targets = [Path(p) if Path(p).is_absolute() else ROOT / p
               for p in (args.paths or DEFAULT_TARGETS)]
    findings = scan([t for t in targets if t.exists()], secrets, private)
    note = " (%d binary file(s) in the private tier not parsed)" % unparsed if unparsed else ""
    if not findings:
        print("leak check: clean, %d protected value(s)%s" % (count, note))
        return 0
    for path, n, cat in findings:
        shown = path.relative_to(ROOT) if str(path).startswith(str(ROOT)) else path
        print("LEAK  %s:%d  %s" % (shown, n, cat))
    print("\n%d finding(s). Remove the value from that file, or from the data it was "
          "rendered from, and re-render. Do not open the private tier to compare." % len(findings))
    return 1


if __name__ == "__main__":
    sys.exit(main())
