#!/usr/bin/env python3
"""Suggest a CV setup for a posting: base, language, dials with reasons, headline,
and the posting's requirements marked covered, available or gap.

Instant and free: word matching against profile/threads.json and career.json,
no model call. The AI refinement (Analyze fit) is a separate, optional step.
See plans/cv-builder.md, step 1.4.

    py tools/cv_suggest.py posting.txt --title "Customer Success Manager"
    py tools/cv_suggest.py posting.txt --json
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "render"))
sys.path.insert(0, str(ROOT / "web"))
from prescreen import has_term  # noqa: E402

LEVELS = ["lead", "strong", "light", "off"]

# German function words. Three or more distinct ones in a posting means it is
# written in German; job-title words alone (Verkäufer) do not decide it.
GERMAN_WORDS = ["und", "die", "der", "das", "wir", "sie", "du", "dich", "ihre", "für",
                "mit", "bei", "unser", "unsere", "suchen", "erfahrung", "kenntnisse"]

# Words too common in postings to say anything about coverage.
STOP = set("""
with without from into onto that this than then have having will your yours our ours they them what when must able also both each more most such very well plus using used within over under upon 
identify nurture drive deliver ideally plus proven track record familiarity
experience experienced strong ability skills skill years team teams work working role
company business customers customer clients client products product including across
within through excellent knowledge understanding environment responsible ensure
support provide manage develop development building build opportunity looking great
their other people should would could about while where which these those there
erfahrung kenntnisse arbeit unternehmen kunden kundinnen bereich bereiche sowie
unsere unser deine ihre sehr gute guten idealerweise wünschenswert aufgaben profil
durch bezug einer einem eines deiner deinen deinem ihrer ihren möchtest bist hast
kannst sind wird werden haben sollte bereit weiter vielzahl lage sicher dafür
gerne jahre praktische erste mehrere andere anderen stetig dynamischen dynamisches
teamplayer umgebung erreichung unterstützen unterstützung ziele zielen
berufserfahrung vergleichbare vorteil plus bonus nice mehrjährige mehrjähriger
bevorzugt rolle kompetenz kompetenzen sehr gute gutes fundierte fundiertes
""".split())


def written_language(lang):
    """A requirement for this language in writing, or at a high level."""
    n = "|".join(re.escape(x.lower()) for x in
                 [lang.get("language", "")] + (lang.get("names") or []) if x)
    lv = r"schrift|written|verhandlungssicher|c1|c2|fluent|native"
    return re.compile(r"(%s)[^.;]{0,60}(%s)|(%s)[^.;]{0,60}(%s)" % (n, lv, lv, n))


# Personal qualities and conditions: true or not of them, but nothing a CV
# bullet covers. Scored as keywords they filled the requirement list with
# "gaps" (motivation, a driving licence, being a team player) and buried the
# real ones.
# A degree requirement is read against the education entries, not by word:
# "Bachelor's degree" never matched "B.S. Information System Security".
DEGREE = re.compile(r"\b(bachelor|degree|b\.\s?[as]\.|bsc|studium|hochschulabschluss|"
                    r"abgeschlossene[sn]?\s+(studium|ausbildung)|master|mba|ph\.?d|diplom)", re.I)
VOCATIONAL = re.compile(r"\b(ausbildung\s+(als|zum|zur)|abgeschlossene[rn]?\s+(berufs)?ausbildung|"
                        r"fachinformatiker|kaufmann|kauffrau)", re.I)
HIGHER_DEGREE = re.compile(r"\b(master|mba|ph\.?d|doctor|doktor|diplom)", re.I)
HELD_BACHELOR = re.compile(r"^(b\.\s?[as]\.|bachelor|bsc)", re.I)
HELD_HIGHER = re.compile(r"^(m\.\s?[as]\.|master|mba|ph\.?d|diplom)", re.I)


def degree_status(line, education):
    """(status, note) for a line that asks for a degree, or None if it does not."""
    held = [e.get("degree", "") for e in education or []]
    # A German vocational qualification (Ausbildung als ...) is not a degree,
    # but a relevant one may be "vergleichbar". The employer decides that, so
    # it is marked as something to argue, never as covered.
    if VOCATIONAL.search(line) and not DEGREE.search(line):
        if held and re.search(r"vergleichbar|equivalent|comparable", line, re.I):
            return "available", ("comparable qualification to argue in the letter: %s"
                                 % "; ".join(held))
        return "gap", "asks for a specific vocational qualification (Ausbildung)"
    if not DEGREE.search(line):
        return None
    bachelor = next((d for d in held if HELD_BACHELOR.search(d)), None)
    higher = next((d for d in held if HELD_HIGHER.search(d)), None)
    # "Bachelor's or Master's" asks for the lower one; a Master's alone asks for it.
    wants_higher = HIGHER_DEGREE.search(line) and not re.search(r"bachelor|b\.\s?[as]\.|bsc", line, re.I)
    if wants_higher:
        return ("covered", "degree: %s" % higher) if higher else (
            "gap", "asks for a degree above a bachelor's; you hold %s" % (bachelor or "none listed"))
    if bachelor or higher:
        return "covered", "degree: %s (check the field matches)" % (higher or bachelor)
    return "gap", "no degree in education"


PERSONAL = re.compile(
    r"\b(motivat\w*|zuverl(ä|ae|a)ss\w*|reliab\w*|teamplayer|team player|teamf(ä|ae|a)hig\w*|"
    r"begeister\w*|leidenschaft\w*|passion\w*|interesse\b|neugier\w*|curious|curiosity|"
    r"reisebereit\w*|willingness to travel|f(ü|ue|u)hrerschein\w*|driv(er'?s|ing) licen[cs]e|"
    r"homeoffice|home office|flexib\w*|belastbar\w*|eigeninitiative|hands-on mentality|"
    r"kundenorientiert\w*|customer.obsessed|freundlich\w*|sorgf(ä|ae|a)lt\w*|teil eines)", re.I)


def covers(word, text, text_low=None):
    """Whether a posting word appears in a text, allowing for German.

    German inflects and compounds: "Kundenbeziehungen" should find
    "Kundenbeziehung", and "Beratung" should find "Beratungsprojekte". Whole-word
    matching read every line of a German posting as a gap. Long words match on
    a stem as a substring; short ones and acronyms stay whole-word, so "SaaS"
    does not match inside another word.
    """
    # A hyphenated compound is covered by any real part of it: "IT-Sicherheit"
    # by "Sicherheitsaudits", "Cloud-Lösungen" by "cloud email security".
    parts = [x for x in word.strip("-/").split("-") if len(x) >= 5]
    if "-" in word.strip("-") and parts:
        return any(covers(x, text, text_low) for x in parts)
    w = word.lower()
    if len(w) < 6 or word.isupper():
        return has_term(word, text)
    stem = w[:max(5, len(w) - 3)]
    return stem in (text_low if text_low is not None else text.lower())


def load(name):
    return json.loads((ROOT / "profile" / name).read_text(encoding="utf-8"))


def cv_languages():
    try:
        m = json.loads((ROOT / "profile" / "market.json").read_text(encoding="utf-8"))
        return [x for x in m.get("cv_languages") or [] if x] or ["en"]
    except (OSError, ValueError):
        return ["en"]


def detect_lang(text):
    low = " %s " % re.sub(r"[^\wäöüß]+", " ", (text or "").lower())
    hits = sum(1 for w in GERMAN_WORDS if " %s " % w in low)
    return "de" if hits >= 3 or re.search(r"\((m|w|d|x)/(m|w|d|x)", text or "", re.I) else "en"


def score_thread(thread, title, body):
    """(score, matched terms). Title matches count three times."""
    score, matched = 0, []
    for t in thread.get("targets", []):
        if has_term(t, title):
            score += 6
            matched.append(t)
        elif has_term(t, body):
            score += 3
            matched.append(t)
    for v in thread.get("vocabulary", []):
        # Five letters or more, or an all-caps acronym: "post" (as in postal
        # mail) once matched the Media thread on a retail posting.
        if not (len(v) >= 5 or v.isupper()):
            continue
        if has_term(v, title):
            score += 3
            matched.append(v)
        elif has_term(v, body) or (len(v) >= 6 and not re.search(r"[- ]", v) and covers(v, body)):
            # covers: German inflection ("Netzwerken", "Firewalls").
            score += 1
            matched.append(v)
    return score, list(dict.fromkeys(matched))


def suggest_base(threads_doc, title, body):
    sig = threads_doc.get("base_signals", {})
    scores = {}
    for base, words in sig.items():
        s = sum(3 for w in words if has_term(w, title))
        s += sum(1 for w in words if has_term(w, body))
        scores[base] = s
    base = "service" if scores.get("service", 0) > scores.get("professional", 0) else "professional"
    return base, scores


def suggest(posting, title="", ctx=None, force_base=None):
    import cv_builder as B  # noqa: E402
    ctx = ctx or B.load_context()
    tdoc = ctx["threads"]
    title = title or (posting or "").strip().splitlines()[0] if (posting or "").strip() else title
    base, base_scores = suggest_base(tdoc, title, posting)
    # The user switched base in the panel: suggest dials for that base instead.
    if force_base in tdoc["bases"]:
        base = force_base
    # The title counts too: "Training Manager (m/w/d)" is a German posting even
    # when the posting text could not be fetched.
    lang = (detect_lang("%s\n%s" % (title, posting)) if (posting or "").strip() or
            re.search(r"\((m|w|d|x)/(m|w|d|x)", title or "", re.I) else tdoc["bases"][base]["lang"])
    # Only a language the user writes CVs in (profile/market.json cv_languages).
    allowed = cv_languages()
    if lang not in allowed:
        lang = tdoc["bases"][base]["lang"] if tdoc["bases"][base]["lang"] in allowed else allowed[0]

    rows = []
    for t in tdoc["threads"]:
        score, matched = score_thread(t, title, posting)
        rows.append({"id": t["id"], "base": t["base"], "score": score, "matched": matched})
    own = sorted([r for r in rows if r["base"] == base], key=lambda r: -r["score"])

    dials = {r["id"]: "off" for r in rows}
    reasons = {}
    lead = own[0]
    dials[lead["id"]] = "lead"
    strong = [r for r in own[1:] if r["score"] >= 3 and r["score"] >= 0.4 * max(lead["score"], 1)]
    for r in strong[:tdoc.get("max_strong", 2)]:
        dials[r["id"]] = "strong"
    for r in own:
        if dials[r["id"]] == "off" and r["score"] > 0:
            dials[r["id"]] = "light"
    # Cross-over (the user's call, 2026-09-24): on a Service CV, a professional
    # thread the posting clearly asks for comes in as Strong. An IT-Administrator
    # posting matched the Technical thread on "firewall", and the Service CV
    # still left out every encryption and lab bullet from one employer, the best
    # evidence they have for it. Not the other way round: the service threads'
    # plain rewordings add nothing a professional CV lacks.
    if base == "service":
        room = tdoc.get("max_strong", 2) - sum(1 for v in dials.values() if v == "strong")
        # An absolute bar as well as a relative one: a systems-administrator
        # posting scored Technical 7 against a Lead of 22, clearly asking for
        # it, and the relative bar alone left it off.
        other = sorted([r for r in rows if r["base"] != base and r["score"] >= 3
                        and (r["score"] >= 6 or r["score"] >= 0.5 * max(lead["score"], 1))],
                       key=lambda r: -r["score"])
        for r in other[:max(room, 0)]:
            dials[r["id"]] = "strong"
            reasons[r["id"]] = "Strong (from the Professional side): posting mentions %s" % (
                ", ".join(r["matched"][:4]))
    # The user's own framing (2026-09-24): enablement is the backbone of all their
    # professional work, and AI belongs in nearly every CV now. Never Off there.
    if base == "professional":
        for tid in ("enablement", "ai"):
            if dials.get(tid) == "off":
                dials[tid] = "light"
                reasons[tid] = "Light by default: part of nearly every professional CV."

    for r in rows:
        if r["id"] in reasons:
            continue
        if r["matched"]:
            reasons[r["id"]] = "%s: posting mentions %s" % (
                dials[r["id"]].capitalize(), ", ".join(r["matched"][:4]))
        elif dials[r["id"]] == "lead":
            reasons[r["id"]] = "Lead by default for this base; the posting names none of its terms."
        else:
            reasons[r["id"]] = "Off: nothing in the posting calls for it."

    import server  # noqa: E402  clean_title and the requirement extractor live there
    headline = server.clean_title(title)
    spec = B.default_spec(base, lang=lang, lead=lead["id"], dials=dials, ctx=ctx)
    spec["headline"] = headline
    return {
        "spec": spec,
        "base_reason": "service signals %d vs professional %d" % (
            base_scores.get("service", 0), base_scores.get("professional", 0)),
        "lang_reason": "posting is written in %s" % ("German" if lang == "de" else "English"),
        "reasons": reasons,
        "scores": {r["id"]: r["score"] for r in rows},
        "requirements": requirements(posting, spec, ctx),
    }


def requirements(posting, spec, ctx, limit=8):
    """The posting's requirement lines, each marked against the CV the spec builds.

    covered    words from the line appear in a bullet or skill the CV shows
    available  they appear somewhere in career.json, just not in this CV
    gap        they appear nowhere: never invented, address it honestly

    A word-level hint, not a judgement: it is shown so a missing strength can be
    added with one click, and a real gap is seen before an interviewer finds it.
    """
    import cv_builder as B  # noqa: E402
    import server  # noqa: E402
    lines = server.posting_requirements(posting or "", limit=limit)
    if not lines:
        return []
    p = B.plan(spec, ctx)
    shown = " ".join(b.get("text", "") + " " + (b.get("text_de") or "")
                     for g in (p["jobs"], p["projects"]) for x in g for b in x["bullets"])
    shown += " " + " ".join(" ".join(c.get("items", []) + (c.get("items_de") or []))
                            for _, _, c in p["skills"])
    # Career content only: the whole file also holds _do_not_reintroduce, where
    # "champions network" appears as a fabrication, and a requirement asking for
    # champions came back "available" from that note.
    from prescreen import profile_text  # noqa: E402
    everything = profile_text()
    sys.path.insert(0, str(ROOT / "tools"))
    import claim_check  # noqa: E402
    blocked = claim_check.banned_phrases()
    langs = ctx["career"].get("languages") or []
    shown += " " + " ".join("%s %s" % (x.get("language", ""), x.get("language_de", ""))
                            for x in langs)
    # A language the user holds only partly (career.json languages[].gate).
    gated = [x for x in langs if x.get("gate")]
    shown_low, everything_low = shown.lower(), everything.lower()
    out = []
    for line in lines:
        low = line.lower()
        # A language the user holds only partly is a gate, not a keyword: say so
        # rather than scoring the line on its words.
        g = next((x for x in gated if written_language(x).search(low)), None)
        if g:
            out.append({"text": line, "status": "gap", "matched": [], "bullets": [],
                        "note": "Language gate: %s" % (g.get("honest_detail") or g["gate"])})
            continue
        hit = next((b for b in blocked if re.search(r"(?<!\w)%s(?!\w)" % re.escape(b), low)), None)
        if hit:
            # A blocked claim is a gap by definition: it was removed as untrue.
            out.append({"text": line, "status": "gap", "matched": [],
                        "bullets": [], "note": "asks for %r, which is on the blocked-claims "
                                               "list: never claim it" % hit})
            continue
        deg = degree_status(line, ctx["career"].get("education"))
        if deg and len(line) < 220:
            out.append({"text": line, "status": deg[0], "matched": [], "bullets": [],
                        "note": deg[1]})
            continue
        if PERSONAL.search(line) and len(line) < 140:
            out.append({"text": line, "status": "personal", "matched": [], "bullets": [],
                        "note": "A personal quality or condition, not CV evidence: answer "
                                "it in the letter or the interview if it matters."})
            continue
        words = [w for w in re.findall(r"[A-Za-zÄÖÜäöüß][\wäöüß+#/-]{3,}", line)
                 if w.lower() not in STOP]
        in_cv = [w for w in words if covers(w, shown, shown_low)]
        in_data = [w for w in words if covers(w, everything, everything_low)]
        if words and len(in_cv) >= max(1, (len(words) + 1) // 2):
            status = "covered"
        elif words and len(in_data) >= max(1, (len(words) + 1) // 2):
            status = "available"
        else:
            status = "gap"
        # Bullets that could cover it, for the one-click add.
        candidates = []
        if status == "available":
            for role in ctx["career"].get("roles", []):
                for b in role.get("bullets", []):
                    both = b.get("text", "") + " " + (b.get("text_de") or "")
                    if any(covers(w, both) for w in in_data):
                        candidates.append(b["id"])
        out.append({"text": line, "status": status, "matched": in_cv or in_data,
                    "bullets": candidates[:3]})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("posting", help="posting text file, or - for stdin")
    ap.add_argument("--title", default="")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    text = sys.stdin.read() if args.posting == "-" else Path(args.posting).read_text(
        encoding="utf-8", errors="replace")
    s = suggest(text, args.title)
    if args.as_json:
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return 0
    spec = s["spec"]
    print("base      %s  (%s)" % (spec["base"], s["base_reason"]))
    print("language  %s  (%s)" % (spec["lang"], s["lang_reason"]))
    print("headline  %s" % spec["headline"])
    for tid, level in sorted(spec["dials"].items(), key=lambda kv: LEVELS.index(kv[1])):
        if level != "off" or s["scores"].get(tid):
            print("  %-6s %-14s %s" % (level, tid, s["reasons"].get(tid, "")))
    if s["requirements"]:
        print("\nrequirements")
        for r in s["requirements"]:
            print("  %-9s %s" % (r["status"], r["text"][:90]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
