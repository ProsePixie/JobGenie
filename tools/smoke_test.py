#!/usr/bin/env python3
"""Build every thread as Lead, through the real builder, and verify each CV.

The CV builder (render/cv_builder.py) is the only way a CV is made since the
switch-over from personas. This builds every thread in profile/threads.json
as Lead on its own base, in its base's language, and every professional thread
in German as well, then runs each through render/ats_check.py: the text layer,
the chronology, and the substance gate. Nothing is written outside a
throwaway folder, which is removed afterwards.

It exists because a manual check once passed while the real flow was broken,
and because a German CV leaves out bullets with no text_de: an AI-led German
CV once came out with a single bullet and nothing noticed.

    py tools/smoke_test.py
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "render"))


def smoke_builder(server):
    """The CV builder: every thread as Lead on its own base, the other threads
    off, built with page fitting and run through ats_check (text layer and the
    substance gate). Returns the failures as 'builder/<thread>'."""
    import shutil as _shutil
    sys.path.insert(0, str(ROOT / "render"))
    import cv_builder  # noqa: E402
    ctx = cv_builder.load_context()
    out_root = ROOT / "applications" / "_smoke_builder"
    failures = []
    # Each thread as Lead in its base's own language, and every professional
    # thread in German too: a German CV leaves out bullets with no text_de, and
    # an AI-led German CV once came out with a single bullet, untested.
    runs = [(t, None) for t in ctx["threads"]["threads"]]
    runs += [(t, "de") for t in ctx["threads"]["threads"] if t["base"] == "professional"]
    for t, lang in runs:
        spec = cv_builder.default_spec(t["base"], lang=lang, lead=t["id"], ctx=ctx)
        label = "%s%s" % (t["id"], "/de" if lang else "")
        print("== builder: %s base, Lead %s, %s ==" % (t["base"], t["id"], spec["lang"]))
        res = cv_builder.build(spec, out_root / label.replace("/", "-"), "smoketest", ctx=ctx)
        ok = bool(res.get("ok") and res.get("pdf"))
        if ok:
            check = server.run([server.PY, "render/ats_check.py", res["pdf"],
                                "--max-pages", str(res["max_pages"])])
            ok = check["ok"]
            if not ok:
                for line in check["out"].splitlines():
                    if "FAIL" in line:
                        print("    %s" % line.strip())
        print("  %s  %s page(s), %d bullets" % ("PASS" if ok else "FAIL", res.get("pages"),
                                                len(res.get("shown_bullets", []))))
        if not ok:
            failures.append("builder/%s" % label)
    _shutil.rmtree(out_root, ignore_errors=True)
    return failures


def main():
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    import server  # noqa: E402  after sys.path is set up above

    # Builds copy nothing to the Desktop, but a test must never write outside
    # the project whatever changes later.
    server.sync_to_desktop = lambda *a, **k: None

    failures = smoke_builder(server)
    print()
    if failures:
        print("%d build(s) FAILED: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("Every thread built as Lead, in its base's language and professional threads in "
          "German too, and passed ats_check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
