#!/usr/bin/env python3
"""Start your own profile/: the example's structure with the fictional person removed.

    python3 tools/new_profile.py

Writes profile/ from profile.example/ with every fact cleared to TODO or empty:
no roles, projects, education, certifications, skills or evidence; identity
fields TODO; market.json with no home set. threads.json keeps the example
threads as a starting point for /setup to replace. notes.md, evaluation.md and
writing-style.md are copied as-is: they are instructional/TODO content, not
personal data, and /setup fills in their remaining TODOs (voice preferences)
directly. Creates profile/private/ with an empty leak-terms.txt. Refuses if
profile/ already exists: it never overwrites data.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "profile.example"
PROFILE = ROOT / "profile"


def blank_career(example):
    ident = {k: "TODO" for k in ("name", "email", "phone", "city", "location", "work_authorization")}
    ident["_tier"] = "public"
    ident["links"] = {"linkedin": "TODO"}
    return {"_doc": "Your career data. Filled by /setup, one confirmed fact at a time; edit "
                    "with tools/careerdata.py or the Career data tab, never by hand.",
            "identity": ident, "roles": [], "projects": [], "education": [], "certifications": [],
            "skills": {}, "languages": []}


def create(example=EXAMPLE, profile=PROFILE):
    if profile.exists():
        raise FileExistsError("%s already exists; nothing was changed" % profile)
    shutil.copytree(example, profile)
    (profile / "career.json").write_text(
        json.dumps(blank_career(json.loads((example / "career.json").read_text())), indent=2) + "\n",
        encoding="utf-8")
    (profile / "evidence.json").write_text(json.dumps(
        {"_doc": "Portfolio registry: what you can show, and what it proves.", "artifacts": []},
        indent=2) + "\n", encoding="utf-8")
    m = json.loads((profile / "market.json").read_text(encoding="utf-8"))
    m.update({"home_places": [], "home_countries": [], "wide_regions": [], "us_home": False,
              "cv_languages": ["en"], "language_gates": []})
    (profile / "market.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    private = profile / "private"
    private.mkdir(exist_ok=True)
    (private / "leak-terms.txt").touch()
    return profile


def main():
    try:
        path = create()
    except FileExistsError as exc:
        print(exc)
        return 1
    print("Created %s. Next: open this folder in Claude Code and run /setup." % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
