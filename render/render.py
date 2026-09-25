#!/usr/bin/env python3
"""Render career data into an application package.

One data source, four outputs:

    cv.html         reviewable in a browser, and the PDF source
    cv.pdf          ATS-safe single column, via headless Chrome
    cv.txt          plain text built from the same HTML, for pasting into portal fields
    cv.fields.json  flat key/value payload for filling ATS forms

Standard library only. No LaTeX, no pip installs. Chrome or Edge does the
PDF; pdftotext (ships with Git for Windows) does the text layer.

Usage
    py render/render.py --check
    py render/render.py --base professional --lead ai --threads "enablement=strong" \
        --out applications/acme-pe --posting applications/acme-pe/posting.txt

Selection (bases, thread dials, bullets) lives in render/cv_builder.py; this
module holds the shared page, PDF and text-layer helpers it uses.

Rule enforced here, not merely documented: a field whose value contains TODO
is never written into a document. It is omitted and reported on the console.
"""

import argparse
import html
import json
import os
from html.parser import HTMLParser
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile"
TEMPLATES = Path(__file__).resolve().parent / "templates"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
]

# Roles with these org_types are presented as "Projects"; everything else is
# employment history. This is what lets a CV lead with built things or
# with employers without maintaining two copies of the data.
PROJECT_ORG_TYPES = {"independent", "product"}

MONTHS = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
    "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}

# A German CV with "Oct 2025" and "May 2024" in it reads as half translated.
MONTHS_DE = dict(MONTHS, **{"03": "Mär", "05": "Mai", "10": "Okt", "12": "Dez"})
PRESENT = {"en": "Present", "de": "heute"}


# --------------------------------------------------------------------------
# data helpers
# --------------------------------------------------------------------------

class Omissions:
    """Collects everything dropped for being TODO, so nothing vanishes silently."""

    def __init__(self):
        self.items = []

    def note(self, where, what):
        self.items.append((where, what))

    def report(self):
        if not self.items:
            return "All referenced fields were populated."
        # A missing German translation is not an omission: bullet_text prints
        # the English line instead, so a German CV carries it in English.
        # Reported under its own heading so "omitted" never hides that.
        english = [x for x in self.items if x[0] == "bullet.text_de"]
        other = [x for x in self.items if x[0] != "bullet.text_de"]
        lines = []
        if other:
            lines.append("Omitted %d field(s) that still read TODO:" % len(other))
            lines += ["    %-34s %s" % (w, what) for w, what in other]
        if english:
            lines.append("%d bullet(s) have no German translation and are printed IN "
                         "ENGLISH in this German CV (add text_de, or use the Build "
                         "panel's Translate):" % len(english))
            lines += ["    %s" % what for _, what in english]
        return "\n".join(lines)


def is_todo(value):
    return not isinstance(value, str) or not value.strip() or "TODO" in value


def take(value, where, what, omissions):
    """Return value, or None if it is a TODO placeholder (recording the omission)."""
    if is_todo(value):
        omissions.note(where, what)
        return None
    return value.strip()


