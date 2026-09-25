#!/usr/bin/env python3
"""Mechanical triage of a job posting, before any model reasoning.

Built after a posting titled "AI Enablement Specialist" scored 43 and was
skipped: the title matched a target exactly, and the actual work was bot
configuration and CRM integration. The word "enablement" means enabling
systems in one industry and enabling people in another, and the difference is
invisible in a title.

This runs the checks that do not need judgement, so the model only reasons
about postings that survive them.

Usage
    python3 tools/prescreen.py posting.txt --title "AI Enablement Specialist"
    python3 tools/prescreen.py posting.txt --title "..." --json
    cat posting.txt | python3 tools/prescreen.py - --title "..."
"""

import argparse
import functools
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile"

# Enabling SYSTEMS. Configuration, plumbing, uptime.
OPS_SIGNALS = [
    "configure", "configuration", "integrate", "integration", "api", "apis",
    "crm", "telephony", "webhook", "pipeline", "deploy", "deployment",
    "troubleshoot", "troubleshooting", "monitor", "monitoring", "uptime",
    "workflow automation", "low-code", "no-code", "zapier", "n8n", "make.com",
    "sql", "infrastructure", "provisioning", "ticket", "incident", "sso",
    "middleware", "etl", "backend", "latency", "observability",
]

# Enabling PEOPLE. Curriculum, comprehension, behaviour change.
PEOPLE_SIGNALS = [
    "onboarding", "curriculum", "training", "learner", "learners", "workshop",
    "facilitation", "facilitate", "coaching", "instructional design", "course",
    "courses", "lesson", "certification", "enablement content", "e-learning",
    "elearning", "lms", "teach", "teaching", "educate", "education",
    "storytelling", "narrative", "video production", "script", "voiceover",
    "knowledge base", "documentation", "train-the-trainer", "academy",
    # German. Without these every German posting read as UNCLEAR, including an
    # IT-administrator role that is plainly systems work.
    "schulung", "schulungen", "trainer", "trainerin", "dozent", "dozentin",
    "unterricht", "weiterbildung", "einarbeitung", "lehrgang", "seminar",
    "seminare", "lernende", "teilnehmende", "kursleitung", "wissensvermittlung",
    "beratungsgespräch", "beratungsgespräche", "kundenberatung", "dokumentation",
    "anleitung", "erklären",
]

OPS_SIGNALS += [
    "konfiguration", "installation", "administration", "wartung", "fehlerbehebung",
    "netzwerk", "netzwerke", "server", "störung", "störungen", "schnittstelle",
    "schnittstellen", "datenbank", "programmierung", "rollout", "rollouts",
    "systemadministration", "firewall", "firewalls", "verkabelung",
]

