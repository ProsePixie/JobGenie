#!/usr/bin/env python3
"""Re-render every unsent application's CV with today's data and rules.

A CV rendered before a rule changed stays exactly as it was: the VHS CVs
missed a role the chronology check now requires, the Omaze CV ran to three
pages. This finds every application that has not gone out yet, builds its CV
again with the CV builder - from its saved build.json, or the Build panel's own
suggestion from the posting when there is none - runs the current checks on
the old file and the new one, and shows the difference.

Nothing is replaced unless --apply is given, and then the old files are kept
in <app>/_previous/<date>/, never deleted. Applications that were sent,
answered, or closed are never touched: the file there is the record of what
the employer received.

    py tools/rerender.py                 dry run: stage, check, compare
    py tools/rerender.py --only vhs      only slugs containing "vhs"
    py tools/rerender.py --apply         replace the old CVs that the new ones beat
"""

import argparse
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))

LOCKED_STAGES = {"sent", "responded", "interviewing", "closed"}
STAGING = "_rerender"


def fails(server, pdf, max_pages):
    """The failing check names for one PDF, via the real ats_check."""
    res = server.run([server.PY, "render/ats_check.py", str(pdf), "--max-pages", str(max_pages)])
    out = [line.split()[1] for line in res["out"].splitlines()
           if line.strip().startswith("FAIL") and len(line.split()) > 1]
    return res["ok"], out


def spec_for(server, B, S, entry, folder):
    """(spec, max_pages, file stem): what the Build panel would open with."""
    saved = server.load_json(folder / "build.json", None)
    ctx = server._build_ctx(B, entry)
    if saved:
        spec = saved
    else:
        posting, _ = server._posting_for(entry)
        spec = (S.suggest(posting, entry.get("role", ""), ctx=ctx)["spec"] if posting else
                server.fallback_spec(B, ctx, entry))
    name = (ctx["career"].get("identity") or {}).get("name", "CV")
    stem = "%s_%s" % (server.re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "CV",
                      "Lebenslauf" if spec.get("lang") == "de" else "CV")
    return spec, spec.get("max_pages") or 2, stem


def candidates(server, only=""):
    for entry in server.load_pipeline():
        if entry.get("stage") in LOCKED_STAGES or entry.get("outcome") in server.TERMINAL:
            continue
        folder = server.app_dir(entry["id"])
        if only and only not in folder.name:
            continue
        cvs = [p for p in folder.glob("*.pdf") if "letter" not in p.name.lower()]
        if cvs:
            yield entry, folder, cvs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="replace old CVs the new ones beat")
    ap.add_argument("--only", default="", help="only folders whose name contains this")
    args = ap.parse_args()

    import server  # noqa: E402

    rows = []
    B, S = server._builder()
    for entry, folder, old_cvs in candidates(server, args.only):
        spec, max_pages, stem = spec_for(server, B, S, entry, folder)
        stage = folder / STAGING
        shutil.rmtree(stage, ignore_errors=True)
        ctx = server._build_ctx(B, entry)
        try:
            res = B.build(spec, stage, stem, ctx=ctx)
        except Exception as exc:  # noqa: BLE001 - report it per application
            res = {"ok": False, "err": str(exc)}
        new_pdf = Path(res["pdf"]) if res.get("pdf") else None
        old_ok, old_fails = fails(server, old_cvs[0], max_pages)
        label = {"lead": B.lead_of(spec), "lang": spec.get("lang")}
        if not new_pdf or not new_pdf.exists():
            rows.append((folder.name, old_ok, old_fails, False, ["build failed"], None, label))
            continue
        new_ok, new_fails = fails(server, new_pdf, res.get("max_pages", max_pages))
        rows.append((folder.name, old_ok, old_fails, new_ok, new_fails, (old_cvs, stage), label))

    if not rows:
        print("No unsent application has a CV to re-render.")
        return 0

    print("%-58s %-26s %s" % ("application", "current CV", "rebuilt today"))
    for name, old_ok, old_f, new_ok, new_f, _, st in rows:
        print("%-58s %-26s %s   (%s, %s)" % (
            name[:58], "ok" if old_ok else "FAILS " + ",".join(old_f)[:20],
            "ok" if new_ok else "FAILS " + ",".join(new_f), st["lead"], st["lang"]))

    better = [r for r in rows if r[3] and not r[1]]
    if not args.apply:
        print("\n%d CV(s) fail today's checks and pass when re-rendered. Staged in each "
              "folder's %s/ for review; nothing replaced. Run with --apply to swap them in."
              % (len(better), STAGING))
        return 0

    stamp = datetime.date.today().isoformat()
    for name, old_ok, _, new_ok, _, paths, _ in rows:
        if not paths:
            continue
        old_cvs, stage = paths
        folder = stage.parent
        if new_ok and not old_ok:
            keep = folder / "_previous" / stamp
            keep.mkdir(parents=True, exist_ok=True)
            for old in old_cvs:
                for sibling in folder.glob(old.stem + ".*"):
                    shutil.move(str(sibling), str(keep / sibling.name))
            for new in stage.iterdir():
                shutil.move(str(new), str(folder / new.name))
            print("replaced  %s (old CV kept in _previous/%s/)" % (name, stamp))
        shutil.rmtree(stage, ignore_errors=True)
    print("\nOnly CVs that failed before and pass now were replaced. Open each one and read it "
          "before sending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
