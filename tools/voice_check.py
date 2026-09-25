#!/usr/bin/env python3
"""Check written text against profile/writing-style.md, mechanically.

The style guide has been right all along and unenforced, which is how em dashes
ended up in documents written by the same assistant that wrote the ban. This is
to voice what render/ats_check.py is to the text layer: the rule exists, so the
rule gets checked rather than remembered.

Two kinds of finding.

    FAIL   a rule in writing-style.md, broken. Fix before sending.
    WARN   a tell rather than a rule. Common in generated text and uncommon in
           writing by a person who did the work. Read it and decide.

The banned list is parsed out of writing-style.md itself, so editing the guide
changes the check and the two cannot drift apart.

Standard library only.

    py tools/voice_check.py applications/acme/letter.md
    py tools/voice_check.py --career
    py tools/voice_check.py applications/acme/cv.txt --json
    py tools/voice_check.py -            reads stdin
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE = ROOT / "profile" / "writing-style.md"
CAREER = ROOT / "profile" / "career.json"

# Rules that are not quoted phrases and so cannot be parsed out of the guide.
DASHES = {"—": "em dash", "–": "en dash used as an em dash"}

BRITISH = [
    "organisation", "organise", "programme", "standardise", "localisation",
    "behaviour", "sceptical", "recognise", "analyse", "centre", "specialise",
    "catalogue", "licence", "fibre", "judgement", "cancelled", "modelling",
    "prioritise", "optimise", "utilise", "realise", "colour", "favour",
    "labour", "defence", "practise", "travelled", "learnt",
]

# Not banned by the guide, but heavily overrepresented in generated prose.
# Warnings, not failures, because a few of them are words they might really use.
SMELLS = [
    "delve", "utilize", "utilise", "showcase", "underscore", "pivotal",
    "myriad", "holistic", "comprehensive", "multifaceted", "meticulous",
    "intricate", "nuanced", "landscape", "realm", "journey", "unlock",
    "elevate", "resonate", "foster", "embark", "navigate the", "tapestry",
    "crucial", "vital role", "game-changer", "transformative", "empower",
    "streamline", "in the realm of", "it is worth noting", "that said",
    "furthermore", "moreover", "additionally,", "in conclusion",
    "first and foremost", "when it comes to", "at the end of the day",
    "a wide range of", "a variety of", "plays a key role", "serves as a",
    "stands as a", "not only", "ensuring that", "allowing for",
]

HEDGES = ["i think i", "i believe i", "i may not", "i feel that i",
          "hopefully", "i would love to", "somewhat", "arguably"]


def load_banned():
    """Pull the quoted phrases out of the Banned outright section of the guide."""
    if not STYLE.exists():
        return []
    text = STYLE.read_text(encoding="utf-8")
    block = re.search(r"##\s*Banned outright(.*?)(?=\n##\s|\Z)", text, re.S)
    if not block:
        return []
    phrases = []
    for line in block.group(1).splitlines():
        if not line.strip().startswith("-"):
            continue
        for quoted in re.findall(r"[\"“]([^\"”]+)[\"”]", line):
            cleaned = quoted.strip().lower()
            if cleaned:
                phrases.append(cleaned)
    return sorted(set(phrases))


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


GERMAN_HINTS = (" und ", " der ", " die ", " das ", " für ", " von ", " mit ",
                " im ", " zur ", " des ", " dem ", " einer ", " einem ", " eines ",
                " sowie ", " nach ", " über ", "ungen ", "text_de")


def looks_german(line):
    """Whether to skip the English-only checks on this line.

    Needed because "Organisationen" is correct German and the British spelling
    list flagged it. The em dash rule still applies: German uses them more
    freely than English, which makes it more of a risk there, not less.

    career_text()'s own locators mark a German field explicitly (role[0].
    text_de: ..., skills.x[1].items_de: ...) - trust that over guessing from
    hint words, which a short skills-item phrase can fail with zero of.
    Confirmed: "strukturierte Onboarding-Programme" has no "und"/"der"/etc.
    at all, and was flagged as the British spelling of "program" without
    this. A real letter or CV body never contains the literal text "_de:",
    so this never fires outside career_text()'s own output.
    """
    if "_de:" in line:
        return True
    low = line.lower()
    return sum(1 for hint in GERMAN_HINTS if hint in low) >= 2



COMMENT_BLOCK = re.compile(r"<!--.*?-->", re.S)


def without_comments(text):
    """Blank out <!-- --> blocks, keeping line numbers. A letter scaffold's
    notes (Lead thread, pitch, gap notes) are for the writer and never render, so
    they are not judged: a British spelling in one scaffold's notes once failed
    every letter written for it."""
    return COMMENT_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)

def scan(text, banned):
    findings = []
    text = without_comments(text)
    lines = text.splitlines()

    def note(level, rule, i, excerpt):
        findings.append({"level": level, "rule": rule, "line": i,
                         "excerpt": excerpt.strip()[:96]})

    for i, line in enumerate(lines, 1):
        low = line.lower()
        # Comments in a letter scaffold are instructions to the writer, not the
        # letter, so they are not judged.
        if line.strip().startswith(("<!--", "-->", "#")):
            continue
        for ch, label in DASHES.items():
            if ch in line:
                note("FAIL", label, i, line)
        if looks_german(line):
            continue
        for phrase in banned:
            if phrase in low:
                note("FAIL", "banned: %r" % phrase, i, line)
        for word in BRITISH:
            if re.search(r"\b%s" % re.escape(word), low):
                note("FAIL", "British spelling: %r" % word, i, line)
        for word in SMELLS:
            if word in low:
                note("WARN", "tell: %r" % word, i, line)
        for word in HEDGES:
            if word in low:
                note("WARN", "hedging: %r" % word, i, line)

    # Three bullets in a row opening the same way reads as generated, which the
    # guide says in prose and nothing has ever checked.
    # Frontmatter delimiters start with a dash and are not bullets.
    bullets = [(i, ln) for i, ln in enumerate(lines, 1)
               if ln.strip().startswith(("-", "*", "•"))
               and ln.strip().strip("-*• ")]
    run, prev = [], None
    for i, line in bullets:
        first = re.sub(r"^[-*•]\s*", "", line).split()
        first = first[0].lower().strip(",.:") if first else ""
        if first and first == prev:
            run.append((i, line))
        else:
            run = [(i, line)]
        prev = first
        if len(run) >= 3:
            note("WARN", "three bullets in a row open with %r" % first, i, line)
            run = []

    # Uniform sentence length is the quietest tell of the lot. Real writing is
    # lumpy: a long one, then a short one.
    body = "\n".join(ln for ln in lines if not ln.strip().startswith(("<!--", "-->", "#", "-")))
    lengths = [len(s.split()) for s in sentences(body) if len(s.split()) > 3]
    if len(lengths) >= 5:
        mean = sum(lengths) / len(lengths)
        spread = (sum((n - mean) ** 2 for n in lengths) / len(lengths)) ** 0.5
        if mean and spread / mean < 0.28:
            note("WARN", "sentence lengths are unusually even (mean %.0f, spread %.0f)"
                 % (mean, spread), 0, "vary one of them: a short sentence after a long one")
    return findings


def career_text():
    """Every piece of prose that can render verbatim into an actual document,
    English and German, with a locator.

    Covers: career.json's bullet text, and its skills-cluster items (both
    render straight into the CV body). A thread's vocabulary/avoid word lists
    are not prose and are not scanned here.
    """
    data = json.loads(CAREER.read_text(encoding="utf-8"))
    out = []
    for role in data.get("roles", []):
        for i, bullet in enumerate(role.get("bullets", [])):
            for field in ("text", "text_de"):
                if bullet.get(field):
                    out.append("%s[%d].%s: %s" % (role.get("id"), i, field, bullet[field]))
    for key, cluster in (data.get("skills") or {}).items():
        for field in ("items", "items_de"):
            for i, item in enumerate(cluster.get(field) or []):
                if item:
                    out.append("skills.%s[%d].%s: %s" % (key, i, field, item))
    return "\n".join(out)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="file to check, or - for stdin")
    ap.add_argument("--career", action="store_true",
                    help="check every bullet in career.json instead of a file")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    if args.career:
        text, label = career_text(), "profile/career.json bullets"
    elif args.path == "-":
        text, label = sys.stdin.read(), "stdin"
    elif args.path:
        p = Path(args.path)
        if not p.exists():
            sys.exit("no such file: %s" % p)
        text, label = p.read_text(encoding="utf-8"), str(p)
    else:
        ap.error("give a file, or --career, or - for stdin")

    findings = scan(text, load_banned())
    if args.as_json:
        print(json.dumps({"source": label, "findings": findings}, indent=2,
                         ensure_ascii=False))
        return 1 if any(f["level"] == "FAIL" for f in findings) else 0

    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]
    print("voice check: %s\n" % label)
    if not findings:
        print("  Nothing flagged. It reads as written rather than generated.")
        return 0
    for f in fails + warns:
        where = ("line %d" % f["line"]) if f["line"] else "whole text"
        print("  %-5s %-11s %s" % (f["level"], where, f["rule"]))
        if f["excerpt"]:
            print("        %s" % f["excerpt"])
    print()
    print("%d to fix, %d to consider." % (len(fails), len(warns)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
