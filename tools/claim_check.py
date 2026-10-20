#!/usr/bin/env python3
"""Check a draft against career.json and evidence.json for anything that does not trace.

This is to hard rule 2 what render/ats_check.py is to the text layer and
tools/voice_check.py is to writing-style.md: the rule already exists ("every claim
must trace to career.json, evidence.json, or a fact the user stated"), so it gets
checked mechanically instead of trusted on the honor system - which matters most for
whatever a draft came out of an unattended process, human or AI.

Two kinds of finding.

    FAIL   a specific, known bad claim (something in _do_not_reintroduce), or a
           company name that is not the one this application targets. Refuse to
           send until fixed.
    WARN   a number that does not appear anywhere in career.json or evidence.json.
           Often a phone number, a year used as a date, or a percentage the model
           was allowed to state because it is generic ("100%") rather than invented.
           Read it and decide - this check cannot tell the difference on its own.

Standard library only.

    python3 tools/claim_check.py applications/acme/letter.md --company Acme
    python3 tools/claim_check.py applications/acme/letter.md --company Acme --json
    python3 tools/claim_check.py -  --company Acme          reads stdin
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAREER = ROOT / "profile" / "career.json"
EVIDENCE = ROOT / "profile" / "evidence.json"
WATCHLIST = ROOT / "profile" / "watchlist.json"

# A handful of specific bans that predate this script and are not safe to infer
# generically from _do_not_reintroduce's prose - see career.json for the incident
# behind each one.
KNOWN_BAD_TERMS = ["n8n", "docebo", "adeddie", "addie", "sam model",
                    "champions network", "adoption kpi", "adoption metric",
                    "completion analytics"]

# Years alone are not a fabrication risk - a CV is full of them - so a bare
# 19xx/20xx token is never flagged even though it will not appear verbatim in
# career.json as a standalone number.
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def load_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def banned_phrases():
    """Quoted phrases inside career.json's _do_not_reintroduce, plus the fixed list.

    The registry writes its bans as prose with the exact banned wording in single
    quotes (see 'adoption KPIs and completion analytics' style entries), so pulling
    quotes out of `claim` and `also_appears_as` finds them without hand-copying the
    list a second time and letting the two drift apart.
    """
    career = load_json(CAREER)
    phrases = set(KNOWN_BAD_TERMS)
    for entry in career.get("_do_not_reintroduce", []):
        for field in ("claim", "also_appears_as"):
            for quoted in re.findall(r"'([^']+)'", entry.get(field, "") or ""):
                cleaned = quoted.strip().lower()
                if cleaned:
                    phrases.add(cleaned)
    return sorted(phrases)


def source_text():
    """Every string value in career.json and evidence.json, concatenated.

    Used as the corpus a number has to appear in verbatim to count as traceable.
    Deliberately not parsed into fields - a number in a _calibration note is just
    as valid a source as one in a bullet, and the whole point is not to have to
    keep two lists of "where facts are allowed to live" in sync.
    """
    chunks = []
    for path in (CAREER, EVIDENCE):
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def company_names(exclude):
    """Watchlist companies, minus the target and minus every real past employer.

    A letter naming a past employer (Acme, Globex, ...) is normal - that is
    what a career history is made of. What is not normal is a *prospect* company
    from watchlist.json showing up in a letter aimed at a different one, which is
    the copy-paste-drift failure mode this check exists to catch.

    Known gap, not fixed: an employer can be both a past employer (career.json) and a
    live watchlist target (security-awareness category) at the same time, so it
    is exempted here like any other past employer - a letter for a different
    target company that wrongly names that employer will NOT be caught. Narrowing the
    exemption to close this would make the far more common case (a legitimate
    "I built enablement at Acme" career-history line) fail every time
    instead, which is the worse trade. If this specific company ever causes a
    real mismatch, catch it by hand the way Wayve and Quantum-Systems were
    caught in tools/watch_ats.py, not by weakening this exemption generally.
    """
    watch = load_json(WATCHLIST)
    career = load_json(CAREER)
    target = (exclude or "").strip().lower()
    employers = [(r.get("org") or "").strip().lower() for r in career.get("roles", [])]

    def is_past_employer(name_lower):
        return any(name_lower in org or org.startswith(name_lower)
                   for org in employers if org)

    names = set()
    for cat in watch.get("categories", {}).values():
        for c in cat.get("companies", []):
            name = (c.get("name") or "").strip()
            low = name.lower()
            if name and low != target and not is_past_employer(low):
                names.add(name)
    return names


# Words that raise the scope of a claim without adding a fact: "I was the sole
# contact", "led the rollout", "the entire program". A drafted letter turned
# "serviced computers at eight schools" into "alleiniger Ansprechpartner an acht
# Schulen" (the sole contact at eight schools), and nothing flagged it: no
# number, no banned phrase, no other company. Each is a WARN when it appears
# nowhere in career.json or evidence.json, because then nothing supports it.
SCOPE_WORDS = [
    "sole", "solely", "single-handedly", "entire", "entirely", "every", "led",
    "headed", "managed", "oversaw", "owned", "spearheaded", "pioneered",
    "alleinig", "alleinige", "alleiniger", "alleinigen", "einzige", "einziger",
    "sämtliche", "gesamte", "gesamten", "leitete", "verantwortete", "federführend",
]
SCOPE_RE = re.compile(r"(?<![\w-])(%s)(?![\w-])" % "|".join(re.escape(w) for w in SCOPE_WORDS),
                      re.IGNORECASE)

NUMBER_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?%|\b\d{2,}\b")



# A sentence saying he LACKS something. A letter drafted for a cybersecurity
# trainer role said "SOC and SIEM operations, threat intelligence and ethical
# hacking are not part of my background yet" about a man who had trained on
# Trend Micro Vision One, XDR included (2026-10-05). Nothing in career.json said
# so; the drafter read "not in the data" as "he does not have it". Hard rule 2
# was only ever checked in one direction, so a false denial passed everything.
# Absence from the data is not absence of experience: such a sentence is allowed
# only for a gap he has confirmed (career.json confirmed_gaps).
DENIAL_RES = [re.compile(x, re.I) for x in [
    r"\bnot (?:yet )?(?:a )?(?:part|within|in)\b[^.]{0,12}\bmy (?:background|experience|skill ?set|work)\b",
    r"\b(?:no|little|limited|lack of|without any) (?:prior |direct |formal |hands-on |practical |professional |real |much )?(?:experience|exposure|background|knowledge)\b",
    r"\bI (?:do not|don't|have not|haven't|have never|never|lack)\b[^.]{0,60}\b(?:experience|worked|used|done|held|managed|run|operated)\b",
    r"\bnot yet\b", r"\b(?:still|am) (?:new to|learning|developing)\b",
    r"\boutside (?:of )?my (?:experience|background|expertise)\b",
    # German
    r"\bkeine?[nrms]? (?:direkte[nr]? |praktische[nr]? |formale[nr]? |berufliche[nr]? )?(?:Erfahrung|Kenntnisse|Berufserfahrung)",
    r"\bnicht (?:Teil|Bestandteil) meine[rs]? (?:Erfahrung|Hintergrund|Laufbahn|Werdegang)",
    r"\bnoch nicht\b", r"\bfehlt mir\b", r"\bhabe ich (?:noch )?(?:nicht|nie|keine)\b",
]]
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def confirmed_gap_terms():
    """Lower-case phrases that mark a gap he has confirmed (career.json
    confirmed_gaps[].terms). A sentence naming one may say he lacks it."""
    out = []
    for g in (load_json(CAREER).get("confirmed_gaps") or []):
        out += [str(t).lower() for t in g.get("terms") or []]
    return out


def denials(line):
    """Sentences in a line that state a lack, with the pattern that matched."""
    found = []
    for sentence in SENTENCE_RE.split(line):
        if any(r.search(sentence) for r in DENIAL_RES):
            found.append(sentence.strip())
    return found


COMMENT_BLOCK = re.compile(r"<!--.*?-->", re.S)


def without_comments(text):
    """Blank out <!-- --> blocks, keeping line numbers. A letter scaffold's
    notes (Lead thread, pitch, gap notes) are for the writer and never render, so
    they are not judged: a British spelling in one scaffold's notes once failed
    every letter written for it."""
    return COMMENT_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)

def scan(text, company):
    findings = []
    text = without_comments(text)
    lines = text.splitlines()
    corpus = source_text()
    banned = banned_phrases()
    others = company_names(company)
    gap_terms = confirmed_gap_terms()

    def note(level, rule, i, excerpt):
        findings.append({"level": level, "rule": rule, "line": i,
                         "excerpt": excerpt.strip()[:96]})

    for i, line in enumerate(lines, 1):
        if line.strip().startswith(("<!--", "-->", "#")):
            continue
        low = line.lower()

        if "todo" in low:
            note("FAIL", "literal TODO remains", i, line)

        for phrase in banned:
            if phrase in low:
                note("FAIL", "known bad claim: %r (see _do_not_reintroduce)" % phrase,
                     i, line)

        for name in others:
            # Case-sensitive: a company is named with its capitals. Ignoring case,
            # the watchlist's music company "Output" failed a letter that said
            # "training output".
            if re.search(r"\b%s\b" % re.escape(name), line):
                note("FAIL", "mentions %r, not this application's target company" % name,
                     i, line)

        for m in SCOPE_RE.finditer(line):
            word = m.group(1).lower()
            if not re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(word), corpus, re.IGNORECASE):
                note("WARN", "scope word %r is not in career.json or evidence.json - "
                     "check it is literally true" % m.group(1), i, line)

        for sentence in denials(line):
            if not any(t in sentence.lower() for t in gap_terms):
                note("FAIL", "says he lacks something, and it is not a confirmed gap "
                     "(career.json confirmed_gaps): not being in the data is not the "
                     "same as not having done it", i, sentence)

        for m in NUMBER_RE.finditer(line):
            token = m.group().strip()
            digits = re.sub(r"[^\d]", "", token)
            if YEAR_RE.match(digits):
                continue
            if token not in corpus and digits not in corpus:
                note("WARN", "number %r does not appear in career.json or evidence.json"
                     % token, i, line)

    return findings


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="file to check, or - for stdin")
    ap.add_argument("--company", default="", help="this application's target company")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    if args.path == "-":
        text, label = sys.stdin.read(), "stdin"
    else:
        p = Path(args.path)
        if not p.exists():
            sys.exit("no such file: %s" % p)
        text, label = p.read_text(encoding="utf-8"), str(p)

    findings = scan(text, args.company)

    if args.as_json:
        print(json.dumps({"source": label, "findings": findings}, indent=2,
                         ensure_ascii=False))
        return 1 if any(f["level"] == "FAIL" for f in findings) else 0

    fails = [f for f in findings if f["level"] == "FAIL"]
    warns = [f for f in findings if f["level"] == "WARN"]
    print("claim check: %s\n" % label)
    if not findings:
        print("  Nothing flagged. Every number and name traces, and nothing on the "
              "known-bad list showed up.")
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
