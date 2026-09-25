#!/usr/bin/env python3
"""Propose career.json entries from a LinkedIn data export. Proposes; never writes.

    python3 tools/import_linkedin.py inbox/linkedin-export/
    python3 tools/import_linkedin.py inbox/linkedin-export/ --json > proposals.json

Reads Positions.csv, Education.csv, Skills.csv and Certifications.csv when
present and prints proposed roles, education, skills and certifications in
career.json's shapes, each marked "status": "proposed". /setup shows them to
the user one at a time; only a confirmed fact is written, through
tools/careerdata.py (CLAUDE.md hard rule 2).

Never opened: Connections.csv, messages, or anything else in the export. A
connections list is personal data about other people; tools/warm_path.py
searches it locally and prints matches only.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
READ = ("Positions.csv", "Education.csv", "Skills.csv", "Certifications.csv")


def ym(value):
    """'Mar 2021' -> '2021-03', '2021' -> '2021', '' -> 'present' is left to the caller."""
    value = (value or "").strip()
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{4})$", value)
    if m and m.group(1).lower() in MONTHS:
        return "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()])
    m = re.match(r"^(\d{4})-(\d{1,2})", value)
    if m:
        return "%s-%02d" % (m.group(1), int(m.group(2)))
    m = re.match(r"^(\d{4})$", value)
    return m.group(1) if m else ""


def slug(*parts):
    s = re.sub(r"[^a-z0-9]+", "-", " ".join(p for p in parts if p).lower()).strip("-")
    return s[:40] or "entry"


def rows(folder, name):
    path = Path(folder) / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        # LinkedIn sometimes puts a notes preamble above the header row.
        lines = fh.read().splitlines()
    start = next((i for i, l in enumerate(lines) if "," in l and not l.startswith("Notes")), 0)
    return list(csv.DictReader(lines[start:]))


def get(row, *keys):
    for k in keys:
        for rk, v in row.items():
            if rk and rk.strip().lower() == k.lower() and v:
                return v.strip()
    return ""


def propose(folder):
    out = {"roles": [], "education": [], "skills": [], "certifications": []}
    ids = set()
    for r in rows(folder, "Positions.csv"):
        org, title = get(r, "Company Name", "Company"), get(r, "Title")
        if not (org or title):
            continue
        rid = slug(org)
        while rid in ids:
            rid += "-2"
        ids.add(rid)
        desc = [l.strip(" -•\t") for l in re.split(r"[\n•]+", get(r, "Description")) if l.strip(" -•\t")]
        out["roles"].append({
            "status": "proposed", "id": rid, "title": title, "org": org,
            "start": ym(get(r, "Started On", "Start Date")),
            "end": ym(get(r, "Finished On", "End Date")) or "present",
            "location": get(r, "Location"),
            "bullet_suggestions": desc,
            "_note": "Each bullet suggestion must be confirmed and tagged with threads before it is "
                     "written; numbers only if the user confirms them.",
        })
    for r in rows(folder, "Education.csv"):
        school = get(r, "School Name", "School")
        if not school:
            continue
        out["education"].append({
            "status": "proposed", "id": slug(school, get(r, "Degree Name", "Degree")),
            "degree": get(r, "Degree Name", "Degree"), "institution": school,
            "field": get(r, "Field Of Study", "Field of Study"),
            "start": ym(get(r, "Start Date", "Started On")),
            "end": ym(get(r, "End Date", "Finished On"))})
    out["skills"] = [{"status": "proposed", "name": get(r, "Name", "Skill")}
                     for r in rows(folder, "Skills.csv") if get(r, "Name", "Skill")]
    for r in rows(folder, "Certifications.csv"):
        name = get(r, "Name")
        if name:
            out["certifications"].append({
                "status": "proposed", "id": slug(name), "name": name,
                "issuer": get(r, "Authority", "Issuer"),
                "year": ym(get(r, "Started On", "Issued On"))})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="the unzipped LinkedIn export")
    ap.add_argument("--json", action="store_true", help="print proposals as JSON")
    args = ap.parse_args(argv)
    if not Path(args.folder).is_dir():
        print("no such folder: %s" % args.folder)
        return 1
    found = [n for n in READ if (Path(args.folder) / n).exists()]
    if not found:
        print("None of %s in %s. Unzip the export first." % (", ".join(READ), args.folder))
        return 1
    p = propose(args.folder)
    if args.json:
        print(json.dumps(p, indent=2, ensure_ascii=False))
        return 0
    print("Proposals from %s (nothing written; /setup confirms each one):\n" % ", ".join(found))
    for r in p["roles"]:
        print("ROLE   %s, %s  %s - %s  %s" % (r["title"], r["org"], r["start"], r["end"], r["location"]))
        for b in r["bullet_suggestions"]:
            print("         ? %s" % b)
    for e in p["education"]:
        print("EDU    %s, %s  %s - %s" % (e["degree"], e["institution"], e["start"], e["end"]))
    for c in p["certifications"]:
        print("CERT   %s (%s, %s)" % (c["name"], c["issuer"], c["year"]))
    if p["skills"]:
        print("SKILLS %s" % ", ".join(s["name"] for s in p["skills"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
