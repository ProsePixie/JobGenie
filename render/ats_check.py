#!/usr/bin/env python3
"""Verify what an ATS actually extracts from a rendered CV.

The rendered page is not the artifact a parser sees. This checks the text
layer: whether contact details survive as literal text, whether reading order
matches the visual layout, and which posting keywords are present.

Standard library only. Requires pdftotext (ships with Git for Windows).

Usage
    py render/ats_check.py applications/acme/cv.pdf
    py render/ats_check.py applications/acme/cv.pdf --keywords "python,llm,evaluation"
    py render/ats_check.py applications/acme/cv.pdf --keywords-file posting.txt

A keyword reported MISSING is triaged into one of two cases, because they call
for opposite responses:

    missing (gap)      the skill genuinely is not in career.json.
                       Leave it out. Do not invent it. Address it honestly
                       in the letter if it matters.

    missing (have it)  career.json shows it but the rendered CV omitted it.
                       This is a selection failure, not a candidate failure.
                       Re-tag the bullet or raise its strength and re-render.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import find_pdftotext, page_count  # noqa: E402  single source of truth

ROOT = Path(__file__).resolve().parent.parent
CAREER = ROOT / "profile" / "career.json"

# The .txt beside the PDF, set once the target is known. This tool extracts
# with -layout, which preserves the line structure and so keeps a hyphen that
# falls at a line end. render.py extracts reflowed, which does not. The two
# disagree, and the reflowed one is the file pasted into application forms.
TXT_SIBLING = None

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
# Ligatures and private-use glyphs are the classic signature of a PDF whose
# text layer looks fine on screen and turns to noise inside a parser.
SUSPECT_RE = re.compile("[%s-%s%s-%s%s]" % (chr(0xFB00), chr(0xFB06), chr(0xE000), chr(0xF8FF), chr(0xFFFD)))


def extract(pdf_path):
    # find_pdftotext, not shutil.which: on Windows pdftotext is Git's copy and
    # usually not on PATH, so the CV rendered and then failed its own check.
    exe = find_pdftotext()
    if not exe:
        sys.exit("pdftotext not found. On Windows it ships with Git: "
                 r"C:\Program Files\Git\mingw64\bin\pdftotext.exe")
    # -enc UTF-8 is required, not optional. pdftotext otherwise emits Latin-1,
    # and every umlaut comes back as U+FFFD, which would fail this very check
    # on a perfectly sound CV belonging to anyone named Mueller.
    proc = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)
    if proc.returncode != 0:
        sys.exit("pdftotext failed: %s" % (proc.stderr or "").strip()[:400])
    return proc.stdout


def load_keywords(args):
    if args.keywords:
        return [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.keywords_file:
        raw = Path(args.keywords_file).read_text(encoding="utf-8", errors="replace")
        # Reuse the prescreen extractor: requirements-section scoped, restricted to
        # acronyms, proper nouns and known domain terms. Splitting on whitespace
        # returned "policy", "each" and "time" as keywords, which is noise wearing
        # a finding's clothes.
        sys.path.insert(0, str(ROOT / "tools"))
        from prescreen import extract_requirement_gaps  # noqa: E402
        return extract_requirement_gaps(raw, "")[:30]
    return []


STOPWORDS = {
    "the", "and", "for", "with", "you", "our", "are", "will", "have", "this",
    "that", "your", "from", "who", "all", "can", "not", "but", "they", "their",
    "about", "into", "team", "work", "role", "position", "company", "job",
    "years", "experience", "skills", "requirements", "including", "such",
    "well", "also", "more", "other", "within", "across", "using", "help",
}


def check_links(text, findings):
    """Every profile URL must survive extraction intact.

    A URL broken across a line loses its hyphen to pdftotext and silently
    becomes a different address. The href stays correct, so this is invisible
    unless the text layer is checked against the source.
    """
    if not CAREER.exists():
        return
    links = json.loads(CAREER.read_text(encoding="utf-8")).get("identity", {}).get("links", {})
    flat = re.sub(r"\s+", "", text)
    for name, val in links.items():
        url = val.get("url") if isinstance(val, dict) else val
        if not isinstance(url, str) or "TODO" in url or not url.strip():
            continue
        tail = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
        if re.sub(r"\s+", "", tail) in flat:
            findings.append(("PASS", "link:%s" % name, tail))
        elif tail.split("/")[0] in flat:
            findings.append(("FAIL", "link:%s" % name,
                             "present but mangled in the text layer, expected %s" % tail))


def check_contact(text, findings):
    emails = EMAIL_RE.findall(text)
    if emails:
        findings.append(("PASS", "email", emails[0]))
    else:
        findings.append(("FAIL", "email", "no email survived extraction"))

    phones = [p for p in PHONE_RE.findall(text) if sum(c.isdigit() for c in p) >= 8]
    if phones:
        findings.append(("PASS", "phone", phones[0].strip()))
    else:
        findings.append(("WARN", "phone", "no phone in text layer (fine if omitted by choice)"))


def check_integrity(text, findings, max_pages=2):
    if not text.strip():
        findings.append(("FAIL", "text layer", "empty - the PDF has no extractable text"))
        return
    findings.append(("PASS", "text layer", "%d characters extracted" % len(text)))

    bad = SUSPECT_RE.findall(text)
    if bad:
        findings.append(("FAIL", "glyphs", "%d ligature/PUA characters that parsers mangle" % len(bad)))
    else:
        findings.append(("PASS", "glyphs", "no ligature or private-use characters"))

    pages = page_count(text)
    status = "PASS" if pages <= max_pages else "FAIL"
    findings.append((status, "pages", "%d (limit %d)" % (pages, max_pages)))

    # The name should be the first non-empty line. If it is not, the DOM order
    # and the visual order have diverged.
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    if first and len(first) < 60 and "@" not in first:
        findings.append(("PASS", "reading order", "starts with %r" % first[:40]))
    else:
        findings.append(("WARN", "reading order", "first line is unexpected: %r" % first[:60]))

    if re.search(r"\b(19|20)\d{2}\b", text):
        findings.append(("PASS", "dates", "year values present"))
    else:
        findings.append(("WARN", "dates", "no four-digit years found"))

    if "TODO" in text:
        findings.append(("FAIL", "placeholders", "the document contains the literal text TODO"))

    # Section headers must survive as contiguous strings. CSS letter-spacing on
    # tracked capitals extracted as "E D U C AT I O N", which no parser looking
    # for EDUCATION will match. Found by reading the output, not by any check.
    upper = text.upper()
    headers = ("EXPERIENCE", "SKILLS", "EDUCATION",
               "BERUFSERFAHRUNG", "KENNTNISSE", "AUSBILDUNG")
    broken = [h for h in headers if h not in upper and re.search(r"\s".join(h), upper)]
    if broken:
        findings.append(("FAIL", "section headers",
                         "letter-spaced and unparseable: %s" % ", ".join(broken)))
    else:
        present = [h for h in headers if h in upper]
        findings.append(("PASS", "section headers", ", ".join(present) or "none found"))

    check_compounds(text, findings)


def check_compounds(text, findings):
    """Hyphenated compounds must survive extraction with their hyphen.

    A line break falling on a hyphen makes pdftotext drop it, so
    "Enablement-Programm" extracts as "EnablementProgramm" and a parser indexes
    a word that does not exist. This is the same failure that once turned a
    LinkedIn URL into linkedin.com/in/jeremiahgrother.

    Checked against the source rather than by pattern, because the obvious
    heuristic of a lowercase letter followed by a capital would flag every
    FunkTrainer, OpenAI and PowerPoint in the document.
    """
    try:
        career = json.loads(CAREER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return

    compounds = set()
    for role in career.get("roles", []):
        for bullet in role.get("bullets", []):
            for field in ("text", "text_de"):
                for match in re.findall(r"\w{3,}-\w{3,}", bullet.get(field) or ""):
                    compounds.add(match)

    # Checked against the sibling .txt as well as this extraction. They are
    # produced by separate pdftotext runs and wrap differently, and the .txt is
    # the one pasted straight into application forms.
    layers = [text]
    if TXT_SIBLING and TXT_SIBLING.exists():
        try:
            layers.append(TXT_SIBLING.read_text(encoding="utf-8"))
        except OSError:
            pass

    lost = sorted({c for c in compounds for layer in layers
                   if c not in layer and c.replace("-", "") in layer})
    if lost:
        findings.append(("FAIL", "compounds",
                         "hyphen dropped at a line break: %s" % ", ".join(lost[:4])))
    elif compounds:
        findings.append(("PASS", "compounds",
                         "%d hyphenated compounds intact" % len(compounds)))


def check_keywords(text, keywords):
    # Whole words, the same matcher prescreen uses. As substrings, "LMS" was
    # covered by "LLMs" and "Go" by "going", and "SSO" was reported as a skill
    # the data holds but the CV left out - an invitation to re-tag something
    # that was never there.
    sys.path.insert(0, str(ROOT / "tools"))
    from prescreen import has_term, profile_text  # noqa: E402
    flat = " ".join(text.split())
    corpus = profile_text() if CAREER.exists() else ""
    rows = []
    for kw in keywords:
        if has_term(kw, flat):
            rows.append((kw, "covered", ""))
        elif has_term(kw, corpus):
            rows.append((kw, "missing (have it)", "in career.json but not selected - re-tag and re-render"))
        else:
            rows.append((kw, "missing (gap)", "genuine gap - do not invent it"))
    return rows


def check_substance(text, pdf_path, findings):
    """Fail a CV that is thin, generic, or hides the work history.

    His words, 2026-09-24: "Roles should at least be listed and applicable
    skills shown." A CV built to undersell once collapsed every role into
    one sentence and shipped a page that was mostly blank. The text layer
    passed every other check here, because nothing here asked whether the
    document said anything. The thresholds live in render.py, which uses the
    same numbers when it decides whether a shorter version is still good.
    """
    from render import (  # noqa: E402
        LAST_PAGE_MIN_SHARE, MIN_BULLETS, MIN_CHARS_PER_PAGE, MIN_SKILLS,
        PROJECT_ORG_TYPES, last_page_share, substance,
    )
    flat = " ".join(text.split())

    # Every job in career.json appears, by employer name. Side projects are
    # the dials' choice; the employment chronology is not.
    if CAREER.exists():
        roles = json.loads(CAREER.read_text(encoding="utf-8")).get("roles", [])
        # Either spelling counts: a German CV prints org_de where one exists.
        missing = [r.get("org", r.get("id")) for r in roles
                   if r.get("org_type") not in PROJECT_ORG_TYPES and r.get("org")
                   and not any(" ".join(n.split()) in flat
                               for n in (r["org"], r.get("org_de") or "") if n)]
        if missing:
            findings.append(("FAIL", "chronology",
                             "%d job(s) not on the CV: %s. Every role is listed, at "
                             "least as one line" % (len(missing), ", ".join(missing))))
        else:
            findings.append(("PASS", "chronology", "every job in career.json is listed"))

    html_path = pdf_path.with_suffix(".html")
    if html_path.exists():
        html_text = html_path.read_text(encoding="utf-8")
        found = substance(html_text)
        ok = found["bullets"] >= MIN_BULLETS
        # The CV builder leaves bullets without text_de out of a German CV,
        # so a thin German CV is usually missing translations, not tags.
        german = bool(re.search(r'<html[^>]*lang="de"', html_text))
        hint = (". Most likely missing German translations: the builder leaves out "
                "bullets with no text_de. Translate them (Build panel) or build in English"
                if german else ". Tag more of his real bullets with the Lead thread in career.json")
        findings.append(("PASS" if ok else "FAIL", "substance",
                         "%d bullet(s) of actual work (minimum %d)%s"
                         % (found["bullets"], MIN_BULLETS, "" if ok else hint)))
        ok = found["skills"] >= MIN_SKILLS
        findings.append(("PASS" if ok else "FAIL", "skills",
                         "%d skill and language item(s) (minimum %d)%s"
                         % (found["skills"], MIN_SKILLS, "" if ok else
                            ". Tag applicable skill clusters with the Lead thread")))
    else:
        findings.append(("WARN", "substance", "no %s beside the PDF to count bullets "
                         "and skills from" % html_path.name))

    pages = page_count(text)
    if pages:
        per_page = len(flat) // pages
        findings.append(("PASS" if per_page >= MIN_CHARS_PER_PAGE else "FAIL", "fill",
                         "%d characters per page (minimum %d)" % (per_page, MIN_CHARS_PER_PAGE)))
        share = last_page_share(text)
        if pages > 1 and share < LAST_PAGE_MIN_SHARE:
            findings.append(("WARN", "last page",
                             "page %d is %d%% as full as page 1 and could not be "
                             "condensed without cutting below %d bullets"
                             % (pages, 100 * share, MIN_BULLETS)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", help="path to the rendered cv.pdf")
    ap.add_argument("--keywords", help="comma-separated keywords from the posting")
    ap.add_argument("--keywords-file", help="a saved posting; keywords are extracted from it")
    ap.add_argument("--max-pages", type=int, default=2,
                    help="page limit this render was supposed to respect (default 2). "
                         "Some service CVs require 1 - pass "
                         "the same value used with render.py --max-pages.")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit("no such file: %s" % pdf_path)

    # German findings contain umlauts, and stdout to a pipe on Windows encodes
    # in the ANSI codepage, so a redirected report comes back mangled.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    global TXT_SIBLING  # noqa: PLW0603
    TXT_SIBLING = pdf_path.with_suffix(".txt")

    text = extract(pdf_path)

    findings = []
    check_integrity(text, findings, args.max_pages)
    check_contact(text, findings)
    check_links(text, findings)
    check_substance(text, pdf_path, findings)

    print("text layer: %s\n" % pdf_path)
    for status, label, detail in findings:
        print("  %-5s %-15s %s" % (status, label, detail))

    keywords = load_keywords(args)
    if keywords:
        rows = check_keywords(text, keywords)
        print("\nkeyword coverage (%d)" % len(rows))
        for kw, status, note in rows:
            print("  %-22s %-18s %s" % (kw, status, note))
        missing_have = [r for r in rows if r[1] == "missing (have it)"]
        if missing_have:
            print("\n%d keyword(s) are supported by your data but absent from the CV."
                  % len(missing_have))
            print("That is a selection bug. Fix the tags, not the truth.")

    failures = [f for f in findings if f[0] == "FAIL"]
    if failures:
        print("\n%d check(s) failed. Do not submit this PDF." % len(failures))
        return 1
    print("\nText layer is sound.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