# Places the candidate already is, from profile/market.json home_places and
# wide_regions. A "must be based in" naming one of these describes them, not a gate.
def _market():
    try:
        return json.loads((ROOT / "profile" / "market.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


MARKET = _market()
HOME = "|".join(re.escape(str(x).lower()) for x in
                (MARKET.get("home_places") or []) + (MARKET.get("wide_regions") or [])) or "(?!x)x"


def language_gate(names):
    """A requirement for one language at a level the user does not have in writing."""
    n = "|".join(re.escape(x.lower()) for x in names)
    level = (r"fluent|native|professional|business|verhandlungssicher|flie(?:ß|ss)end|"
             r"muttersprachlich|courant|fluido|nativo|c1|c2")
    return re.compile(
        r"(%s)[-\s]+(level\s+)?(proficiency\s+)?(in\s+)?(written\s+)?(\w+\s+(and|&|und)\s+)?(%s)\b|"
        r"\b(%s)\w*[^.\n]{0,40}?\b(%s|must|required|essential|mandatory)\b" % (level, n, n, level), re.I)


# A requirement that is immediately softened is not a requirement. Checked on
# the text around a match, within the same sentence.
SOFTENED = re.compile(
    r"\b(a\s+)?(plus|bonus|advantage|nice[-\s]to[-\s]have|beneficial|preferred|"
    r"desirable|optional)\b|von\s+vorteil|w(ü|ue)nschenswert|ein\s+plus", re.I)

# A language the user lists in market.json language_gates, e.g.
# {"language": "German", "names": ["german", "deutsch"], "note": "Spoken is fine; written is not"}.
LANGUAGE_GATES = [("language_required", language_gate(g.get("names") or [g["language"]]),
                   "Requires %s. %s" % (g["language"], g.get("note", "")), True)
                  for g in MARKET.get("language_gates") or [] if g.get("language")]

GATES = LANGUAGE_GATES + [
    # A bare "relocat" matched "relocation package offered", which is a benefit,
    # and "must be based in <home town>" was treated as a gate for someone living there.
    ("relocation", re.compile(
        r"(must|willing\s+to|required\s+to|need\s+to|expected\s+to)\s+relocate|"
        r"relocation\s+(is\s+)?(required|mandatory|necessary)|"
        r"on-?site\s+(only|required)|"
        r"must\s+(be\s+)?(based|located|live)\s+in\s+(?!(%s)\b)" % HOME, re.I),
     "May require relocation or fixed onsite presence.",
     False),
    ("contract_not_employment", re.compile(
        r"consulting\s+(opportunity|engagement)|freelance|contractor|b2b\s+contract|"
        r"self-?employed|independent\s+contractor|fixed-?term|"
        # German, which this gate never read: fixed-term, freelance, fee basis.
        # Adult-education fee-basis roles (Honorarkraft) slipped through.
        r"\bbefristet|freiberuflich|freie[rn]?\s+mitarbeit|honorar(basis|kraft|vertrag)|"
        r"auf\s+honorarbasis|werkvertrag", re.I),
     "Contract or consulting, not employment. Different income, tax and benefits "
     "profile; if you receive unemployment benefits, check how self-employed hours affect them.",
     False),
    ("undisclosed_employer", re.compile(
        r"on\s+behalf\s+of\s+(a|our)\s+(partner|client)|our\s+partner\s+is\s+looking|"
        r"confidential\s+client|client\s+company|unnamed\s+(client|employer)", re.I),
     "Employer undisclosed. No dossier, no warm path, no company research possible.",
     False),
    ("clearance_or_citizenship", re.compile(
        r"security\s+clearance|must\s+be\s+a\s+citizen|citizenship\s+required|"
        r"eu\s+citizenship\s+required", re.I),
     "Clearance or citizenship gate. Verify before investing.",
     False),
    ("ai_screened", re.compile(
        r"ai-?powered\s+match|automated\s+(screening|matching)|algorithmic\s+screen", re.I),
     "Application is machine-screened first. Keyword coverage matters more than prose.",
     False),
    ("commodity_role", re.compile(
        r"no\s+(prior\s+)?[\w,\s]{0,30}?experience\s+(is\s+)?(required|necessary|needed)|"
        r"open\s+to\s+.{0,20}from\s+any\s+background|entry[-\s]level|"
        r"no\s+experience\s+necessary", re.I),
     "Advertised as requiring no experience. Twenty-five years is priced at zero and "
     "paid the same as zero.",
     False),
]


def sentence_around(text, m):
    """The clause a match sits in: back to the last full stop or line break
    before it, forward to the next one after it."""
    start = max(text.rfind(c, 0, m.start()) for c in ".;\n") + 1
    ends = [i for i in (text.find(c, m.end()) for c in ".;\n") if i != -1]
    return text[start:min(ends) if ends else len(text)]


def gate_match(text, rx, softenable):
    """First match that is a real requirement, or None."""
    for m in rx.finditer(text):
        if softenable and SOFTENED.search(sentence_around(text, m)):
            continue
        return m
    return None


@functools.lru_cache(maxsize=None)
def term_pattern(term):
    """Whole words only, case-insensitive; a plural and space/hyphen spellings count.

    Plain substring tests read "api" in "rapidly", "script" in "description",
    "sso" in "associate", "lms" in "LLMs" and "go" in "going" - so a systems
    posting could read as people work, and a keyword the CV does not carry
    could be reported as covered.

    Short terms written with capitals ("Go", "R", "AI") match case-sensitively,
    and short terms take a plain "s" plural only, or the language Go is found
    in "what goes wrong".
    """
    term = term.strip()
    short = len(term) <= 3
    exact = short and any(c.isupper() for c in term)
    parts = [re.escape(p) for p in re.split(r"[\s-]+", term if exact else term.lower()) if p]
    plural = "s?" if short else "(?:s|es)?"
    return re.compile(r"(?<![A-Za-z0-9])%s%s(?![A-Za-z0-9])"
                      % (r"[\s-]?".join(parts), plural), 0 if exact else re.I)


def has_term(term, text):
    return bool(term and term_pattern(term).search(text))


def profile_text():
    """Every value in career.json, meta notes removed, as one string.

    Case is kept so a capitalized short keyword ("Go") can be told apart from
    the ordinary word; has_term ignores case for everything else.

    Underscore keys (_doc, _needs, _do_not_reintroduce) hold notes about what
    is NOT established. Left in, a keyword looks supported when its only
    mention is a note saying it is unconfirmed or fabricated, which turns a
    genuine gap into "missing (have it)" and invites putting it back.

    Values only. A json.dumps of the whole file also carried the key names, so
    a posting that asked for "tags", "text" or "strength" matched the schema.
    """
    out = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            out.append(node)

    walk(strip_meta(load("career.json")))
    return "\n".join(out)


def load(name):
    return json.loads((PROFILE / name).read_text(encoding="utf-8"))


def strip_meta(node):
    if isinstance(node, dict):
        return {k: strip_meta(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [strip_meta(v) for v in node]
    return node


def count_signals(text, signals):
    return [s for s in signals if has_term(s, text)]


def vocab_scores(text, threads, field):
    """Score each thread by how many of its terms appear in `text`."""
    out = {}
    for p in threads:
        terms = [t.lower() for t in p.get(field, [])]
        hits = [t for t in terms if has_term(t, text)]
        out[p["id"]] = (len(hits), hits)
    return out


TITLE_NOISE = {"senior", "junior", "lead", "specialist", "manager", "head", "of",
               "and", "the", "a", "principal", "staff", "associate", "director",
               "m", "f", "d", "w", "x"}


def title_scores(title, threads):
    """Match titles by word overlap, not exact string.

    'AI Enablement Specialist' must match a thread targeting 'AI Enablement
    Lead'. Requiring the whole phrase meant the first real posting slipped
    through the trap detector this file exists to run.
    """
    words = {w for w in re.findall(r"[a-z0-9+]+", title.lower())
             if w not in TITLE_NOISE}
    out = {}
    for p in threads:
        best, matched = 0.0, ""
        for target in p.get("targets", []):
            tw = {w for w in re.findall(r"[a-z0-9+]+", target.lower())
                  if w not in TITLE_NOISE}
            if not tw:
                continue
            overlap = len(words & tw) / len(tw)
            if overlap > best:
                best, matched = overlap, target
        out[p["id"]] = (round(best, 2), matched)
    return out


# [\s#*_-]* before the word, not just \s*: a posting converted from HTML to
# text commonly leaves headers as "**Requirements**", "## Requirements" or
# "- Requirements:", none of which matched a bare-whitespace anchor. That
# silently fell through to the block.strip() or text fallback below,
# scanning the entire posting - which is exactly the "Join"/"way" noise this
# function's own docstring says scoping exists to prevent.
SECTION_START = re.compile(
    r"^[\s#*_-]*(requirements|qualifications|what you.{0,3}ll need|what you bring|"
    r"you have|about you|who you are|your profile|skills|must have|"
    r"what we.{0,3}re looking for|nice to have|preferred)\b", re.I)
SECTION_END = re.compile(
    r"^[\s#*_-]*(benefits|we offer|what we offer|perks|about (us|the company)|"
    r"how .{0,20} works|compensation|our offer|why join|why work|"
    r"what you.{0,3}ll do|what you will do|responsibilities)\b", re.I)

# Domain nouns that matter even when lowercase.
TECH_LEXICON = [
    "api", "apis", "crm", "llm", "saas", "telephony", "webhook", "sql", "python",
    "javascript", "salesforce", "hubspot", "zendesk", "workday", "kubernetes",
    "docker", "aws", "azure", "gcp", "terraform", "zapier", "n8n", "airtable",
    "looker", "tableau", "powerbi", "figma", "jira", "confluence", "notion",
    "articulate", "captivate", "camtasia", "storyline", "docebo", "seismic",
    "highspot", "scorm", "xapi", "lms", "cms", "sso", "saml", "oauth", "rest",
    "graphql", "ci/cd", "git", "linux", "react", "typescript", "node",
]


def extract_requirement_gaps(text, corpus):
    """Terms from the requirements section that the profile does not support.

    Scoped to the requirements block and restricted to acronyms, proper nouns
    and known domain terms. Scanning whole prose returned words like 'Join'
    and 'way', which is noise dressed as a finding.
    """
    lines, inside = [], False
    for line in text.splitlines():
        if SECTION_START.search(line):
            inside = True
            continue
        if inside and SECTION_END.search(line):
            break
        if inside and line.strip():
            lines.append(line.strip())
    block = "\n".join(lines) or text

    found = []
    for line in block.splitlines():
        tokens = re.findall(r"\b([A-Za-z][A-Za-z0-9+./#-]{1,20})\b", line)
        for i, token in enumerate(tokens):
            low = token.lower()
            is_acronym = token.isupper() and 2 <= len(token) <= 5
            is_proper = token[0].isupper() and not token.isupper() and len(token) > 3
            in_lexicon = low in TECH_LEXICON
            # A capital at the start of a bullet means nothing. Postings put one
            # requirement per line, so position 0 was returning "Naturally",
            # "Experienced" and "Skilled" as if they were technologies.
            if i == 0 and not (is_acronym or in_lexicon):
                continue
            if not (is_acronym or is_proper or in_lexicon):
                continue
            if low in TITLE_NOISE or low in GENERIC or has_term(low, corpus):
                continue
            if token not in found:
                found.append(token)
    return found


# Capitalised English that is never a skill.
GENERIC = {
    "experience", "experienced", "strong", "solid", "excellent", "previous",
    "hands", "proactive", "comfortable", "ability", "years", "familiarity",
    "familiar", "background", "naturally", "skilled", "understands", "thrives",
    "basic", "make", "nice", "have", "preferred", "plus", "ideally", "also",
    "including", "such", "other", "using", "within", "across", "german",
    "english", "business", "fluent", "working", "team", "teams", "role",
}


def screen(text, title=""):
    """Run every mechanical check and return the result as a dict.

    Callable so batch_screen.py can screen a hundred postings without a model
    reading any of them.
    """
    title = title or text.strip().splitlines()[0][:120]
    # Scored against the CV builder's threads (profile/threads.json), which
    # replaced the personas at the switch-over; same targets and vocabulary.
    threads = load("threads.json")["threads"]
    corpus = profile_text()

    # ---- gates ----
    gates = []
    for key, rx, note, softenable in GATES:
        m = gate_match(text, rx, softenable)
        if m:
            gates.append({"gate": key, "matched": m.group(0)[:60].strip(), "note": note})

    # ---- beware the title ----
    by_title = title_scores(title, threads)
    by_body = vocab_scores(text, threads, "vocabulary")
    title_best = max(by_title.items(), key=lambda kv: kv[1][0])
    body_best = max(by_body.items(), key=lambda kv: kv[1][0])

    ops = count_signals(text, OPS_SIGNALS)
    people = count_signals(text, PEOPLE_SIGNALS)
    total = len(ops) + len(people)
    people_share = (len(people) / total) if total else 0.0

    # A ratio built from two or three hits is noise. An annotation gig scored
    # 100% "people" off the words "training" and "teach", which is how a
    # commodity piecework listing outranked a real enablement role.
    if total < 5:
        orientation = "UNCLEAR - too few signals to judge from the text."
    elif people_share >= 0.6:
        orientation = "PEOPLE - enabling humans. Your territory."
    elif people_share <= 0.35:
        orientation = "SYSTEMS - enabling machines. Configuration and plumbing."
    else:
        orientation = "MIXED - read the accountabilities line by line."

    # Same noise floor as orientation just above, and for the same reason:
    # title_trap used to trust people_share on its own, so a short posting
    # with two or three signal hits could flag TITLE TRAP off statistical
    # noise the comment above already warns against trusting for orientation.
    title_trap = (total >= 5 and title_best[1][0] >= 0.4 and people_share <= 0.35
                  and any(t in title.lower() for t in
                          ("enablement", "education", "learning", "training",
                           "content", "curriculum", "instructional")))

    gaps = extract_requirement_gaps(text, corpus)

    result = {
        "title": title,
        "gates_triggered": gates,
        "orientation": orientation,
        "people_share": round(people_share, 2),
        "ops_signals": ops[:14],
        "people_signals": people[:14],
        "thread_by_title": {"id": title_best[0], "overlap": title_best[1][0],
                            "closest_target": title_best[1][1]},
        "thread_by_body": {"id": body_best[0], "hits": body_best[1][1][:10]},
        "title_trap": title_trap,
        "requirement_terms_not_in_profile": gaps[:18],
    }
    result.update(thread_view(text, title))
    return result


def thread_view(text, title):
    """The CV builder's view of the posting: base and Lead thread, the same
    scoring the Build panel's suggestion uses (plans/cv-builder.md, 3.1)."""
    import cv_suggest  # noqa: E402  sits beside this file; imports us lazily
    tdoc = load("threads.json")
    base, base_scores = cv_suggest.suggest_base(tdoc, title, text)
    rows = []
    for t in tdoc["threads"]:
        score, matched = cv_suggest.score_thread(t, title, text)
        rows.append({"id": t["id"], "base": t["base"], "score": score, "matched": matched[:5]})
    own = sorted([r for r in rows if r["base"] == base], key=lambda r: -r["score"])
    return {"base": base, "base_scores": base_scores,
            "lead_thread": own[0]["id"] if own else None,
            "thread_scores": {r["id"]: r["score"] for r in rows},
            "thread_matches": {r["id"]: r["matched"] for r in rows if r["matched"]}}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("posting", help="path to the posting text, or - for stdin")
    ap.add_argument("--title", default="", help="the job title as advertised")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    text = (sys.stdin.read() if args.posting == "-"
            else Path(args.posting).read_text(encoding="utf-8", errors="replace"))
    result = screen(text, args.title)

    title = result["title"]
    gates = result["gates_triggered"]
    orientation = result["orientation"]
    ops = result["ops_signals"]
    people = result["people_signals"]
    title_best = (result["thread_by_title"]["id"],
                  (result["thread_by_title"]["overlap"],
                   result["thread_by_title"]["closest_target"]))
    body_best = (result["thread_by_body"]["id"],
                 (len(result["thread_by_body"]["hits"]), None))
    title_trap = result["title_trap"]
    gaps = result["requirement_terms_not_in_profile"]

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print("posting: %s\n" % title)
    if gates:
        print("GATES TRIGGERED")
        for g in gates:
            print("  %-26s %r" % (g["gate"], g["matched"]))
            print("  %-26s %s" % ("", g["note"]))
        print()
    else:
        print("gates: none triggered\n")

    print("orientation: %s" % orientation)
    print("  people signals %2d  %s" % (len(people), ", ".join(people[:10])))
    print("  ops signals    %2d  %s" % (len(ops), ", ".join(ops[:10])))
    print()
    print("thread by title:  %-16s (%.0f%% overlap with %r)"
          % (title_best[0], title_best[1][0] * 100, title_best[1][1]))
    print("thread by body:   %-16s (%d vocabulary hits)"
          % (body_best[0], body_best[1][0]))
    print("builder:          %s base, Lead %s   (%s)"
          % (result["base"], result["lead_thread"],
             ", ".join("%s %d" % (k, v) for k, v in sorted(result["thread_scores"].items(),
                                                           key=lambda kv: -kv[1]) if v)))

    if title_trap:
        print()
        print("  *** TITLE TRAP ***")
        print("  The title reads as a learning or enablement role, but the body is")
        print("  systems work. This is the shape of a deep product-specialist role")
        print("  in disguise. Read the accountabilities before believing")
        print("  the title.")

    if gaps:
        print("\nrequirement terms absent from your profile:")
        print("  " + ", ".join(gaps[:18]))
        print("  (mechanical - some are noise. Genuine absences are gaps, not")
        print("   things to invent.)")

    print("\nTriage only. Run /fit for the scored verdict.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
