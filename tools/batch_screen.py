#!/usr/bin/env python3
"""Triage a batch of job postings mechanically, before any model reads them.

The Indeed connector returns dozens of results per search. Reading all of them
costs more than it is worth, and reading them by title is how the Jobgether
posting nearly got through. This screens every posting against the hard gates,
the people-to-systems orientation, the title trap, and the watchlist, then
returns a short ranked list worth actually reasoning about.

Input is JSON (array) or JSONL, one object per posting:

    {"id": "...", "title": "...", "company": "...", "location": "...",
     "url": "...", "body": "full posting text"}

Only `title` and `body` are required. Anything already seen in a previous run
is skipped, so this is safe to re-run daily.

Usage
    py tools/batch_screen.py jobs.json
    py tools/batch_screen.py jobs.json --all          # ignore the seen history
    py tools/batch_screen.py jobs.json --min 35       # widen the shortlist
    py tools/batch_screen.py jobs.json --json         # machine-readable

The score here is a PRE-FILTER, not a fit score. It decides what is worth
opening. /fit decides what is worth applying to.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prescreen import screen  # noqa: E402

SEEN = ROOT / "data" / "jobs-seen.jsonl"
WATCHLIST = ROOT / "profile" / "watchlist.json"

# Gates that cannot be cleared by any amount of good fit.
FATAL_GATES = {"german_required": 30, "relocation": 30, "clearance_or_citizenship": 30,
               "commodity_role": 35}
SOFT_GATES = {"contract_not_employment": 8, "undisclosed_employer": 10, "ai_screened": 2}


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def fingerprint(job):
    """Company plus title. Boards repost the same role with new ids."""
    return "%s::%s" % (norm(job.get("company")), norm(job.get("title")))


def load_jobs(path):
    raw = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if raw.startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def load_seen():
    if not SEEN.exists():
        return set()
    out = set()
    for line in SEEN.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.add(json.loads(line)["fingerprint"])
            except (ValueError, KeyError):
                continue
    return out


def load_watchlist():
    if not WATCHLIST.exists():
        return set(), [], [], []
    w = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    companies = set()
    for cat in w.get("categories", {}).values():
        for c in cat.get("companies", []):
            companies.add(norm(c["name"]))
    terms = w.get("search_terms", {})
    # Only unconditional avoid entries. Several are written as "X (when the body
    # is Y)", and stripping the condition turned a warning about one posting into
    # a blanket penalty on every posting sharing that title, including good ones.
    avoid = [norm(t) for t in terms.get("avoid", {}).get("terms", []) if "(" not in t]
    return (companies, [norm(t) for t in terms.get("primary", [])],
            [norm(t) for t in terms.get("secondary", [])], avoid)


def triage(job, result, watch):
    """0-100 pre-filter score, with every adjustment recorded."""
    companies, primary, secondary, avoid = watch
    score, why = 50, []

    orientation = result["orientation"]
    if orientation.startswith("PEOPLE"):
        score += 20
        why.append("+20 people-oriented")
    elif orientation.startswith("SYSTEMS"):
        # IT-support and administrator work is a deliberate target (the Service
        # base's Technical thread), so a posting it leads is not penalized for
        # being systems work, by the builder's view or by its title alone.
        by_title = result.get("thread_by_title") or {}
        if (result.get("base") == "service" and result.get("lead_thread") == "svc-technical") or \
                (by_title.get("id") == "svc-technical" and by_title.get("overlap", 0) >= 0.5):
            why.append("systems-oriented, but a Service technical target")
        else:
            score -= 25
            why.append("-25 systems-oriented")

    if result["title_trap"]:
        score -= 20
        why.append("-20 title trap")

    company = norm(job.get("company"))
    if company and company in companies:
        score += 15
        why.append("+15 on watchlist")

    title = norm(job.get("title"))
    if any(t and t in title for t in primary):
        score += 10
        why.append("+10 primary target title")
    elif any(t and t in title for t in secondary):
        score += 5
        why.append("+5 secondary target title")

    if any(a and a in title for a in avoid if len(a) > 6):
        score -= 15
        why.append("-15 title on the avoid list")

    for gate in result["gates_triggered"]:
        key = gate["gate"]
        if key in FATAL_GATES:
            score -= FATAL_GATES[key]
            why.append("-%d %s" % (FATAL_GATES[key], key))
        elif key in SOFT_GATES:
            score -= SOFT_GATES[key]
            why.append("-%d %s" % (SOFT_GATES[key], key))

    return max(0, min(100, score)), why


def bucket(score):
    if score >= 60:
        return "REVIEW"
    if score >= 35:
        return "BORDERLINE"
    return "SKIP"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jobs", help="JSON array or JSONL of postings")
    ap.add_argument("--all", action="store_true", help="ignore the seen history")
    ap.add_argument("--min", type=int, default=35,
                    help="lowest score to display (default 35)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    jobs = load_jobs(args.jobs)
    seen = set() if args.all else load_seen()
    watch = load_watchlist()

    rows, skipped_seen, no_body = [], 0, []
    for job in jobs:
        fp = fingerprint(job)
        if fp in seen:
            skipped_seen += 1
            continue
        seen.add(fp)
        body = job.get("body") or ""
        if not body.strip():
            # Reported, not dropped silently: a posting with no text cannot be
            # screened, and it vanishing from the counts hid a broken fetch.
            no_body.append(job)
            continue
        result = screen(body, job.get("title", ""))
        score, why = triage(job, result, watch)
        rows.append({
            "fingerprint": fp,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": job.get("url", ""),
            "score": score,
            "bucket": bucket(score),
            "why": why,
            "orientation": result["orientation"].split(" -")[0],
            "title_trap": result["title_trap"],
            "gates": [g["gate"] for g in result["gates_triggered"]],
            "gaps": result["requirement_terms_not_in_profile"][:8],
            "thread": result["thread_by_title"]["id"],
            "base": result.get("base"),
            "lead_thread": result.get("lead_thread"),
        })

    rows.sort(key=lambda r: -r["score"])

    SEEN.parent.mkdir(parents=True, exist_ok=True)
    with SEEN.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if args.as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0

    shown = [r for r in rows if r["score"] >= args.min]
    print("%d new, %d already seen, %d above the %d cutoff\n"
          % (len(rows), skipped_seen, len(shown), args.min))
    if no_body:
        print("%d posting(s) had no text and could not be screened. Fetch their "
              "bodies and re-run:" % len(no_body))
        for job in no_body[:10]:
            print("  %-38s %s" % ((job.get("title") or "")[:38], job.get("url") or ""))
        print()

    for r in shown:
        print("  %3d  %-9s %-38s %s"
              % (r["score"], r["bucket"], r["title"][:38], r["company"][:28]))
        print("       %-9s %s" % (r["orientation"].lower(), ", ".join(r["why"])))
        if r["gates"]:
            print("       gates:  %s" % ", ".join(r["gates"]))
        if r["gaps"]:
            print("       gaps:   %s" % ", ".join(r["gaps"]))
        if r["url"]:
            print("       %s" % r["url"])
        print()

    auto = [r for r in rows if r["score"] < args.min]
    if auto:
        print("auto-skipped (%d):" % len(auto))
        for r in auto:
            reason = ", ".join(r["why"]) or "no positive signal"
            print("  %3d  %-38s %-24s %s"
                  % (r["score"], r["title"][:38], r["company"][:24], reason))

    print("\nPre-filter only. Run /fit on anything in REVIEW before drafting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
