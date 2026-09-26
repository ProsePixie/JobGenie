#!/usr/bin/env python3
"""Turn a CV (PDF, DOCX or TXT) in inbox/ into plain text for /setup to read.

    python3 tools/import_cv.py inbox/My_CV.pdf
    python3 tools/import_cv.py            every CV in inbox/

Writes inbox/<name>.txt beside each file and prints where. It only extracts
text: it never interprets it and never writes to profile/. /setup proposes
each fact from this text, and nothing is saved until the user confirms it
(CLAUDE.md hard rule 2). Standard library only: PDF through pdftotext, DOCX
by reading word/document.xml from the zip.
"""

import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
sys.path.insert(0, str(ROOT / "render"))

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_text(path):
    """Paragraphs of a .docx, one per line; list items keep a leading '- '."""
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t"))
        if p.find("%spPr/%snumPr" % (W, W)) is not None and text.strip():
            text = "- " + text
        lines.append(text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def pdf_text(path):
    import render as R
    exe = R.find_pdftotext()
    if not exe:
        raise RuntimeError("pdftotext not found: run python3 tools/doctor.py")
    res = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=60)
    if res.returncode != 0:
        raise RuntimeError("pdftotext failed: %s" % res.stderr.strip()[:200])
    if len(res.stdout.strip()) < 50:
        raise RuntimeError("%s has almost no text layer (a scanned image?). Export it as "
                           "DOCX or a text-based PDF instead." % path.name)
    return res.stdout


def extract(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_text(path)
    if suffix == ".pdf":
        return pdf_text(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError("unsupported file type %s (use PDF, DOCX or TXT)" % suffix)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    files = [Path(a) for a in args] or sorted(
        p for p in INBOX.glob("*") if p.suffix.lower() in (".pdf", ".docx"))
    if not files:
        print("Put your CV (PDF or DOCX) in %s, then run this again." % INBOX)
        return 1
    status = 0
    for f in files:
        try:
            text = extract(f)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            print("FAILED  %s: %s" % (f.name, exc))
            status = 1
            continue
        out = f.with_suffix(".txt") if f.suffix.lower() != ".txt" else f
        out.write_text(text, encoding="utf-8")
        print("text    %s (%d lines)" % (out, text.count("\n")))
    return status


if __name__ == "__main__":
    sys.exit(main())
