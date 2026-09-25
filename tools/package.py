#!/usr/bin/env python3
"""Assemble what actually gets uploaded for one application, and check it last.

    applications/<slug>/submit/
        Jane_Doe_CV.pdf              or _Lebenslauf.pdf
        Jane_Doe_Cover_Letter.pdf    or _Anschreiben.pdf
        Jane_Doe_<enclosure>.pdf     from documents/enclosures/, copied unread
        Jane_Doe_Application.pdf     or _Bewerbung.pdf, with --merge: one file
                                             for portals that take one upload, in
                                             Bewerbungsmappe order (letter, CV, enclosures)

It is the last gate before sending, so it refuses rather than warns:

    - the CV fails render/ats_check.py
    - the letter is older than letter.md, runs past one page, or still says TODO
    - anything from the private tier appears in the package (tools/leak_check.py;
      the finding names file, line and category, never the value)
    - an enclosure named on the command line does not exist

    python3 tools/package.py <slug>
    python3 tools/package.py <slug> --merge
    python3 tools/package.py <slug> --enclose "Reference Acme.pdf" --merge
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "applications"
ENCLOSURES = ROOT / "documents" / "enclosures"
sys.path.insert(0, str(ROOT / "render"))
sys.path.insert(0, str(ROOT / "tools"))

# Many portals cap an upload at 5 MB.
SIZE_WARN = 5 * 1024 * 1024


def stem_for(career):
    name = (career.get("identity") or {}).get("name") or "CV"
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "CV"


def text_of(pdf):
    from render import find_pdftotext
    exe = find_pdftotext()
    if not exe:
        return None
    res = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=60)
    return res.stdout if res.returncode == 0 else None


def letter_lang(md):
    m = re.search(r"^lang:\s*(\w+)", md.read_text(encoding="utf-8"), re.M) if md.exists() else None
    return m.group(1) if m else "en"


def cv_in(folder):
    cvs = sorted((p for p in folder.glob("*.pdf") if "letter" not in p.name.lower()),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    return cvs[0] if cvs else None


def leaks(folder, pdfs, private=None):
    import leak_check
    private = private or leak_check.PRIVATE
    secrets, _ = leak_check.load_secrets(private)
    if not any(secrets[k] for k in ("terms", "emails", "phones", "amounts")):
        return []
    found = [(p, n, c) for p, n, c in leak_check.scan([folder], secrets, private)
             if "submit" not in p.parts]
    for pdf in pdfs:
        text = text_of(pdf)
        if text:
            found += [(pdf, n, c) for n, c in leak_check.scan_text(text, secrets)]
    return ["%s:%d %s" % (p.name, n, c) for p, n, c in found]


def build(slug, enclose=(), merge=False, apps=APPS, enclosures=ENCLOSURES, private=None):
    folder = apps / slug
    if not folder.is_dir():
        return None, ["no application folder %s" % folder], []
    career = json.loads((ROOT / "profile" / "career.json").read_text(encoding="utf-8"))
    stem = stem_for(career)
    problems, warnings, plan = [], [], []

    cv = cv_in(folder)
    if not cv:
        problems.append("no CV PDF in the folder. Build or render it first.")
    else:
        build_spec = folder / "build.json"
        max_pages = 2
        if build_spec.exists():
            max_pages = json.loads(build_spec.read_text(encoding="utf-8")).get("max_pages", 2)
        res = subprocess.run([sys.executable, str(ROOT / "render" / "ats_check.py"), str(cv),
                              "--max-pages", str(max_pages)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", cwd=str(ROOT))
        if res.returncode != 0:
            fails = [l.strip() for l in res.stdout.splitlines() if l.strip().startswith("FAIL")]
            problems.append("%s fails its checks: %s" % (cv.name, "; ".join(fails)[:300]))
        de = "Lebenslauf" in cv.name
        plan.append((cv, "%s_%s.pdf" % (stem, "Lebenslauf" if de else "CV")))

    md, letter = folder / "letter.md", folder / "letter.pdf"
    if letter.exists():
        from render import page_count
        if md.exists() and md.stat().st_mtime > letter.stat().st_mtime + 1:
            problems.append("letter.pdf is older than letter.md. Render the letter again.")
        text = text_of(letter)
        if text is not None:
            if page_count(text) > 1:
                problems.append("the letter runs to %d pages; it must fit on one"
                                % page_count(text))
            if "TODO" in text:
                problems.append("the letter still contains TODO")
        de = letter_lang(md) == "de"
        plan.insert(0, (letter, "%s_%s.pdf" % (stem, "Anschreiben" if de else "Cover_Letter")))
    elif md.exists():
        warnings.append("letter.md exists but was never rendered; packaging without a letter")

    for name in enclose:
        src = enclosures / name
        if not src.exists():
            problems.append("no enclosure %r in documents/enclosures/" % name)
        elif src.suffix.lower() != ".pdf":
            problems.append("enclosure %r is not a PDF" % name)
        else:
            plan.append((src, "%s_%s.pdf" % (stem, re.sub(r"[^A-Za-z0-9]+", "_", src.stem)
                                              .strip("_"))))

    problems += ["private-tier value in the package: %s" % x
                 for x in leaks(folder, [p for p, _ in plan if p.parent == folder], private)]
    if problems:
        return None, problems, warnings

    out = folder / "submit"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    written = []
    for src, target in plan:
        shutil.copyfile(src, out / target)
        written.append(out / target)

    if merge and len(written) < 2:
        warnings.append("only one document, so there is nothing to merge")
    elif merge:
        from render import find_poppler
        exe = find_poppler("pdfunite")
        if not exe:
            warnings.append("pdfunite (poppler, next to pdftotext) not found: no merged file")
        else:
            german = any("Lebenslauf" in p.name or "Anschreiben" in p.name for p in written)
            merged = out / ("%s_%s.pdf" % (stem, "Bewerbung" if german else "Application"))
            res = subprocess.run([exe] + [str(p) for p in written] + [str(merged)],
                                 capture_output=True, text=True, timeout=120)
            if res.returncode == 0 and merged.exists():
                written.append(merged)
            else:
                warnings.append("pdfunite failed: %s" % (res.stderr or "").strip()[:200])

    for p in written:
        if p.stat().st_size > SIZE_WARN:
            warnings.append("%s is %.1f MB; many portals cap uploads at 5 MB"
                            % (p.name, p.stat().st_size / 1e6))
    return written, [], warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug", help="applications/<slug>")
    ap.add_argument("--enclose", nargs="*", default=[],
                    help="PDF file names in documents/enclosures/ to attach")
    ap.add_argument("--merge", action="store_true", help="also write one combined PDF")
    args = ap.parse_args(argv)

    written, problems, warnings = build(args.slug, args.enclose, args.merge)
    for w in warnings:
        print("warning   %s" % w)
    if problems:
        for p in problems:
            print("REFUSED   %s" % p)
        return 1
    for p in written:
        print("ready     %s (%d KB)" % (p.relative_to(ROOT), p.stat().st_size // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
