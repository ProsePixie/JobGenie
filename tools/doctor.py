#!/usr/bin/env python3
"""Check that everything JobGenie needs is installed, and say how to fix what is not.

    python3 tools/doctor.py

Exit 0 when every required item is present, 1 otherwise. The `claude` CLI is
optional: only the AI steps (letter drafting, fit analysis, /setup) need it.
"""

import json
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "render"))

FIX = {
    "python": {"Windows": "Install Python 3.10+ from python.org (tick 'Add to PATH').",
               "Darwin": "brew install python", "Linux": "Install python3 from your package manager."},
    "chrome": {"Windows": "Install Chrome or Edge, or set CHROME_PATH to chrome.exe.",
               "Darwin": "Install Google Chrome, or set CHROME_PATH.",
               "Linux": "Install chromium (e.g. apt install chromium), or set CHROME_PATH. "
                        "In a container, also set CHROME_NO_SANDBOX=1."},
    "pdftotext": {"Windows": "Install Git for Windows (it ships pdftotext), or poppler for Windows.",
                  "Darwin": "brew install poppler", "Linux": "apt install poppler-utils"},
    "pdfunite": {"Windows": "Optional: poppler for Windows, only for a merged PDF.",
                 "Darwin": "brew install poppler", "Linux": "apt install poppler-utils"},
    "claude": {"Windows": "Optional: install Claude Code (claude.com/claude-code) for the AI steps.",
               "Darwin": "Optional: install Claude Code (claude.com/claude-code) for the AI steps.",
               "Linux": "Optional: install Claude Code (claude.com/claude-code) for the AI steps."},
    "profile": {"*": "Run /setup in Claude Code, or: python3 tools/new_profile.py (to start from "
                     "the example) - or cp -r profile.example profile to try the fictional user."},
    "market": {"*": "profile/market.json needs home_places and cv_languages. /setup writes it; "
                    "see profile.example/market.json for the shape."},
}


def fix(key):
    table = FIX[key]
    return table.get(platform.system()) or table.get("*") or next(iter(table.values()))


def checks(root=ROOT):
    """[(name, ok, required, detail)]"""
    import render as R
    out = []
    v = sys.version_info
    out.append(("python", v >= (3, 10), True, "Python %d.%d" % (v.major, v.minor)))
    chrome = R.find_chrome()
    out.append(("chrome", bool(chrome), True, chrome or "not found"))
    ptt = R.find_pdftotext()
    out.append(("pdftotext", bool(ptt), True, ptt or "not found"))
    unite = R.find_poppler("pdfunite")
    out.append(("pdfunite", bool(unite), False, unite or "not found (only needed for a merged PDF)"))
    cl = shutil.which("claude")
    out.append(("claude", bool(cl), False, cl or "not found (only needed for the AI steps)"))
    prof = root / "profile" / "career.json"
    out.append(("profile", prof.exists(), True, str(prof) if prof.exists() else "no profile/ yet"))
    market_ok, detail = False, "missing"
    mpath = root / "profile" / "market.json"
    if mpath.exists():
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
            market_ok = bool(m.get("home_places") or m.get("home_countries")) and bool(m.get("cv_languages"))
            detail = "home: %s; CV languages: %s" % (
                ", ".join((m.get("home_places") or []) + (m.get("home_countries") or [])) or "none",
                ", ".join(m.get("cv_languages") or []) or "none")
        except ValueError:
            detail = "not valid JSON"
    out.append(("market", market_ok, True, detail))
    return out


def main():
    results = checks()
    failed = False
    for name, ok, required, detail in results:
        mark = "OK     " if ok else ("MISSING" if required else "absent ")
        print("%s %-10s %s" % (mark, name, detail))
        if not ok:
            print("        -> %s" % fix(name))
            failed = failed or required
    print("\nReady." if not failed else "\nFix the MISSING items above, then run this again.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
