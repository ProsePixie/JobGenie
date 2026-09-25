#!/usr/bin/env python3
"""Render a cover letter from markdown into a one-page PDF.

Reuses the CV pipeline's Chrome and pdftotext helpers, so a letter is subject
to the same text-layer discipline as the CV.

The source is markdown with a small frontmatter block:

    ---
    company: Acme GmbH
    role: Prompt Engineer
    recipient: Hiring Team
    city: Berlin
    ---

    Opening paragraph.

    - a bullet, if one earns its place
    - another

    Closing paragraph.

The sender block shows the same links as the CV beside it, decided by the
dials in that folder's build.json; without one, only links not tied to a
thread appear.

Before anything is rendered, the source is checked against writing-style.md
(tools/voice_check.py) and against career.json's blocked claims and other
companies' names (tools/claim_check.py). Any FAIL stops the render.

Supported markdown: paragraphs, `- ` bullets, **bold**, *italic*. That is the
whole grammar a cover letter needs, and keeping it small means no dependency.

Usage
    py render/letter.py applications/acme/letter.md
    py render/letter.py applications/acme/letter.md --html-only
    py render/letter.py applications/acme/letter.md --basename Jane_Doe_Letter
"""

import argparse
import datetime
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import (  # noqa: E402
    Omissions, display_url, ensure_exact_case, find_chrome, find_pdftotext, is_todo,
    page_count, places_de, take, write_pdf, write_text_layer,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import claim_check  # noqa: E402
import voice_check  # noqa: E402
PROFILE = ROOT / "profile"
TEMPLATES = Path(__file__).resolve().parent / "templates"

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)

MONTHS_DE = {1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
             7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November",
             12: "Dezember"}

CHROME = {
    "en": {"subject": "Application: %s", "signoff": "Sincerely,"},
    # No comma: DIN 5008, and a comma here is a common tell of a translated letter.
    "de": {"subject": "Bewerbung als %s", "signoff": "Mit freundlichen Grüßen"},
}


def find_todos(text):
    """Literal TODO outside an HTML comment block.

    A scaffold's own instructional comment (see letter_scaffold() in
    web/server.py) is multi-line, so this strips whole <!-- ... --> blocks
    first rather than checking whether one line itself starts with <!--,
    which would miss a TODO sitting on an inner line of that comment."""
    stripped = COMMENT_RE.sub("", text)
    return [ln.strip() for ln in stripped.splitlines() if "TODO" in ln]


MONTHS_EN = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
             7: "July", 8: "August", 9: "September", 10: "October", 11: "November",
             12: "December"}


def format_date(lang):
    """Day, month, year in both languages: "24 September 2026".

    The one exception to American English in writing-style.md, by the user's
    choice: dates are European order. The month is spelled out so a reader
    used to either convention reads it the same way. Named months rather than
    strftime("%B"), which follows the machine's locale.
    """
    today = datetime.date.today()
    if lang == "de":
        return "%d. %s %d" % (today.day, MONTHS_DE[today.month], today.year)
    return "%d %s %d" % (today.day, MONTHS_EN[today.month], today.year)


def check_source(raw, company):
    """Voice and grounding findings for the letter source, FAILs first."""
    findings = voice_check.scan(raw, voice_check.load_banned())
    findings += claim_check.scan(raw, company)
    return sorted(findings, key=lambda f: (f["level"] != "FAIL", f["line"]))


def parse_frontmatter(raw):
    """Return (meta, body). Frontmatter is optional."""
    meta = {}
    if not raw.startswith("---"):
        return meta, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return meta, raw
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip().lower()] = val.strip()
    return meta, parts[2]


def inline(text):
    """Escape, then apply the two inline markers. Order matters."""
    out = html.escape(text, quote=False)
    out = BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = ITALIC_RE.sub(r"<em>\1</em>", out)
    return out


def md_to_html(body):
    blocks, buf, mode = [], [], None

    def flush():
        if not buf:
            return
        if mode == "ul":
            items = "".join("<li>%s</li>" % inline(b) for b in buf)
            blocks.append("<ul>%s</ul>" % items)
        else:
            blocks.append("<p>%s</p>" % inline(" ".join(buf)))
        buf.clear()

    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            mode = None
            continue
        if stripped.startswith("- "):
            if mode != "ul":
                flush()
                mode = "ul"
            buf.append(stripped[2:])
        else:
            if mode == "ul":
                flush()
            mode = "p"
            buf.append(stripped)
    flush()
    return "\n".join(blocks)


def build_sender(ident, lang="en", links=None):
    name = ident.get("name", "")
    if is_todo(name):
        sys.exit("identity.name is still TODO in profile/career.json. "
                 "A letter cannot be signed without it.")
    bits = []
    for key in ("email", "phone"):
        val = ident.get(key)
        if not is_todo(val):
            bits.append(html.escape(val))
    city = ident.get("city")
    loc = city if not is_todo(city) else ident.get("location")
    if loc and not is_todo(loc):
        bits.append(html.escape(places_de(loc) if lang == "de" else loc))
    # The letter is often read before the CV is opened, and the portfolio is
    # the one thing on it a reader can check. Same link set as the CV.
    if links is None:
        links = untied_links(ident)
    for _key, url in links:
        bits.append('<a href="%s">%s</a>' % (html.escape(url), html.escape(display_url(url))))
    lines = "<br>".join(bits)
    return ('<div class="sender"><span class="name">%s</span>%s</div>'
            % (html.escape(name), lines))


