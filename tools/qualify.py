#!/usr/bin/env python3
"""How qualified the career data says they are for one posting: a 0-100 score
with every point explained.

The pipeline's `score` was a number typed in by hand, or by a /fit session,
and 45 of 48 entries had none. This computes one from what the app already
knows, the same way every time, with no model involved:

    Requirements  60   each requirement line in the posting, marked against
                       the CV the Build panel would make: covered by that CV
                       (full credit), in career.json but not on that CV (0.6,
                       it can be added), or a gap (none). Personal qualities
                       ("reliable", "team player") are not counted.
    Lead clarity  15   how clearly one thread owns the posting: the Lead's
                       match against the runner-up in the same base.
    Orientation   10   people versus systems work (prescreen), counted only
                       where the Lead is about people: enablement, teaching.
                       It catches the "AI Enablement" title trap.
    Evidence      15   a portfolio piece registered for the Lead thread in
                       evidence.json: ready to show 100, needs work 60.

A part that cannot be judged (no requirement lines found, a Lead where
orientation does not apply) is left out and its weight shared by the rest,
rather than guessed. Conditions of the job - contract rather than employment,
relocation, required German - are not qualifications: they are returned as
`flags`, to check first, and do not move the number.

A score from a /fit review overrides this one (score_source "fit"), and so does
a number typed in the pipeline card ("manual"). Recomputing never overwrites
either.

    python3 tools/qualify.py <slug-or-id>       one entry, with the breakdown
    python3 tools/qualify.py --all              score every open entry that has a posting
    python3 tools/qualify.py posting.txt --title "Customer Success Manager"
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "render"))
sys.path.insert(0, str(ROOT / "web"))

WEIGHTS = {"requirements": 60, "lead": 15, "orientation": 10, "evidence": 15}
CREDIT = {"covered": 1.0, "available": 0.6, "gap": 0.0}
OVERRIDES = {"fit", "manual"}
NICE = re.compile(r"(is a plus|nice.to.have|a bonus|bonus points|preferred|ideally|"
                  r"w\u00fcnschenswert|von vorteil|idealerweise|ein plus)", re.I)


def _orientation_value(text):
    head = (text or "").split(" ")[0]
    return {"PEOPLE": 100, "MIXED": 60, "SYSTEMS": 20}.get(head)


def qualify(posting, title="", ctx=None, weights=None):
    """{"score", "parts": [...], "flags": [...], "lead", "base"} for one posting."""
    import cv_builder as B
    import cv_suggest as S
    import prescreen
    weights = dict(WEIGHTS, **(weights or {}))
    ctx = ctx or B.load_context()
    ctx = dict(ctx, posting_terms=B.posting_terms(posting, ctx))
    sug = S.suggest(posting, title, ctx=ctx)
    spec = sug["spec"]
    lead = B.lead_of(spec)
    parts = []

    # Requirements, against the CV this posting would actually get.
    all_reqs = S.requirements(posting, spec, ctx, limit=10)
    reqs = [r for r in all_reqs if r["status"] in CREDIT]
    if not all_reqs:
        return {"score": None, "parts": [], "flags": [], "lead": lead, "base": spec["base"],
                "why": "No requirement lines could be read from this posting, so there is "
                       "nothing to score against. Run /fit, or type a score in the card.",
                "date": datetime.date.today().isoformat()}
    if reqs:
        # A nice-to-have counts half, whichever way it goes.
        w = [0.5 if NICE.search(r["text"]) else 1.0 for r in reqs]
        n = {k: sum(1 for r in reqs if r["status"] == k) for k in CREDIT}
        value = 100 * sum(CREDIT[r["status"]] * x for r, x in zip(reqs, w)) / sum(w)
        parts.append({"key": "requirements", "label": "Requirements", "value": round(value),
                      "why": "%d of %d covered by the CV, %d more in your data, %d gap(s)"
                             % (n["covered"], len(reqs), n["available"], n["gap"])
                             + (" (nice-to-haves count half)" if min(w) < 1 else ""),
                      "items": [{"text": r["text"][:140], "status": r["status"],
                                 "note": r.get("note", ""), "nice": x < 1}
                                for r, x in zip(reqs, w)]})
    else:
        parts.append({"key": "requirements", "label": "Requirements", "value": 100,
                      "why": "the posting asks only for personal qualities (%d), nothing you "
                             "could lack on paper" % len(all_reqs), "items": []})

    # Lead clarity: the Lead against the runner-up in its own base.
    rows = sorted(((t["id"], S.score_thread(t, title, posting)[0]) for t in ctx["threads"]["threads"]
                   if t["base"] == spec["base"]), key=lambda x: -x[1])
    top = rows[0][1] if rows else 0
    second = rows[1][1] if len(rows) > 1 else 0
    if top <= 0:
        value, why = 0, "no thread's targets or vocabulary appear in the posting"
    else:
        margin = (top - second) / top
        # A strong match that is shared still counts for something: a posting
        # that is plainly enablement and a little AI is not a weak fit.
        value = min(100, 40 + 60 * min(1.0, margin / 0.5)) if top >= 6 else 30 * top / 6
        why = "%s leads (%d) over %s (%d)" % (lead, top, rows[1][0] if len(rows) > 1 else "-", second)
    parts.append({"key": "lead", "label": "Lead clarity", "value": round(value), "why": why})

    pre = prescreen.screen(posting, title)
    # Only where the Lead is about people (threads.json "people_focused").
    if (ctx["by_id"].get(lead) or {}).get("people_focused"):
        o = _orientation_value(pre["orientation"])
        if o is not None:
            parts.append({"key": "orientation", "label": "People or systems", "value": o,
                          "why": pre["orientation"].split(" - ")[-1].rstrip(".")})

    ev = {} if spec["base"] == "service" else json.loads((ROOT / "profile" / "evidence.json").read_text(encoding="utf-8"))
    # Most specific first: a piece tagged for this thread alone says more about
    # it than one tagged for three.
    if spec["base"] == "service":
        mine = None  # nobody expects a portfolio for a service job
    else:
        mine = sorted((a for a in ev.get("artifacts", []) if lead in (a.get("threads") or [])),
                      key=lambda a: len(a.get("threads") or []))
    ready = [a for a in mine or [] if a.get("shareable") in ("public", "private-ok")]
    if mine is None:
        pass
    elif ready:
        value, why = 100, "ready to show: " + ", ".join(a["name"] for a in ready[:3])
    elif mine:
        value, why = 60, "exists but needs work before showing: " + ", ".join(a["name"] for a in mine[:3])
    else:
        value, why = 0, "no portfolio piece registered for %s" % lead
    if mine is not None:
        parts.append({"key": "evidence", "label": "Evidence", "value": value, "why": why})

    total_w = sum(weights[p["key"]] for p in parts)
    for p in parts:
        p["weight"] = round(100 * weights[p["key"]] / total_w)
    score = round(sum(p["value"] * weights[p["key"]] for p in parts) / total_w)
    flags = [{"gate": g["gate"], "note": g["note"], "matched": g["matched"]}
             for g in pre.get("gates_triggered", [])]
    if pre.get("title_trap"):
        flags.append({"gate": "title_trap", "matched": "",
                      "note": "The title reads like your work; the body reads like systems "
                              "configuration. Read the accountabilities."})
    return {"score": score, "parts": parts, "flags": flags, "lead": lead, "base": spec["base"],
            "date": datetime.date.today().isoformat()}


def apply_to_entry(entry, result):
    """Store the result on a pipeline entry. The shown `score` follows it unless
    a /fit review or a typed number set it."""
    entry["qualification"] = result
    if result["score"] is not None and entry.get("score_source") not in OVERRIDES:
        entry["score"] = result["score"]
        entry["score_source"] = "auto"
        if entry.get("stage") in ("found", "screened"):
            entry["stage"] = "scored"
    return entry


def score_entry(server, entry, ctx=None):
    posting = server.saved_posting(server.app_dir(entry["id"]))
    if not posting:
        return None
    res = qualify(posting, entry.get("role", ""), ctx=ctx, weights=server_weights(server))
    # Which posting this score is for, so a changed or newly added posting is
    # noticed and rescored (server.score_stale).
    res["posting_mtime"] = posting_mtime(server, entry)
    return res


def posting_mtime(server, entry):
    p = server.app_dir(entry["id"]) / "posting.txt"
    return int(p.stat().st_mtime) if p.exists() else None


def server_weights(server):
    s = server.load_json(server.PROFILE / "app_settings.json", {})
    w = (s.get("thresholds") or {}).get("weights") or {}
    return {k: int(v) for k, v in w.items() if k in WEIGHTS and str(v).isdigit()}


def show(result, head=""):
    if head:
        print(head)
    if result["score"] is None:
        print("  no score: %s" % result["why"])
        return
    print("  score %d   (Lead %s, %s base)" % (result["score"], result["lead"], result["base"]))
    for p in result["parts"]:
        print("  %-18s %3d x %2d%%   %s" % (p["label"], p["value"], p["weight"], p["why"]))
        for it in p.get("items", []):
            print("      %-9s %s%s" % (it["status"], it["text"][:90],
                                      ("  (%s)" % it["note"][:60]) if it["note"] else ""))
    for f in result["flags"]:
        print("  CHECK  %s: %s" % (f["gate"], f["note"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="pipeline id or slug, or a posting file")
    ap.add_argument("--title", default="")
    ap.add_argument("--all", action="store_true", help="score every open entry with a posting")
    args = ap.parse_args(argv)

    import server
    if args.target and Path(args.target).is_file():
        show(qualify(Path(args.target).read_text(encoding="utf-8"), args.title,
                     weights=server_weights(server)))
        return 0
    import cv_builder as B
    ctx = B.load_context()
    with server.PIPELINE_LOCK:
        entries = server.load_pipeline()
        done = 0
        for e in entries:
            if args.all:
                if e.get("outcome") in server.TERMINAL or e.get("stage") == "closed":
                    continue
            elif not args.target or args.target not in (e["id"], server.app_dir(e["id"]).name):
                continue
            res = score_entry(server, e, ctx)
            if res is None:
                if not args.all:
                    sys.exit("no saved posting for %s" % e["id"])
                continue
            apply_to_entry(e, res)
            done += 1
            if args.all:
                kept = "" if e.get("score_source") in ("auto", None) else "   (shown: %s %s)" % (
                    e["score_source"], e["score"])
                print("%3s  %-60s%s" % ("-" if res["score"] is None else res["score"], (e["company"] + " - " + e["role"])[:60], kept))
            else:
                show(res, "%s - %s" % (e["company"], e["role"]))
        server.save_pipeline(entries)
    if not done:
        print("nothing scored" + ("" if args.all else ": no such entry"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