def load(name):
    path = PROFILE / name
    if not path.exists():
        sys.exit("missing data file: %s" % path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit("%s is not valid JSON: %s" % (path, exc))


def fmt_date(value, lang="en"):
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    if v.lower() == "present":
        return PRESENT.get(lang, "Present")
    if "TODO" in v:
        return None
    if len(v) == 7 and v[4] == "-":
        months = MONTHS_DE if lang == "de" else MONTHS
        return "%s %s" % (months.get(v[5:7], v[5:7]), v[:4])
    return v


def date_range(role, lang="en"):
    """A missing end date renders as the start alone.

    Never emit a trailing separator: "Jan 2025 -" reads as an unfinished
    document, and guessing "Present" would assert something the data does
    not say.
    """
    start = fmt_date(role.get("start"), lang)
    end = fmt_date(role.get("end"), lang)
    if start and end:
        return "%s - %s" % (start, end)
    return start or end or ""


def sort_key(role):
    """Newest first. Undated entries sink rather than crash the sort."""
    start = role.get("start") or ""
    return "0000-00" if "TODO" in start or not start else start


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def end_year(role):
    """Year a role ended. Ongoing and undated roles sort as current.

    Defaulting to current rather than 0 matters: an undated role must never be
    silently demoted into the earlier-career block where nobody reads it.
    """
    value = (role.get("end") or "").strip().lower()
    if value in ("present", "current"):
        return 9999
    match = re.match(r"(\d{4})", value) or re.match(r"(\d{4})", role.get("start") or "")
    return int(match.group(1)) if match else 9999


def e(text):
    return html.escape(str(text), quote=True)


def display_url(url):
    """Readable form for the page. The href keeps the full URL.

    "linkedin.com/in/jane-doe" reads better than the https://www.
    version and takes less of a contact line that is already crowded.
    """
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


LABELS = {
    "en": {"roles": "Experience", "projects": "Selected Work", "skills": "Skills",
           "certifications": "Certifications", "education": "Education",
           "languages": "Languages", "earlier": "Earlier Experience"},
    "de": {"roles": "Berufserfahrung", "projects": "Ausgewählte Projekte",
           "skills": "Kenntnisse", "certifications": "Zertifizierungen",
           "education": "Ausbildung", "languages": "Sprachen",
           "earlier": "Frühere Tätigkeiten"},
}


COMPOUND = re.compile(r"\w{3,}-\w{3,}")


def keep_compounds(html):
    """Stop hyphenated compounds breaking across lines.

    Applied after escaping, to already-safe text. The hyphen survives
    extraction only if the line never breaks on it, which is the same fix the
    profile URLs needed and for exactly the same reason.
    """
    return COMPOUND.sub(lambda m: '<span class="nb">%s</span>' % m.group(0), html)


def bullet_text(bullet, lang, omissions=None):
    """The bullet in the requested language, falling back to English.

    A missing translation is reported rather than quietly machine-translated.
    An untranslated line in a German CV is a visible gap they can fix; an invented
    German line is a claim nobody reviewed.
    """
    if lang == "de":
        de = bullet.get("text_de")
        if de and not is_todo(de):
            return de
        if omissions is not None:
            omissions.note("bullet.text_de", (bullet.get("text") or "")[:60])
    return bullet["text"]


# Place names in German. A German CV printed "Munich" and "Utah, USA then
# Offenbach, Germany", English words in an otherwise German line. A role can
# carry its own location_de for anything these do not cover.
PLACES_DE = [(" then ", ", danach "), ("Germany", "Deutschland"), ("Bavaria", "Bayern"),
             ("Greater Munich", "Großraum München"), ("Munich", "München"),
             ("Cologne", "Köln"), ("Nuremberg", "Nürnberg"), ("Vienna", "Wien"),
             ("Switzerland", "Schweiz"), ("Austria", "Österreich")]


def places_de(text):
    for en, de in PLACES_DE:
        text = text.replace(en, de)
    return text


def location_text(role, lang="en"):
    loc = role.get("location")
    if not loc or is_todo(loc):
        return ""
    if lang != "de":
        return loc
    if role.get("location_de") and not is_todo(role["location_de"]):
        return role["location_de"]
    return places_de(loc)


def compact_row(title_html, meta):
    """One line: title, org and dates in a single paragraph.

    Compact rows used to put the dates in a right-aligned box beside the title,
    the same layout a full entry uses. With nothing between consecutive rows,
    pdftotext read the date boxes as a second column and emitted every date in
    one clump after the last title - "Sep 2004 Dec 2001" beneath two degrees -
    so no parser could tell which date belonged to which row. Inline, the date
    cannot be separated from its row.
    """
    tail = '<span class="entry-meta-inline"> | %s</span>' % meta if meta else ""
    return ('<div class="entry compact"><p class="entry-title">%s%s</p></div>'
            % (title_html, tail))


def build_section(title, body):
    if not body.strip():
        return ""
    return '<section>\n<h2>%s</h2>\n%s\n</section>' % (e(title), body)


def build_education(career, omissions, lang="en"):
    out = []
    for ed in career.get("education", []):
        inst = take(ed.get("institution"), "education.%s.institution" % ed.get("id"),
                    "institution", omissions)
        field = take(ed.get("field"), "education.%s.field" % ed.get("id"),
                     "field", omissions)
        year = fmt_date(take(ed.get("end"), "education.%s.end" % ed.get("id"),
                             "year", omissions), lang)
        title = ed.get("degree", "")
        # "B.S. Information System Security" plus field "Information System
        # Security" rendered the subject twice. Append the field only when the
        # degree name does not already carry it.
        if field and field.lower() not in title.lower():
            title += ", %s" % field
        out.append(compact_row(
            e(title) + ('<span class="entry-org">, %s</span>' % e(inst) if inst else ""),
            e(year or "")))
    return "\n".join(out)


def build_languages(career, lang="en", omissions=None):
    langs = [l for l in career.get("languages", []) if not is_todo(l.get("language"))]
    if not langs:
        return ""
    if lang == "de":
        parts = []
        for i, l in enumerate(langs):
            name_de, level_de = l.get("language_de"), l.get("level_de")
            if name_de and level_de:
                parts.append("%s (%s)" % (name_de, level_de))
            else:
                if omissions is not None:
                    omissions.note("languages[%d]" % i, "no German translation, left in English")
                parts.append("%s (%s)" % (l["language"], l.get("level", "")))
        text = ", ".join(parts)
    else:
        text = ", ".join("%s (%s)" % (l["language"], l.get("level", "")) for l in langs)
    return '<p class="kv"><span class="kv-value">%s</span></p>' % e(text)


def ensure_exact_case(path):
    """Remove a same-named file whose on-disk casing differs from what is
    about to be written, so the write lands with the casing actually asked
    for.

    Confirmed directly: on Windows, opening "casetest.txt" for writing when
    "CaseTest.txt" already exists overwrites the content in place and keeps
    the original directory entry's casing. No exception, no signal - the file
    on disk is simply still called "CaseTest.txt" afterward. That silently
    reintroduces a stale lowercase filename forever, on every one of the four
    files this renderer writes, for any application folder that already had
    a document rendered before basename case-preservation existed. This is
    the fix for all four; write_pdf's own delete-and-recreate is a special
    case of the same problem, needed there because a locked PDF is also being
    guarded against, not because the casing risk is any different.
    """
    path = Path(path)
    if not path.parent.is_dir():
        return
    real = next((p.name for p in path.parent.iterdir() if p.name.lower() == path.name.lower()), None)
    if real is not None and real != path.name:
        (path.parent / real).unlink()


def find_chrome():
    # CHROME_PATH first: documented in CLAUDE.md, and the only way to point at a
    # Chrome installed somewhere unusual.
    env = os.environ.get("CHROME_PATH", "").strip()
    if env and (Path(env).exists() or shutil.which(env)):
        return env if Path(env).exists() else shutil.which(env)
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


PDFTOTEXT_CANDIDATES = [
    r"C:\Program Files\Git\mingw64\bin\pdftotext.exe",
    r"C:\Program Files\Git\usr\bin\pdftotext.exe",
    r"C:\Program Files (x86)\Git\mingw64\bin\pdftotext.exe",
    r"C:\Program Files (x86)\Git\usr\bin\pdftotext.exe",
]


def find_pdftotext():
    found = shutil.which("pdftotext")
    if found:
        return found
    for c in PDFTOTEXT_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def find_poppler(tool):
    """Another poppler tool (pdfunite, pdfinfo): on PATH, else beside pdftotext,
    which on Windows is usually Git's copy and not on PATH at all."""
    found = shutil.which(tool)
    if found:
        return found
    ptt = find_pdftotext()
    if ptt:
        p = Path(ptt).with_name(tool + Path(ptt).suffix)
        if p.exists():
            return str(p)
    return None


def write_pdf(html_path, pdf_path, chrome):
    # Absolute, always. Chrome resolves --print-to-pdf against its own working
    # directory, not the caller's, so a relative path silently writes somewhere
    # else or fails outright.
    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    # Resolve only the parent, then reattach the requested filename exactly as
    # given. Path.resolve() looks its target up on disk, and on a
    # case-insensitive filesystem it silently returns whatever casing the
    # existing file already has - resolving "ZzzTest_Case.pdf" comes back
    # "zzztest_case.pdf" the moment that file exists under any casing. Calling
    # resolve() on the full path here quietly undid the basename
    # case-preservation fix for every slug that had already been rendered
    # once before that fix existed, since the stale lowercase file was still
    # sitting on disk for resolve() to match against. Directory names in this
    # project are always the lowercase slug they were created with, so
    # resolving just the parent carries no equivalent risk.
    pdf_path = pdf_path.parent.resolve() / pdf_path.name

    # Delete the old file before rendering, rather than judging success by
    # "does a PDF exist afterward". A PDF open in a viewer is locked on
    # Windows; Chrome then fails to overwrite it, the old file is still
    # sitting there, and "exists() -> True" reported success on a document
    # that was not actually regenerated. Removing it first turns that into
    # either a clean PermissionError (caught below, with an actionable
    # message) or a correct False when Chrome genuinely produces nothing.
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except PermissionError:
            return False, ("%s is open in another program (a PDF viewer, usually) "
                           "and cannot be overwritten. Close it and render again."
                           % pdf_path.name)

    with tempfile.TemporaryDirectory(prefix="cvrender-") as profile_dir:
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
        ]
        # Linux containers and CI runners often block Chrome's sandbox, and it
        # then exits with no PDF and nothing on stderr. CHROME_NO_SANDBOX=1 opts out.
        if os.environ.get("CHROME_NO_SANDBOX") == "1":
            cmd.append("--no-sandbox")
        cmd += [
            "--no-first-run",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=4000",
            "--user-data-dir=%s" % profile_dir,
            "--print-to-pdf=%s" % str(pdf_path),
            html_path.resolve().as_uri(),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return False, "Chrome did not finish printing the PDF within 120 seconds."

    if not pdf_path.exists():
        detail = (proc.stderr or proc.stdout or "").strip()[:600]
        return False, detail or ("Chrome exited without producing a file and printed "
                                 "nothing to stderr. Often a headless-Chrome sandbox "
                                 "restriction; check whether antivirus or Windows "
                                 "Controlled Folder Access is blocking chrome.exe from "
                                 "writing inside this project folder.")
    if pdf_path.stat().st_size == 0:
        pdf_path.unlink(missing_ok=True)
        return False, "Chrome produced an empty file. The HTML likely failed to load."
    return True, ""


def write_text_layer(pdf_path, txt_path, pdftotext, layout=False):
    """Emit the text layer.

    Default is flowing text, not -layout. This file exists to be pasted into
    portal fields, and -layout pads every line out to its visual column, which
    arrives in the form as a wall of spaces. ats_check.py does use -layout,
    because there the question is what a layout-aware parser sees.
    """
    ensure_exact_case(txt_path)
    cmd = [pdftotext, "-enc", "UTF-8"]
    if layout:
        cmd.append("-layout")
    cmd += [str(pdf_path), str(txt_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if not txt_path.exists():
        return None, (proc.stderr or "").strip()[:400]
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    return text, ""


class _PasteText(HTMLParser):
    """HTML to plain text that keeps the document's own line structure."""

    BLOCKS = {"h1", "h2", "p", "li", "div", "section", "ul", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.buf, self.skip, self.spans, self.heading = [], [], 0, [], False

    def flush(self):
        text = " ".join("".join(self.buf).split())
        if self.heading:
            text = text.upper()
        if text:
            self.lines.append(text)
        self.buf = []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "title", "script"):
            self.skip += 1
        elif tag in self.BLOCKS or tag == "br":
            self.flush()
            if tag == "h2":
                self.lines.append("")
                self.heading = True
            elif tag == "li":
                self.buf.append("- ")
        elif tag == "span":
            sep = ("class", "sep") in attrs
            self.spans.append(sep)
            if sep:
                self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in ("style", "title", "script"):
            self.skip -= 1
        elif tag in self.BLOCKS:
            self.flush()
            if tag == "h2":
                self.heading = False
        elif tag == "span" and self.spans and self.spans.pop():
            self.buf.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def paste_text(page_html):
    """Plain text for portal fields, one line per bullet, entry and skill row.

    Built from the HTML rather than extracted from the PDF. pdftotext in
    flowing mode merges rows with tight spacing into one paragraph, so every
    certification landed on a single line and every skill cluster ran into
    the next; -layout keeps the rows but pads them with runs of spaces and hard
    wraps each bullet mid-sentence. The PDF text layer is still what
    ats_check.py verifies. This file only has to paste well.
    """
    parser = _PasteText()
    parser.feed(page_html)
    parser.flush()
    out = []
    for line in parser.lines:
        # A blank line only ever separates sections; never two in a row.
        if not line and (not out or out[-1] == ""):
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


# What "not generic" means, measured on real renders on 2026-09-24. The CV they
# was sent for an electronics-retail job listed two lines of history, no
# bullets and 969 characters on its page. ats_check.py fails a CV below these;
# the renderer uses the same numbers when it decides whether a shorter
# document is still a substantial one.
MIN_BULLETS = 4
MIN_SKILLS = 6
MIN_CHARS_PER_PAGE = 1200
LAST_PAGE_MIN_SHARE = 0.25

_SECTION_RE = re.compile(r"<h2>(.*?)</h2>(.*?)</section>", re.S)
_ARGUED = {"experience", "berufserfahrung", "selected work", "ausgewählte projekte"}
# Languages count as skills: for a retail or service job, native English plus
# fluent spoken German is the most applicable skill they have.
_SKILLED = {"skills", "kenntnisse", "languages", "sprachen"}


def substance(page_html):
    """{"bullets", "skills"}: bullets of actual work, and skill items, in a CV."""
    body = page_html.split("<body>", 1)[-1]  # the stylesheet's comments say "<h2>"
    bullets = skills = 0
    for title, content in _SECTION_RE.findall(body):
        t = html.unescape(title).strip().lower()
        if t in _ARGUED:
            # "<li" plus a space or ">": the builder's bullets carry a
            # data-bullet attribute, and counting the literal "<li>" saw none.
            bullets += len(re.findall(r"<li[\s>]", content))
        if t in _SKILLED:
            for v in re.findall(r'<span class="kv-value">(.*?)</span>', content, re.S):
                v = re.sub(r"\([^)]*\)", "", v)  # "Office (Word, Excel)" is one skill
                skills += len([x for x in v.split(",") if x.strip()])
    return {"bullets": bullets, "skills": skills}


def last_page_share(text):
    """How full the last page is, relative to the first. 1.0 for one page."""
    pages = [" ".join(pg.split()) for pg in text.split("\f") if pg.strip()]
    if len(pages) < 2 or not pages[0]:
        return 1.0
    return len(pages[-1]) / len(pages[0])


def page_count(text):
    """Pages in an extracted text layer.

    pdftotext writes a form feed after *every* page including the last, so a
    one-page document already contains one form feed. Counting separators and
    adding one overcounts by exactly one. Stripping every trailing feed first
    undercounts instead: Chrome's stray blank last page ends in "\f\f", and
    was counted as nothing, so a two-page letter passed a one-page limit. When
    the text ends in a feed, the feeds are the page count.
    """
    if not text:
        return 0
    if text.endswith("\f"):
        return text.count("\f")
    return text.count("\f") + 1


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------

def run_check():
    print("toolchain")
    chrome = find_chrome()
    print("  chrome/edge  %s" % (chrome or "NOT FOUND - PDF rendering unavailable"))
    ptt = find_pdftotext()
    print("  pdftotext    %s" % (ptt or "NOT FOUND - text-layer checks unavailable"))
    print("  python       %s" % sys.version.split()[0])

    print("\ndata")
    career = load("career.json")
    threads = load("threads.json").get("threads", [])
    print("  threads      %s" % ", ".join(t["id"] for t in threads))
    print("  roles        %d" % len(career.get("roles", [])))

    bullets = sum(len(r.get("bullets", [])) for r in career.get("roles", []))
    print("  bullets      %d" % bullets)

    needs = []
    for role in career.get("roles", []):
        for item in role.get("_needs", []):
            needs.append((role["id"], item))
    for ed in career.get("education", []):
        for item in ed.get("_needs", []):
            needs.append((ed["id"], item))

    print("\noutstanding (%d)" % len(needs))
    for where, item in needs:
        print("  %-14s %s" % (where, item))

    # How much each thread has to argue with as Lead. Below MIN_BULLETS a
    # Lead-thread CV fails ats_check's substance test, so it shows up here,
    # before an application, rather than on a rejected PDF. German needs text_de.
    print("\nbullets per thread, en / de (minimum %d)" % MIN_BULLETS)
    for t in threads:
        mine = [b for r in career.get("roles", []) for b in r.get("bullets", [])
                if t["id"] in (b.get("threads") or []) and not is_todo(b.get("text"))]
        de = sum(1 for b in mine if b.get("text_de"))
        print("  %-22s %3d / %3d%s" % (t["id"], len(mine), de,
                                      "" if len(mine) >= MIN_BULLETS else "   TOO FEW"))

    if bullets == 0:
        print("\nNo achievement bullets exist yet. Rendering will produce a")
        print("chronology with no argument in it. Fill career.json first.")
    return 0


def run_builder(args):
    """render.py --base ...: the thread-dial builder from the command line."""
    import cv_builder  # noqa: E402  sits beside this file
    if not args.out:
        sys.exit("--out is required")
    ctx = cv_builder.load_context()
    dials = {}
    for pair in [x.strip() for x in args.threads.split(",") if x.strip()]:
        if "=" not in pair:
            sys.exit("--threads expects thread=level, got %r" % pair)
        key, _, level = pair.partition("=")
        dials[key.strip()] = level.strip().lower()
    spec = cv_builder.default_spec(args.base, lang=args.lang if args.lang != "en" or
                                   args.base == "professional" else None,
                                   lead=args.lead, dials=dials, ctx=ctx)
    spec["headline"] = args.headline
    if args.summary_file:
        spec["summary"] = Path(args.summary_file).read_text(encoding="utf-8").strip()
        spec["summary_accepted"] = True
    if args.max_pages != 2:
        spec["advanced"]["max_pages"] = args.max_pages
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    prefer = tuple(t.strip() for t in args.prefer.split(",") if t.strip())
    if args.posting:
        ctx["posting_terms"] = cv_builder.posting_terms(
            Path(args.posting).read_text(encoding="utf-8", errors="replace"), ctx)
    result = cv_builder.build(spec, out_dir, args.basename, prefer=prefer, fit=args.fit,
                              ctx=ctx)
    if result.get("problems"):
        sys.exit("\n".join(result["problems"]))
    lead = cv_builder.lead_of(spec)
    print("base      %s (%s)   lead %s" % (spec["base"], spec["lang"], lead))
    print("dials     %s" % ", ".join("%s=%s" % (k, v) for k, v in spec["dials"].items()
                                     if v != "off"))
    for key in ("html", "pdf", "txt", "fields"):
        if result.get(key):
            print("%-9s %s" % (key, result[key]))
    print("pages     %s of %s%s" % (result["pages"], result["max_pages"],
                                     ("   " + "; ".join(result["notes"])) if result["notes"] else ""))
    print("bullets   %d shown" % len(result["shown_bullets"]))
    if result.get("untranslated"):
        print("german    %d bullet(s) left out for lack of German text: %s"
              % (len(result["untranslated"]), ", ".join(result["untranslated"])))
    if result.get("err"):
        print("error     %s" % result["err"])
    return 0 if result["ok"] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="output directory for the application package")
    ap.add_argument("--basename", default="cv",
                    help="output filename stem (default 'cv'). Use a real name for "
                         "anything a human downloads: --basename Jane_Doe_CV")
    ap.add_argument("--prefer", default="",
                    help="comma-separated tags from the posting; matching bullets are "
                         "boosted above equal-strength siblings")
    ap.add_argument("--lang", choices=sorted(LABELS), default="en",
                    help="output language (default en). 'de' uses German section "
                         "headings and the reviewed text_de bullets, and reports "
                         "any bullet that has no translation rather than inventing one")
    ap.add_argument("--max-pages", type=int, default=2,
                    help="page limit the document must respect (default 2)")
    ap.add_argument("--no-fit", action="store_false", dest="fit",
                    help="do not reduce bullets to reach the page limit; render "
                         "once at --bullets and report the overflow instead")
    ap.add_argument("--check", action="store_true", help="verify toolchain and data, then exit")
    ap.add_argument("--base", choices=["professional", "service"],
                    help="the base: professional (English) or service (German)")
    ap.add_argument("--lead", help="the Lead thread, e.g. enablement, ai, svc-technical")
    ap.add_argument("--threads", default="",
                    help="other dials as thread=level, comma-separated, e.g. "
                         "'ai=strong,media=light'. Unlisted threads are off")
    ap.add_argument("--headline", default="", help="headline under the name "
                    "(default: the Lead thread's)")
    ap.add_argument("--posting", help="posting text file: bullets that match its words rank higher")
    ap.add_argument("--summary-file", help="an accepted summary to print under the headline")
    args = ap.parse_args()

    if args.check:
        return run_check()
    if not args.base:
        ap.error("--base is required (or use --check)")
    return run_builder(args)


if __name__ == "__main__":
    sys.exit(main())