def untied_links(ident):
    """Links not tied to any thread: what a letter without a build.json shows."""
    out = []
    for key, val in (ident.get("links") or {}).items():
        if isinstance(val, dict):
            if val.get("threads"):
                continue
            val = val.get("url")
        clean = take(val, "identity.links.%s" % key, key, Omissions())
        if clean:
            out.append((key, clean))
    return out


def build_links(folder, ident):
    """Links for a letter made from the CV builder: the same set its CV shows,
    decided by the dials in the build.json beside it. None when there is no
    build.json; the sender block then shows only untied links."""
    spec_path = folder / "build.json"
    if not spec_path.exists():
        return None
    try:
        import cv_builder  # noqa: E402  sits beside this file
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        return cv_builder.thread_links(ident, spec, cv_builder.load_context(), Omissions())
    except (ValueError, KeyError, OSError):
        return None


def build_recipient(meta):
    rows = []
    for key in ("recipient", "company", "city"):
        val = meta.get(key)
        if val:
            rows.append(html.escape(val))
    if not rows:
        return ""
    return '<div class="recipient">%s</div>' % "<br>".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="path to letter.md")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--basename", default="letter",
                    help="output filename stem (default 'letter'). Use a real name for "
                         "anything a human downloads: --basename Jane_Doe_Letter")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        sys.exit("no such file: %s" % src)

    raw = src.read_text(encoding="utf-8")
    # Enforced here, not only by web/server.py's api_letter wrapper: CLAUDE.md
    # documents that letter.py refuses to render a TODO, but this script had
    # no such check of its own and would happily write a PDF containing the
    # literal word, only warning about it afterward - a real gap for exactly
    # the direct-CLI usage this file's own docstring shows as an example.
    todos = find_todos(raw)
    if todos:
        sys.exit("%s still has %d TODO line(s) - fill them in before rendering:\n%s"
                 % (src, len(todos), "\n".join("  " + t for t in todos[:8])))

    career = json.loads((PROFILE / "career.json").read_text(encoding="utf-8"))
    ident = career.get("identity", {})

    meta, body = parse_frontmatter(raw)
    if not body.strip():
        sys.exit("%s has no body text." % src)

    # The same two checks the web app runs, so a letter rendered from the
    # command line cannot skip them. Warnings are shown and do not block.
    findings = check_source(raw, meta.get("company", ""))
    for f in findings:
        print("%-4s  line %-3s %s" % (f["level"], f["line"] or "-", f["rule"]))
        if f.get("excerpt"):
            print("            %s" % f["excerpt"])
    fails = [f for f in findings if f["level"] == "FAIL"]
    if fails:
        sys.exit("\n%d check(s) failed in %s. Fix the source; nothing was rendered."
                 % (len(fails), src.name))


    lang = meta.get("lang") if meta.get("lang") in ("en", "de") else "en"
    chrome = CHROME[lang]

    role = meta.get("role", "")
    subject = (chrome["subject"] % role) if role else chrome["subject"].split(":")[0]
    today = format_date(lang)

    parts = [
        build_sender(ident, lang, build_links(src.parent, ident)),
        build_recipient(meta),
        '<div class="date">%s</div>' % html.escape(today),
        '<div class="subject">%s</div>' % html.escape(subject),
        # The scaffold's comment block holds the Lead thread, the internal pitch and
        # notes like "being read as overqualified and as a flight risk". It is
        # for the writer only. It was rendered into the letter as text.
        md_to_html(COMMENT_RE.sub("", body)),
        '<div class="signoff">%s<span class="name">%s</span></div>'
        % (html.escape(chrome["signoff"]), html.escape(ident.get("name", ""))),
    ]

    shell = (TEMPLATES / "shell.html").read_text(encoding="utf-8")
    style = (TEMPLATES / "letter.css").read_text(encoding="utf-8")
    page = (shell
            .replace("{{LANG}}", lang)
            .replace("{{TITLE}}", "%s - %s" % (subject, meta.get("company", "")))
            .replace("{{STYLE}}", style)
            .replace("{{BODY}}", "\n".join(p for p in parts if p)))

    out_dir = src.parent
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", args.basename).strip("_") or "letter"
    html_path = out_dir / ("%s.html" % stem)
    ensure_exact_case(html_path)
    html_path.write_text(page, encoding="utf-8")
    print("html      %s" % html_path)

    if args.html_only:
        return 0

    chrome = find_chrome()
    if not chrome:
        print("pdf       skipped, no Chrome or Edge found")
        return 0

    pdf_path = out_dir / ("%s.pdf" % stem)
    ok, err = write_pdf(html_path, pdf_path, chrome)
    if not ok:
        print("pdf       FAILED: %s" % err)
        return 1
    print("pdf       %s" % pdf_path)

    ptt = find_pdftotext()
    if ptt:
        text, err = write_text_layer(pdf_path, out_dir / ("%s.txt" % stem), ptt)
        if text is not None:
            pages = page_count(text)
            flag = "" if pages <= 1 else "   OVER 1 PAGE - cut, do not shrink the type"
            print("pages     %d%s" % (pages, flag))
            # Scaffold notes must never reach an employer. If any marker of the
            # comment block survives into the PDF, the letter is not sendable.
            leaked = [m for m in ("<!--", "-->", "Spine (reference only", "Gap to be honest",
                                  "Never use:", "Opening move:") if m in text]
            if leaked:
                print("FAILED    internal scaffold notes reached the letter: %s. "
                      "Do not send this PDF." % ", ".join(leaked))
                return 1
            if pages > 1:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
