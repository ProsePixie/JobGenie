#!/usr/bin/env python3
"""Local web UI for the job search system.

Standard library only, in keeping with the rest of the project. This is a thin
driver: it shells out to the existing scripts rather than reimplementing any of
them, so there is exactly one copy of the rendering and screening logic and the
UI cannot drift from the command line.

    python3 web/server.py            start and open a browser
    python3 web/server.py --no-open  start without opening a browser
    python3 web/server.py --port N   use a different port

Binds to 127.0.0.1 only. It runs subprocesses, so it must never be reachable
from the network. Every operation is whitelisted; nothing accepts a free-form
command, and every path is checked to be inside the project before it is used.

Close the console window to stop the server.
"""

import argparse
import datetime
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PROFILE = ROOT / "profile"
DATA = ROOT / "data"
APPS = ROOT / "applications"

PY = sys.executable
TIMEOUT = 180

# ThreadingHTTPServer runs every request on its own thread, and every
# pipeline-mutating endpoint follows the same load-all / mutate / save-all
# pattern (load_pipeline() -> change one entry -> save_pipeline()). Each
# individual save is already atomic (temp file + os.replace), but nothing
# serialized the read...write cycle itself: two overlapping requests for the
# same entry (the exact "a slow Save click racing a Log click" scenario
# api_pipeline_log's own docstring describes) could both load the same
# starting snapshot, and whichever save ran second would silently discard
# the first request's change. This lock is acquired for the full
# read-modify-write cycle in every api_pipeline_* function below, not just
# around the write - that is the actual race window.
PIPELINE_LOCK = threading.Lock()
# A headless drafting session reads CLAUDE.md, career.json, evidence.json and
# the posting before it writes anything - slower than any other subprocess
# this server runs, and worth a timeout of its own rather than raising the
# shared one every fast operation would then also wait out.
DRAFT_TIMEOUT = 600


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default if default is not None else {}


def load_jsonl(path):
    out = []
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def inside_project(path):
    """Guard every filesystem operation the UI can reach."""
    try:
        Path(path).resolve().relative_to(ROOT)
        return True
    except (ValueError, OSError):
        return False


# ---- the app log: what happened, in plain words ----------------------------
#
# One line per action, newest last, in data/app-log.txt, with the reason
# underneath when something failed. It records what was done and whether it
# worked, never the content: no posting text, no career data, no letter body.
# Kept in data/ so a development session can read it too.
APP_LOG = DATA / "app-log.txt"
APP_LOG_MAX = 512 * 1024
_LOG_LOCK = threading.Lock()

ACTION_NAMES = {
    "/api/letter": "Render letter", "/api/letter/draft": "Draft letter with AI",
    "/api/fit/analyze": "Analyze fit (AI)", "/api/screen": "Screen a posting",
    "/api/package": "Package for sending", "/api/posting/save": "Save posting",
    "/api/open": "Open file", "/api/pipeline/add": "Add to pipeline",
    "/api/pipeline/update": "Update card", "/api/pipeline/qualify": "Rescore",
    "/api/pipeline/delete": "Delete card", "/api/pipeline/log": "Log activity",
    "/api/pipeline/report-wrong": "Report as wrong", "/api/sources/run": "Check for new roles",
    "/api/sources/discover": "Discover job board", "/api/sources/add": "Add job board",
    "/api/sources/toggle": "Switch job board on/off", "/api/build/state": "Open Build panel",
    "/api/build/preview": "Preview CV", "/api/build/finalize": "Finalize CV",
    "/api/build/letter": "Letter scaffold", "/api/build/summary": "Summary",
    "/api/build/translate": "Translate bullet", "/api/build/edit": "Edit bullet",
    "/api/build/save": "Save build", "/api/build/star": "Star bullet",
    "/api/build/preset": "Save preset", "/api/build/preset/load": "Load preset",
    "/api/career/bullet": "Add bullet", "/api/career/bullet/update": "Edit bullet",
    "/api/career/certification": "Add certification",
    "/api/career/certification/delete": "Delete certification",
    "/api/career/skill": "Edit skills", "/api/doc-status": "Mark document",
    "/api/import": "Import", "/api/notes/add": "Add note",
    "/api/posting/capture": "Capture posting", "/api/captures/attach": "Attach capture",
    "/api/captures/dismiss": "Dismiss capture", "/api/settings/availability": "Save availability",
    "/api/settings/company": "Edit watchlist company", "/api/settings/term": "Edit search term",
    "/api/settings/thresholds": "Save thresholds", "/api/settings/send-folder": "Save send folder",
}
# Frequent and uneventful: logged only when they fail.
CHECK_SCRIPTS = {"ats_check.py", "voice_check.py", "claim_check.py", "prescreen.py",
                 "leak_check.py", "posting_screen.py", "style_check.py"}
QUIET_ACTIONS = {"/api/build/preview", "/api/build/state", "/api/build/star"}


def app_log(level, action, subject="", detail=""):
    """Append one human-readable line (and indented detail) to the app log."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "%s  %-7s %-26s %s" % (stamp, level, action[:26], subject)
    lines = [line.rstrip()]
    for d in [x for x in str(detail or "").splitlines() if x.strip()][:12]:
        lines.append("                              " + d.rstrip()[:220])
    try:
        with _LOG_LOCK:
            APP_LOG.parent.mkdir(parents=True, exist_ok=True)
            if APP_LOG.exists() and APP_LOG.stat().st_size > APP_LOG_MAX:
                os.replace(str(APP_LOG), str(APP_LOG.with_name("app-log.1.txt")))
            with APP_LOG.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
    except OSError:
        pass  # a log that cannot be written must never break the action


def result_detail(res):
    """The reason an action failed, from whatever shape its reply took."""
    if not isinstance(res, dict):
        return ""
    bits = []
    for key in ("err", "error"):
        if res.get(key):
            bits.append(str(res[key]))
    for key in ("problems", "warnings"):
        v = res.get(key)
        if v:
            bits += ["%s: %s" % (key[:-1], x) for x in (v if isinstance(v, list) else [v])]
    for key in ("ats", "out", "log", "prescreen"):
        v = res.get(key)
        if isinstance(v, str) and ("FAIL" in v or "not found" in v or "Traceback" in v):
            bits += [l for l in v.splitlines() if "FAIL" in l or "not found" in l
                     or "Error" in l][:6]
    return "\n".join(bits)


def api_log(query):
    """The last lines of the app log, newest first, grouped by entry."""
    n = min(int((query.get("lines") or ["600"])[0] or 600), 3000)
    if not APP_LOG.exists():
        return {"ok": True, "entries": [], "path": str(APP_LOG)}
    raw = APP_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    entries = []
    for line in raw:
        if line.startswith(" ") and entries:
            entries[-1]["detail"].append(line.strip())
        elif line.strip():
            entries.append({"line": line, "detail": [],
                            "level": line[21:28].strip() if len(line) > 28 else ""})
    entries.reverse()
    return {"ok": True, "entries": entries, "path": str(APP_LOG)}


def run(cmd, stdin_text=None, timeout=None):
    """Run one of the project's scripts. List form, never shell.

    The child is forced into UTF-8. Writing to a pipe on Windows otherwise
    uses the ANSI codepage, which this end decodes as UTF-8, and every umlaut
    in a German job title comes back as a replacement character.
    """
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    effective_timeout = timeout or TIMEOUT
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, env=env,
            encoding="utf-8", errors="replace", input=stdin_text,
            timeout=effective_timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        res = {"ok": proc.returncode == 0, "code": proc.returncode,
               "out": proc.stdout or "", "err": proc.stderr or ""}
    except subprocess.TimeoutExpired:
        res = {"ok": False, "code": -1, "out": "",
               "err": "timed out after %d seconds" % effective_timeout}
    except OSError as exc:
        res = {"ok": False, "code": -1, "out": "", "err": str(exc)}
    if not res["ok"]:
        script = Path(str(next((c for c in cmd if str(c).endswith(".py")), cmd[0]))).name
        text = (res["err"] + "\n" + res["out"]).strip()
        crashed = "Traceback" in text or res["code"] not in (0, 1, 2)
        # A check that says no is an answer, not a failure: ats_check failing
        # a CV is reported by the action that asked. Logging it filled the log
        # every time Today looked at the CVs. A crash is always logged.
        if crashed or script not in CHECK_SCRIPTS:
            lines = text.splitlines()
            key = [l for l in lines if re.search(r"FAIL|Error|error|not found|refused", l)]
            app_log("script", script, "exited %s" % res["code"],
                    "\n".join((key or lines)[-8:]))
    return res


def safe_slug(text, fallback="untitled"):
    keep = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(text or ""))
    keep = "-".join(p for p in keep.split("-") if p).lower()
    # Strip after truncating, not only before: a cut landing on a dash left
    # "...-expert-", and every later safe_slug() of that name dropped the dash
    # again. Prepare wrote letter.md to one folder while Render and Draft
    # looked in its dashless twin, and reported the letter as missing.
    return keep[:60].strip("-") or fallback


# Shorter than this is not a posting. The watcher files a hit into the capture
# inbox with a one-line note ("Remote job. matched: trainer"), and filing it
# saved that note as posting.txt. Every reader then found a posting, never
# fetched the real one, and the CV builder suggested from twenty-eight
# characters: German roles came out as English CVs with no requirements.
MIN_POSTING_CHARS = 200


def saved_posting(out_dir):
    """The saved posting in an application folder, or "" when there is none
    or what is there is only a watcher's note."""
    path = Path(out_dir) / "posting.txt"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if len(text.strip()) >= MIN_POSTING_CHARS else ""


class PostingFlagged(Exception):
    """A posting containing text addressed to an AI. Never saved (hard rule 3)."""


def screen_posting(text):
    """Raise PostingFlagged if text is addressed to an AI; else the text with
    invisible characters removed. tools/posting_screen.py is the one screen."""
    sys.path.insert(0, str(ROOT / "tools"))
    from posting_screen import screen  # noqa: E402
    clean, flagged = screen(text)
    if flagged:
        raise PostingFlagged(flagged)
    return clean


def flagged_reply(passage):
    return {"ok": False, "flagged": passage,
            "err": "This posting contains text addressed to an AI, so it was not saved "
                   "and nothing was drafted from it (CLAUDE.md hard rule 3). Read it "
                   "yourself before deciding what to do:\n\n    %s" % passage}


def save_posting(entry_id, text):
    """Write the posting for an entry to the one file every reader resolves
    to the same way, via app_dir. One writer, so pipeline/add, prepare, and a
    captured posting all persist it identically. A note too short to be a
    posting is not written (see MIN_POSTING_CHARS)."""
    out_dir = app_dir(entry_id)
    if len((text or "").strip()) < MIN_POSTING_CHARS:
        return out_dir
    # Every way a posting arrives ends here, so every one is screened: pasted,
    # captured by the bookmarklet, attached from the inbox, or fetched.
    text = screen_posting(text)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "posting.txt"
    tmp = path.with_suffix(".txt.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))
    # Score it now, off the request thread: callers may hold PIPELINE_LOCK.
    threading.Thread(target=requalify, args=(entry_id,), daemon=True).start()
    return out_dir


def requalify(entry_id):
    """Recompute one entry's qualification score from its saved posting
    (tools/qualify.py). A /fit or typed score stays what the card shows."""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import qualify  # noqa: E402
        with PIPELINE_LOCK:
            entries = load_pipeline()
            e = next((x for x in entries if x["id"] == entry_id), None)
            if not e:
                return None
            res = qualify.score_entry(sys.modules[__name__], e)
            if res is None:
                return None
            qualify.apply_to_entry(e, res)
            save_pipeline(entries)
            return res
    except Exception as exc:  # noqa: BLE001 - a score is never worth failing a save over
        app_log("ERROR", "Score posting", entry_id, "%s: %s" % (type(exc).__name__, exc))
        return None


_BACKGROUND = threading.Lock()


def score_stale():
    """Score every open entry whose posting is new or changed since its last
    score. Scoring used to run only when a posting was saved through the app,
    so one written any other way (a Claude Code session, an older version) was
    never scored."""
    sys.path.insert(0, str(ROOT / "tools"))
    import qualify  # noqa: E402
    todo = []
    for e in load_pipeline():
        if infer_stage(e) == "closed" or not saved_posting(app_dir(e["id"])):
            continue
        q = e.get("qualification") or {}
        if not q or q.get("posting_mtime") != qualify.posting_mtime(sys.modules[__name__], e):
            todo.append(e["id"])
    for eid in todo:
        requalify(eid)
    if todo:
        app_log("ok", "Scored postings", "%d card(s)" % len(todo))
    return todo


def fetch_missing_postings(limit=40):
    """Fetch the posting for open entries that have only a link, so they can be
    scored and built. One at a time; each result is logged. Only the entry's own
    link is fetched, never a URL found inside a posting (hard rule 3)."""
    done = []
    for e in load_pipeline():
        if len(done) >= limit:
            break
        if (infer_stage(e) == "closed" or not (e.get("url") or "").startswith("http")
                or saved_posting(app_dir(e["id"])) or e["id"] in _POSTING_FAILED):
            continue
        text, note = fetch_and_save_posting(e)
        if not text:
            _POSTING_FAILED[e["id"]] = (time.time(), note)
        app_log("ok" if text else "FAILED", "Fetch posting", e["id"],
                "" if text else note)
        done.append(e["id"])
    return done


def background_scoring(fetch=True):
    """Fetch what is missing, then score what is stale. One run at a time."""
    if not _BACKGROUND.acquire(blocking=False):
        return
    try:
        if fetch:
            fetch_missing_postings()
        score_stale()
    except Exception as exc:  # noqa: BLE001 - never take the server down
        app_log("ERROR", "Background scoring", "", "%s: %s" % (type(exc).__name__, exc))
    finally:
        _BACKGROUND.release()


def api_qualify(body):
    """Recompute and return one entry's score and its breakdown."""
    res = requalify(body.get("id"))
    if res is None:
        return {"ok": False, "err": "No saved posting to score. Paste the posting into "
                                    "the card first."}
    return {"ok": True, "qualification": res}


def fetch_and_save_posting(entry):
    """(text, note). Fetch the posting from the entry's own link and keep it.

    Entries found by the watchers carry a link and no text, so the persona
    scorer and the letter drafter had nothing to read. See
    tools/fetch_posting.py for what is fetched, and what is refused.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    from fetch_posting import FetchError, fetch_posting  # noqa: E402
    try:
        text = fetch_posting(entry.get("url") or "")
    except FetchError as exc:
        return "", str(exc)
    try:
        save_posting(entry["id"], text)
    except PostingFlagged as exc:
        return "", flagged_reply(str(exc))["err"]
    return text, "posting fetched from %s" % entry.get("url")


GENDER_TAG = re.compile(r"\s*\((?:[mwfdxi*]\s*[/|,]\s*){1,3}[mwfdxi*]\)"
                        r"|\s*\(all genders\)|\s*\(alle geschlechter\)", re.I)


LOCATION_TAIL = re.compile(
    r"\s*(\((remote|hybrid|germany|deutschland|dach|emea|europe|eu|munich|m\u00fcnchen|"
    r"berlin|onsite|on-site|global|worldwide)[^)]*\)|[-|,]\s*(remote|hybrid|germany|dach|"
    r"emea|europe)\b.*)$", re.I)


def clean_title(role):
    """The job title a CV headline can carry: no (m/w/d) tag, and nothing
    after it. Board titles run on into the employer's legal name, and
    "Verkäufer PC / Telekommunikation (m/w/x), expert TechnoMarkt" was
    printed under the name as if it were one."""
    role = (role or "").strip()
    m = GENDER_TAG.search(role)
    if m:
        role = role[:m.start()]
    # A trailing place or work mode is not part of a title: "AI Enablement
    # Specialist (Germany)", "Customer Success Manager - Remote".
    role = LOCATION_TAIL.sub("", role)
    return role.strip(" ,-|")[:60]


def app_dir(entry_id):
    """The one way an entry id becomes an application folder path.

    entry_id() joins company and role with "--". safe_slug collapses that to
    a single dash when it is applied a second time. Every reader and writer
    of an application folder must apply safe_slug exactly once to the same
    input to land on the same folder, and four call sites doing that by hand
    is how one of them (the posting save) briefly wrote to a folder nothing
    else would ever read from. This is the only place that should call
    safe_slug on an entry id now.
    """
    return APPS / safe_slug(entry_id, "application")


def safe_filename(text, fallback="cv"):
    """Sanitize a filename stem without forcing it to lowercase.

    Application folder names go through safe_slug and lowercase is fine there;
    they are internal ids. A CV basename is what they see on the Render tab and
    what ends up as the visible file name, and "Jane_Doe_CV" silently
    becoming "jane_doe_cv.pdf" is the kind of small mismatch that reads
    as the tool being broken even though nothing failed.
    """
    keep = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("_")
    return keep[:80] or fallback


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

STAGES = ["found", "screened", "scored", "drafted", "sent", "responded",
          "interviewing", "closed"]

LOG = DATA / "applications.jsonl"

# Terminal outcomes, offered in the detail panel. Kept aligned with the values
# the outcome skill writes, so the UI and the workflow do not diverge.
OUTCOMES = ["", "pending", "skipped", "rejected-auto", "rejected-screen",
            "rejected-interview", "ghosted", "screen", "interview", "offer",
            "withdrawn", "advanced-to-final"]

# Outcomes that end an application. One of these means the card belongs in
# closed no matter what the stage field says, because the stage was written
# earlier and the outcome is the later fact.
TERMINAL = {"skipped", "rejected-auto", "rejected-screen", "rejected-interview",
            "ghosted", "offer", "withdrawn"}


def entry_id(entry):
    """Deterministic, so identity survives a read without persisting anything."""
    return "%s--%s" % (safe_slug(entry.get("company"), "co"),
                       safe_slug(entry.get("role"), "role"))


# Before Drafted: a finalized CV that passed its checks, or a packaged set, moves a
# card here. Nothing did. Every card the Build panel finished stayed in Scored,
# and the Drafted column was empty however much had been drafted. Never backwards:
# a card already sent, answered or closed stays where it is.
EARLY_STAGES = ("found", "screened", "scored")


def promote_to_drafted(entry):
    """Move one entry to Drafted if it is still before it. True when it moved."""
    outcome = (entry.get("outcome") or "").lower().strip()
    if entry.get("stage") in EARLY_STAGES and outcome not in TERMINAL:
        entry["stage"] = "drafted"
        return True
    return False


def catch_up_drafted():
    """At start-up: cards finished before promote_to_drafted existed. A card has
    been drafted when Finalize recorded its `build`, or when it was packaged
    (submit/ exists). Each move is written to the app log."""
    with PIPELINE_LOCK:
        entries = load_pipeline()
        moved = [e for e in entries
                 if (e.get("build") or (app_dir(e["id"]) / "submit").is_dir())
                 and promote_to_drafted(e)]
        if moved:
            save_pipeline(entries)
    for e in moved:
        app_log("ok", "Moved to Drafted", e["id"], "a finalized CV or package already existed")
    return [e["id"] for e in moved]


def infer_stage(entry):
    """Place a legacy entry on the board without rewriting the file to read it.

    An existing `stage` that is not one of STAGES is free text written before
    the board existed. It is moved to `stage_note` rather than overwritten:
    reusing a key for two meanings already destroyed one value once.

    A terminal outcome outranks a stored stage. Recording a rejection used to
    leave the card sitting in Interviewing, so the board claimed a live process
    that had already ended.
    """
    existing = entry.get("stage")
    outcome = (entry.get("outcome") or "").lower().strip()
    if outcome in TERMINAL:
        return "closed"
    if existing in STAGES:
        return existing
    if isinstance(existing, str) and existing.strip():
        entry.setdefault("stage_note", existing)
    if any(k in outcome for k in ("offer", "reject", "ghost", "withdraw")):
        return "closed"
    if "interview" in outcome or "advanced" in outcome:
        return "interviewing"
    if "screen" in outcome:
        return "responded"
    if entry.get("applied"):
        return "sent"
    if entry.get("score") is not None:
        return "scored"
    return "found"


def load_pipeline():
    """One entry per id. A second line for the same application - written by a
    workflow that appended instead of updating - is folded into the first:
    later non-empty values win, activity histories are joined, the original
    date is kept. The board shows one card, and the next save drops the extra
    line."""
    merged = {}
    for e in load_jsonl(LOG):
        e.setdefault("id", entry_id(e))
        first = merged.get(e["id"])
        if first is None:
            merged[e["id"]] = e
            continue
        date, activity = first.get("date"), first.get("activity") or []
        first.update({k: v for k, v in e.items() if v not in (None, "")})
        if date:
            first["date"] = date
        if activity and e.get("activity"):
            first["activity"] = activity + e["activity"]
    out = []
    for e in merged.values():
        e["stage"] = infer_stage(e)
        out.append(e)
    return out


def save_pipeline(entries):
    """Whole-file rewrite via a temp file, so a crash cannot truncate the log."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOG.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                   encoding="utf-8")
    os.replace(str(tmp), str(LOG))


def api_pipeline():
    # A posting added since the last look is scored in the background; the next
    # refresh shows it.
    threading.Thread(target=background_scoring, kwargs={"fetch": False}, daemon=True).start()
    entries = load_pipeline()
    # Which documents exist, for the CV / Letter badges on each card.
    for e in entries:
        kinds = {x["kind"] for x in docs_for(e["id"])}
        e["has_docs"] = sorted(kinds & {"cv", "letter", "letter-draft", "application"})
    return {"stages": STAGES, "outcomes": OUTCOMES, "entries": entries}


def last_touched(entry):
    """The most recent date anything happened on an entry: a field save, an
    activity line, or failing both, the day it was added. Whichever is latest,
    because logging activity should count as attention even on a day nothing
    else was saved, and vice versa."""
    candidates = [d for d in (
        entry.get("updated"),
        entry.get("date"),
        *(a.get("date", "")[:10] for a in entry.get("activity") or []),
    ) if d]
    # Each parsed on its own: one malformed date used to make the whole entry
    # undated, so it could never show up as stale.
    dates = []
    for d in candidates:
        try:
            dates.append(datetime.date.fromisoformat(str(d)[:10]))
        except ValueError:
            continue
    return max(dates) if dates else None


# (pdf path, mtime) -> (ok, failing check names). Today runs ats_check on
# every unsent CV; an unchanged file is not checked twice.
_CV_CHECKS = {}


def cv_check(pdf, max_pages=2):
    key = (str(pdf), pdf.stat().st_mtime)
    if key not in _CV_CHECKS:
        res = run([PY, "render/ats_check.py", str(pdf), "--max-pages", str(max_pages)])
        names = [line.split()[1] for line in res["out"].splitlines()
                 if line.strip().startswith("FAIL") and len(line.split()) > 1]
        _CV_CHECKS[key] = (res["ok"], names)
    return _CV_CHECKS[key]


def unready_cvs(entries):
    """Unsent applications whose CV fails today's checks. A CV rendered before
    a rule changed passes nothing new on its own; tools/rerender.py fixes it."""
    rows = []
    for e in entries:
        if e["stage"] in ("sent", "responded", "interviewing", "closed"):
            continue
        folder = app_dir(e["id"])
        cvs = sorted(p for p in folder.glob("*.pdf") if "letter" not in p.name.lower()) \
            if folder.exists() else []
        if not cvs:
            continue
        ok, names = cv_check(cvs[0])
        if not ok:
            rows.append({"id": e["id"], "company": e["company"], "role": e["role"],
                         "stage": e["stage"], "score": e.get("score"), "days": None,
                         "fails": names})
    return rows


def api_today():
    """Everything that deserves attention right now, across the whole
    pipeline, in one place - because Dashboard, Pipeline, Sources and the
    capture inbox each show a fragment of this and none of them answer "what
    do I actually do today" on their own.

    Three buckets, each a different kind of attention, kept apart rather than
    merged into one undifferentiated list:

        next_actions   something was written down to do. These are ranked by
                       how long it has sat there, not alphabetically, so the
                       one that has been waiting longest surfaces first.
        stale          an open pursuit has gone quiet with nothing planned.
                       Different from next_actions on purpose: "I meant to do
                       X" and "I forgot this existed" call for different
                       reactions, and folding them together would hide which
                       one a given entry actually is.
        top_scored     the best-fitting things not yet acted on. A score sitting
                       in a column of fifteen "found" cards is invisible; this
                       is what makes it count for something.
    """
    entries = load_pipeline()
    open_entries = [e for e in entries if e["stage"] != "closed"]
    today = datetime.date.today()
    stale_days = load_thresholds()["stale_days"]

    next_actions = []
    stale = []
    awaiting = []
    for e in open_entries:
        touched = last_touched(e)
        days = (today - touched).days if touched else None
        row = {"id": e["id"], "company": e["company"], "role": e["role"],
              "stage": e["stage"], "score": e.get("score"), "days": days}
        # Sent and silent. The outcome skill defines ghosted as no reply after
        # thirty days, and nothing surfaced it: a sent application only showed
        # up here if someone had written a next action on it.
        if e["stage"] == "sent" and days is not None and days >= 7:
            hint = ("%d days without a reply. Record it as ghosted, or follow up once "
                    "more if there is a named contact." % days if days >= 30 else
                    "%d days since it went out. A short, polite follow-up is normal now."
                    % days)
            awaiting.append(dict(row, hint=hint))
            continue
        if (e.get("next_action") or "").strip():
            next_actions.append(dict(row, next_action=e["next_action"]))
        elif days is not None and days >= stale_days:
            stale.append(row)

    # Screened or scored, and nothing written down to do: the decision to
    # pursue it was made, and then nothing followed. Shown whatever its age;
    # waiting for it to go stale costs days an early application has.
    stale_ids = {r["id"] for r in stale}
    no_next_step = [
        {"id": e["id"], "company": e["company"], "role": e["role"], "stage": e["stage"],
         "score": e.get("score"), "days": (today - last_touched(e)).days if last_touched(e) else None}
        for e in open_entries
        if e["stage"] in ("screened", "scored", "drafted")
        and not (e.get("next_action") or "").strip() and e["id"] not in stale_ids]

    next_actions.sort(key=lambda r: -(r["days"] if r["days"] is not None else 0))
    stale.sort(key=lambda r: -r["days"])

    top_scored = sorted(
        (e for e in open_entries
         if e["stage"] in ("found", "screened", "scored") and e.get("score") is not None),
        key=lambda e: -e["score"])[:5]
    top_scored = [{"id": e["id"], "company": e["company"], "role": e["role"],
                  "stage": e["stage"], "score": e["score"]} for e in top_scored]

    awaiting.sort(key=lambda r: -r["days"])

    return {
        "next_actions": next_actions[:12],
        "awaiting": awaiting[:12],
        "stale": stale[:12],
        "no_next_step": no_next_step[:12],
        "unready": unready_cvs(open_entries),
        "top_scored": top_scored,
        "captures_pending": len(load_captures()),
        "open_count": len(open_entries),
    }


# --------------------------------------------------------------------------
# UI feedback notes
#
# A floating "leave a note" control, present on every screen, for the person
# actually using this to record what is wrong the moment they hit it, without
# a live session and without losing the context that made it make sense.
# Written to markdown rather than JSON on purpose: this is read by a person
# (or an assistant reading on their behalf) later, not queried by code, and a
# plain chronological log is the right shape for that.
# --------------------------------------------------------------------------

NOTES_FILE = DATA / "ui-notes.md"


def api_notes_add(body):
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "err": "nothing to note"}
    tab = (body.get("tab") or "").strip()
    context = (body.get("context") or "").strip()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    is_new = not NOTES_FILE.exists()
    with NOTES_FILE.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("# Notes left while using the app\n\n"
                    "Each entry is where they were and what they said, in order. Read "
                    "chronologically; a later note about the same screen may "
                    "supersede an earlier one rather than add to it.\n\n")
        f.write("## %s — %s%s\n\n%s\n\n" % (
            ts, tab or "unknown screen",
            (" — " + context) if context else "", text))
    return {"ok": True}


def api_notes_count():
    if not NOTES_FILE.exists():
        return {"ok": True, "count": 0}
    return {"ok": True, "count": NOTES_FILE.read_text(encoding="utf-8").count("\n## ")}


def api_pipeline_add(body):
    try:
        if len((body.get("posting") or "").strip()) >= MIN_POSTING_CHARS:
            screen_posting(body.get("posting"))
    except PostingFlagged as exc:
        return flagged_reply(str(exc))
    company = (body.get("company") or "").strip()
    role = (body.get("role") or "").strip()
    if not company or not role:
        return {"ok": False, "err": "company and role are both required"}

    new = {
        "id": entry_id({"company": company, "role": role}),
        "date": body.get("date") or datetime.date.today().isoformat(),
        "company": company, "role": role,
        "url": (body.get("url") or "").strip(),
        "stage": body.get("stage") if body.get("stage") in STAGES else "found",
        "persona": body.get("persona") or None,
        "thread": body.get("thread") or None,
        "score": body.get("score"),
        "applied": bool(body.get("applied")),
        "outcome": body.get("outcome") or "pending",
        "outcome_date": None,
        "next_action": (body.get("next_action") or "").strip(),
        "notes": (body.get("notes") or "").strip(),
    }
    with PIPELINE_LOCK:
        entries = load_pipeline()
        if any(e["id"] == new["id"] or entry_id(e) == new["id"] for e in entries):
            return {"ok": False, "err": "already in the pipeline: %s" % new["id"]}
        entries.append(new)
        save_pipeline(entries)

    # The Screen tab is usually where a posting is first pasted in, to get a
    # fit score before deciding to apply. Without this, that text was thrown
    # away the moment the entry reached the pipeline, and Prepare application
    # would ask them to go find the posting and paste it in a second time.
    posting = (body.get("posting") or "").strip()
    if posting:
        save_posting(new["id"], posting)

    return {"ok": True, "entry": new}


EDITABLE = {"stage", "outcome", "outcome_date", "notes", "next_action", "url",
            "persona", "thread", "score", "applied", "company", "role"}


def api_pipeline_update(body):
    target = body.get("id")
    patch = body.get("patch") or {}
    with PIPELINE_LOCK:
        entries = load_pipeline()
        for e in entries:
            if e["id"] != target:
                continue
            was = (e.get("outcome") or "").lower().strip()
            old_score = e.get("score")
            for key, val in patch.items():
                if key not in EDITABLE:
                    continue
                if key == "stage" and val not in STAGES:
                    continue
                e[key] = val

            # id is frozen at creation (entry_id() is only ever computed once,
            # in api_pipeline_add) and app_dir()/api_prepare key every file off
            # it, so editing company or role here does not move the existing
            # application folder - it silently starts pointing at a name that
            # no longer matches. Surfaced rather than fixed automatically:
            # renaming the folder risks a locked file on Windows (an open PDF,
            # a render in progress), and a visible mismatch is safer than a
            # migration that can half-fail.
            folder_warning = None
            if ("company" in patch or "role" in patch):
                old_folder = app_dir(e["id"])
                if entry_id(e) != e["id"] and old_folder.exists():
                    folder_warning = (
                        "Company or role changed, but the application folder "
                        "(%s) is still named from the old values and was not "
                        "moved - anything already rendered there stays put."
                        % old_folder.name)

            # A number typed into the card is their, and recomputing never
            # overwrites it (tools/qualify.py). Clearing it hands the card
            # back to the app's own score.
            if "score" in patch and patch["score"] != old_score:
                if patch["score"] is None:
                    auto = (e.get("qualification") or {}).get("score")
                    e["score"], e["score_source"] = auto, ("auto" if auto is not None else None)
                else:
                    e["score_source"] = "manual"

            # Keep the two representations of "did it go out" from drifting apart.
            if "stage" in patch:
                if patch["stage"] in ("sent", "responded", "interviewing"):
                    e["applied"] = True
                elif patch["stage"] in ("found", "screened", "scored", "drafted"):
                    e["applied"] = False

            # Stage and outcome are two names for one truth. A terminal outcome
            # closes the card, and dragging a closed card back out is refused
            # rather than silently reverted on the next read.
            #
            # Recording the outcome and moving the card are told apart on purpose.
            # The detail panel posts stage and outcome together, so refusing on
            # the stage alone would reject the act of recording a rejection.
            outcome = (e.get("outcome") or "").lower().strip()
            if outcome in TERMINAL:
                if outcome == was and patch.get("stage") not in (None, "closed"):
                    return {"ok": False, "err":
                            "%s is a terminal outcome, so this stays in closed. "
                            "Change the outcome first if it is live again."
                            % e.get("outcome")}
                e["stage"] = "closed"
                if outcome != was and not e.get("outcome_date"):
                    e["outcome_date"] = datetime.date.today().isoformat()
            e["updated"] = datetime.date.today().isoformat()
            save_pipeline(entries)
            return {"ok": True, "entry": e, "folder_warning": folder_warning}
        return {"ok": False, "err": "no entry with id %r" % target}


def api_pipeline_log(body):
    """Append one timestamped line to an entry's activity history.

    A separate endpoint rather than routing through the generic patch
    mechanism on purpose: patch requires the caller to already hold the
    current state and send back a full replacement, which is exactly how two
    browser tabs (or a slow "Save" click racing a "Log" click) would silently
    drop each other's activity line. This reads the pipeline fresh, appends
    one entry, and writes it back, so the log is genuinely append-only rather
    than append-if-nobody-else-touched-it-first.
    """
    target = body.get("id")
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "err": "nothing to log"}

    with PIPELINE_LOCK:
        entries = load_pipeline()
        for e in entries:
            if e["id"] != target:
                continue
            e.setdefault("activity", []).append({
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "text": text[:2000],
            })
            e["updated"] = datetime.date.today().isoformat()
            save_pipeline(entries)
            return {"ok": True, "entry": e}
        return {"ok": False, "err": "no entry with id %r" % target}


def api_pipeline_delete(body):
    target = body.get("id")
    with PIPELINE_LOCK:
        entries = load_pipeline()
        kept = [e for e in entries if e["id"] != target]
        if len(kept) == len(entries):
            return {"ok": False, "err": "no entry with id %r" % target}
        save_pipeline(kept)
    return {"ok": True, "removed": target}


FALSE_POSITIVES = DATA / "false-positives.jsonl"


def api_pipeline_report_wrong(body):
    """Log a match that has nothing to do with them, and close the entry out.

    This is the durable version of what used to only happen by describing it
    in chat: point at a specific mismatch, say why, and have it land
    somewhere a future pass over the search terms and NEGATIVE lists can
    actually use - grep tools/review_false_positives.py - instead of relying
    on it being remembered or re-explained the next time the same kind of
    thing shows up.
    """
    target = body.get("id")
    reason = (body.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "err": "say why, even a couple of words - it's what makes "
                                     "this traceable to a term or a company later"}

    with PIPELINE_LOCK:
        entries = load_pipeline()
        for e in entries:
            if e["id"] != target:
                continue
            FALSE_POSITIVES.parent.mkdir(parents=True, exist_ok=True)
            with FALSE_POSITIVES.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "date": datetime.date.today().isoformat(),
                    "company": e.get("company", ""),
                    "role": e.get("role", ""),
                    "url": e.get("url", ""),
                    "persona": e.get("persona", ""),
                    "reason": reason[:500],
                    "reviewed": False,
                }, ensure_ascii=False) + "\n")
            note = "Reported as a wrong match: %s" % reason
            e["outcome"] = "skipped"
            e["outcome_date"] = datetime.date.today().isoformat()
            e["notes"] = ((e.get("notes") or "") + " " + note).strip()
            e.setdefault("activity", []).append({
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "text": note})
            e["updated"] = datetime.date.today().isoformat()
            save_pipeline(entries)
            return {"ok": True, "entry": e}
        return {"ok": False, "err": "no entry with id %r" % target}


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def api_claude_auth():
    """Whether the Claude sign-in the AI features use is still alive."""
    sys.path.insert(0, str(ROOT / "tools"))
    import claude_run  # noqa: E402
    ok, note = claude_run.logged_in()
    return {"ok": True, "logged_in": ok,
            "message": claude_run.SIGN_IN_AGAIN if ok is False else note}


def api_status():
    career = load_json(PROFILE / "career.json")
    apps = load_jsonl(DATA / "applications.jsonl")
    seen = load_jsonl(DATA / "jobs-seen.jsonl")

    needs = []
    for role in career.get("roles", []):
        for item in role.get("_needs", []):
            needs.append({"where": role.get("id", ""), "what": item})
    for item in career.get("_todo_summary", []):
        needs.append({"where": "overall", "what": item})

    bullets = sum(len(r.get("bullets", [])) for r in career.get("roles", []))
    blocked = career.get("_do_not_reintroduce", [])
    if isinstance(blocked, dict):
        blocked = [blocked]

    links = {}
    for key, val in (career.get("identity", {}).get("links") or {}).items():
        url = val.get("url") if isinstance(val, dict) else val
        links[key] = url

    return {
        "name": career.get("identity", {}).get("name", ""),
        "roles": len(career.get("roles", [])),
        "bullets": bullets,
        "certifications": len(career.get("certifications", [])),
        "applications": apps,
        "screened": len(seen),
        "needs": needs,
        "blocked": [{"claim": b.get("claim", ""), "rule": b.get("rule", "")}
                    for b in blocked if isinstance(b, dict)],
        "links": links,
    }


def api_watchlist():
    w = load_json(PROFILE / "watchlist.json")
    cats = []
    for key, cat in (w.get("categories") or {}).items():
        cats.append({
            "id": key,
            "priority": cat.get("priority", 9),
            "why": cat.get("why", ""),
            "roles": cat.get("roles_to_watch", []),
            "companies": cat.get("companies", []),
        })
    cats.sort(key=lambda c: (c["priority"], c["id"]))
    return {"categories": cats,
            "search_terms": w.get("search_terms", {}),
            "income_streams": w.get("income_streams", {}).get("streams", [])}


def api_career():
    career = load_json(PROFILE / "career.json")
    roles = []
    for r in career.get("roles", []):
        roles.append({
            "id": r.get("id"), "title": r.get("title"), "org": r.get("org"),
            "start": r.get("start"), "end": r.get("end"),
            "bullets": [{"text": b.get("text", ""), "text_de": b.get("text_de", ""),
                         "strength": b.get("strength", 2),
                         "tags": b.get("tags", []), "threads": b.get("threads", [])}
                        for b in r.get("bullets", [])],
            "needs": r.get("_needs", []),
        })
    # The threads a new bullet or certification can be tagged with: the
    # builder selects by thread, so an untagged one would never reach a CV.
    threads = [{"id": t["id"], "label": t.get("label", t["id"]), "base": t.get("base")}
               for t in load_json(PROFILE / "threads.json", {}).get("threads", [])]
    return {"roles": roles, "skills": career.get("skills", {}),
            "certifications": career.get("certifications", []), "threads": threads}


# --------------------------------------------------------------------------
# career data editor
#
# The place a new certification, a new bullet, or a skill actually belongs -
# typed in directly by the person it is true of, in the same turn they thinks
# of it, rather than routed through a conversation and a hand-edited file.
# This is hard rule 2's own instruction ("write it into career.json in the
# same turn") given a door of its own instead of relying on remembering to
# ask an assistant to do it.
# --------------------------------------------------------------------------

def api_career_certification(body):
    path = PROFILE / "career.json"
    career = load_json(path, {})
    career.setdefault("certifications", [])
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "err": "a certification needs a name"}
    problem = vet_career_text(name, (body.get("issuer") or "").strip())
    if problem:
        return {"ok": False, "err": problem}
    known_threads = {t["id"] for t in load_json(PROFILE / "threads.json", {}).get("threads", [])}
    threads = [str(t).strip() for t in (body.get("threads") or []) if str(t).strip()]
    unknown = [t for t in threads if t not in known_threads]
    if unknown:
        return {"ok": False, "err": "unknown thread id(s): %s" % ", ".join(unknown)}
    cid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "cert"
    base, n = cid, 2
    existing_ids = {c.get("id") for c in career["certifications"]}
    while cid in existing_ids:
        cid = "%s-%d" % (base, n); n += 1
    entry = {"id": cid, "name": name, "issuer": (body.get("issuer") or "").strip(),
             "year": (body.get("year") or "").strip(),
             "credential_id": (body.get("credential_id") or "").strip(),
             # The builder selects certifications by thread; one with none
             # would never appear on a CV.
             "threads": threads,
             "strength": int(body.get("strength") or 2)}
    career["certifications"].append(entry)
    save_json_atomic(path, career)
    return {"ok": True, "certification": entry}


def api_career_certification_delete(body):
    path = PROFILE / "career.json"
    career = load_json(path, {})
    before = len(career.get("certifications", []))
    career["certifications"] = [c for c in career.get("certifications", [])
                                if c.get("id") != body.get("id")]
    if len(career["certifications"]) == before:
        return {"ok": False, "err": "no certification with that id"}
    save_json_atomic(path, career)
    return {"ok": True}


def vet_career_text(*texts):
    """Why a text may not enter career.json, or None.

    career.json is the source every document is rendered from, and the editor
    wrote to it unchecked: the seven blocked fabrications in
    _do_not_reintroduce ("Docebo", "n8n", "ADDIE" ...) could be typed straight
    back in, and an em dash in a bullet would reach every CV that selects it.
    The same two checks letters get, applied at the door instead.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import claim_check  # noqa: E402
    import voice_check  # noqa: E402
    banned = claim_check.banned_phrases()
    style = voice_check.load_banned()
    for text in texts:
        if not text:
            continue
        low = text.lower()
        hit = next((p for p in banned if re.search(r"(?<!\w)%s(?!\w)" % re.escape(p), low)), None)
        if hit:
            return ("%r is on the blocked-claims list in career.json (_do_not_reintroduce). "
                    "It was removed as untrue and cannot be added back." % hit)
        fails = [f for f in voice_check.scan(text, style) if f["level"] == "FAIL"]
        if fails:
            return "breaks writing-style.md: %s" % "; ".join(f["rule"] for f in fails)
    return None


def find_role(career, role_id):
    return next((r for r in career.get("roles", []) if r.get("id") == role_id), None)


def api_career_bullet(body):
    path = PROFILE / "career.json"
    career = load_json(path, {})
    role = find_role(career, body.get("role_id"))
    if not role:
        return {"ok": False, "err": "no role with that id"}
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "err": "nothing to add"}
    problem = vet_career_text(text, (body.get("text_de") or "").strip())
    if problem:
        return {"ok": False, "err": problem}
    role.setdefault("bullets", [])
    # A stable id and threads, the same as the switch-over migration gave existing
    # bullets, so the Build panel can select, star and remember this one too.
    taken = {b.get("id") for b in role["bullets"]}
    n = len(role["bullets"]) + 1
    while "%s-%d" % (role["id"], n) in taken:
        n += 1
    known_threads = {t["id"] for t in load_json(PROFILE / "threads.json", {}).get("threads", [])}
    threads = [str(t).strip() for t in (body.get("threads") or []) if str(t).strip() in known_threads]
    new_bullet = {
        "id": "%s-%d" % (role["id"], n), "threads": threads,
        "text": text, "strength": int(body.get("strength") or 2),
        "tags": [t.strip() for t in (body.get("tags") or []) if str(t).strip()],
    }
    # Optional on purpose, not required: a bullet with no German version still
    # renders correctly in English, and still falls back safely (with a
    # warning, not silently) if it is ever selected for a German document.
    # This is what lets them add it without German and translate it later.
    text_de = (body.get("text_de") or "").strip()
    if text_de:
        new_bullet["text_de"] = text_de
    role["bullets"].append(new_bullet)
    save_json_atomic(path, career)
    return {"ok": True}


def api_career_bullet_update(body):
    path = PROFILE / "career.json"
    career = load_json(path, {})
    role = find_role(career, body.get("role_id"))
    if not role:
        return {"ok": False, "err": "no role with that id"}
    idx = body.get("index")
    bullets = role.get("bullets", [])
    if not isinstance(idx, int) or not 0 <= idx < len(bullets):
        return {"ok": False, "err": "no bullet at that position"}
    problem = vet_career_text((body.get("text") or "").strip(),
                              (body.get("text_de") or "").strip())
    if problem:
        return {"ok": False, "err": problem}
    if "text" in body:
        text = (body["text"] or "").strip()
        if not text:
            return {"ok": False, "err": "a bullet cannot be emptied this way; delete it instead"}
        bullets[idx]["text"] = text
    if "text_de" in body:
        text_de = (body["text_de"] or "").strip()
        if text_de:
            bullets[idx]["text_de"] = text_de
        else:
            # An empty save clears it, going back to the safe English fallback
            # rather than leaving a stale translation of an edited English line.
            bullets[idx].pop("text_de", None)
    if "delete" in body and body["delete"]:
        bullets.pop(idx)
    save_json_atomic(path, career)
    return {"ok": True}


def api_career_skill(body):
    """Add, remove, or translate one skill item.

    items_de is positional against items - index 3 in one is the German
    version of index 3 in the other - so add and remove keep both lists the
    same length in lockstep rather than editing one and letting the other
    drift, which is exactly the desync that silently drops a whole cluster
    back to English (see build_skills). A new item with no German supplied
    gets an empty placeholder in items_de rather than no entry at all, which
    is what keeps the arrays the same length; build_skills treats an empty
    placeholder the same as no translation, for that one item only, not the
    whole cluster.
    """
    path = PROFILE / "career.json"
    career = load_json(path, {})
    career.setdefault("skills", {})
    cluster = (body.get("cluster") or "").strip()
    item = (body.get("item") or "").strip()
    if not cluster or cluster not in career["skills"]:
        return {"ok": False, "err": "unknown skill cluster"}
    if not item:
        return {"ok": False, "err": "nothing to add"}
    if body.get("op") != "remove":
        problem = vet_career_text(item, (body.get("item_de") or "").strip())
        if problem:
            return {"ok": False, "err": problem}

    entry = career["skills"][cluster]
    items = entry.setdefault("items", [])
    has_de = "items_de" in entry
    if has_de:
        items_de = entry["items_de"]
        # Backfill in case an older cluster's lists are already uneven -
        # never operate on mismatched lengths, pad first instead.
        while len(items_de) < len(items):
            items_de.append("")

    op = body.get("op")
    if op == "remove":
        idx = next((i for i, x in enumerate(items) if x.lower() == item.lower()), None)
        if idx is not None:
            items.pop(idx)
            if has_de and idx < len(items_de):
                items_de.pop(idx)
    elif op == "set_de":
        idx = next((i for i, x in enumerate(items) if x.lower() == item.lower()), None)
        if idx is None:
            return {"ok": False, "err": "no such item in that cluster"}
        entry.setdefault("items_de", ["" for _ in items])
        while len(entry["items_de"]) < len(items):
            entry["items_de"].append("")
        entry["items_de"][idx] = (body.get("item_de") or "").strip()
    elif not any(x.lower() == item.lower() for x in items):
        items.append(item)
        if has_de:
            items_de.append((body.get("item_de") or "").strip())

    save_json_atomic(path, career)
    return {"ok": True}


# --------------------------------------------------------------------------
# settings
#
# The things that change as their situation changes, made editable from the
# app instead of requiring a JSON edit or a conversation. Deliberately narrow
# endpoints per field group rather than one generic "patch this file"
# handler, matching how every other mutation in this server works: a
# whitelisted operation that knows the shape of what it is touching, not an
# arbitrary write.
# --------------------------------------------------------------------------

APP_SETTINGS = PROFILE / "app_settings.json"
DEFAULT_THRESHOLDS = {"score_good_min": 70, "score_ok_min": 40, "stale_days": 14}


def load_thresholds():
    d = load_json(APP_SETTINGS, {})
    return {**DEFAULT_THRESHOLDS, **{k: v for k, v in d.items() if k in DEFAULT_THRESHOLDS}}


def save_json_atomic(path, data):
    # career.json is the source every document is rendered from, so a change
    # made in the Career editor is recorded like any other fact, in
    # profile/sources.jsonl, with the editor as its source.
    if Path(path).resolve() == (PROFILE / "career.json").resolve():
        sys.path.insert(0, str(ROOT / "tools"))
        import careerdata  # noqa: E402
        careerdata.save(data, "Career editor (web UI)", Path(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def api_settings():
    avail = load_json(PROFILE / "availability.json", {})
    watch = load_json(PROFILE / "watchlist.json", {})

    loc = avail.get("location") or {}
    money = avail.get("money") or {}
    shifts = avail.get("shifts") or {}

    companies = []
    for key, cat in (watch.get("categories") or {}).items():
        for co in cat.get("companies") or []:
            # Each entry is normally {name, domain, hq?, note?}, not a bare
            # string - discovered by an add hitting an AttributeError on a
            # dict where a string was assumed, and fixed at both ends.
            if isinstance(co, dict):
                companies.append({"category": key, "company": co.get("name", ""),
                                  "domain": co.get("domain", ""), "hq": co.get("hq", ""),
                                  "note": co.get("note", "")})
            else:
                companies.append({"category": key, "company": str(co),
                                  "domain": "", "hq": "", "note": ""})

    return {
        "availability": {
            "home_plz": loc.get("home_plz", ""),
            "radius_km": loc.get("radius_km"),
            "floor_gross_monthly": money.get("floor_gross_monthly"),
            "shifts_yes": shifts.get("yes") or [],
            "shifts_no": shifts.get("no") or [],
        },
        "watchlist": {
            "search_terms": {
                "primary": (watch.get("search_terms") or {}).get("primary") or [],
                "secondary": (watch.get("search_terms") or {}).get("secondary") or [],
            },
            "categories": sorted((watch.get("categories") or {}).keys()),
            "companies": companies,
        },
        "thresholds": load_thresholds(),
        "send_folder": str(send_folder() or ""),
    }


def api_settings_availability(body):
    path = PROFILE / "availability.json"
    avail = load_json(path, {})
    avail.setdefault("location", {})
    avail.setdefault("money", {})
    avail.setdefault("shifts", {})

    if "home_plz" in body:
        avail["location"]["home_plz"] = str(body["home_plz"]).strip()[:20]
    if "radius_km" in body:
        try:
            avail["location"]["radius_km"] = max(1, min(200, int(body["radius_km"])))
        except (TypeError, ValueError):
            return {"ok": False, "err": "radius_km must be a number"}
    if "floor_gross_monthly" in body:
        try:
            avail["money"]["floor_gross_monthly"] = max(0, int(body["floor_gross_monthly"]))
        except (TypeError, ValueError):
            return {"ok": False, "err": "floor_gross_monthly must be a number"}
    if "shifts_yes" in body:
        avail["shifts"]["yes"] = [str(x).strip() for x in body["shifts_yes"] if str(x).strip()]
    if "shifts_no" in body:
        avail["shifts"]["no"] = [str(x).strip() for x in body["shifts_no"] if str(x).strip()]

    save_json_atomic(path, avail)
    return {"ok": True}


def api_settings_thresholds(body):
    cur = load_thresholds()
    for key in DEFAULT_THRESHOLDS:
        if key in body:
            try:
                cur[key] = max(0, int(body[key]))
            except (TypeError, ValueError):
                return {"ok": False, "err": "%s must be a number" % key}
    if cur["score_ok_min"] >= cur["score_good_min"]:
        return {"ok": False, "err": "the 'good' threshold must be higher than the 'ok' one"}
    # Merge, not replace: the file holds other settings too (send_folder, weights).
    save_json_atomic(APP_SETTINGS, {**load_json(APP_SETTINGS, {}), **cur})
    return {"ok": True, "thresholds": cur}


def api_settings_send_folder(body):
    """Set or clear the folder finished documents are also copied to."""
    raw = (body.get("send_folder") or "").strip()
    if raw and not Path(raw).is_absolute():
        return {"ok": False, "err": "use a full path, e.g. C:\\Users\\you\\Desktop\\Job Applications "
                                    "or /Users/you/Desktop/Job Applications"}
    settings = load_json(APP_SETTINGS, {})
    if raw:
        settings["send_folder"] = raw
    else:
        settings.pop("send_folder", None)
    save_json_atomic(APP_SETTINGS, settings)
    return {"ok": True, "send_folder": raw}


def api_settings_term(body):
    path = PROFILE / "watchlist.json"
    watch = load_json(path, {})
    watch.setdefault("search_terms", {})
    which = body.get("list")
    if which not in ("primary", "secondary"):
        return {"ok": False, "err": "list must be primary or secondary"}
    terms = [t for t in (watch["search_terms"].get(which) or [])]
    term = (body.get("term") or "").strip()
    if not term:
        return {"ok": False, "err": "no term given"}
    if body.get("op") == "remove":
        terms = [t for t in terms if t.lower() != term.lower()]
    else:
        if not any(t.lower() == term.lower() for t in terms):
            terms.append(term)
    watch["search_terms"][which] = terms
    save_json_atomic(path, watch)
    return {"ok": True, which: terms}


def company_name(entry):
    """A company entry is normally {name, domain, hq?, note?}; tolerate the
    bare-string shape too rather than assume every entry was added the same way."""
    return (entry.get("name") or "") if isinstance(entry, dict) else str(entry)


def api_settings_company(body):
    path = PROFILE / "watchlist.json"
    watch = load_json(path, {})
    watch.setdefault("categories", {})
    category = (body.get("category") or "").strip()
    company = (body.get("company") or "").strip()
    if not company:
        return {"ok": False, "err": "no company given"}
    if body.get("op") == "remove":
        for cat in watch["categories"].values():
            cat["companies"] = [c for c in (cat.get("companies") or [])
                                if company_name(c).lower() != company.lower()]
    else:
        if not category:
            return {"ok": False, "err": "choose a category"}
        cat = watch["categories"].setdefault(category, {"priority": 9, "why": "",
                                                         "roles_to_watch": [], "companies": []})
        cat.setdefault("companies", [])
        if not any(company_name(c).lower() == company.lower() for c in cat["companies"]):
            domain = (body.get("domain") or "").strip()
            entry = {"name": company}
            if domain:
                entry["domain"] = domain
            cat["companies"].append(entry)
    save_json_atomic(path, watch)
    return {"ok": True}


# --------------------------------------------------------------------------
# desktop copy
#
# The project folder is not where they would look for a finished document -
# the Desktop is. Every successful CV or letter render also lands a copy in
# its own folder there, named for the company and role rather than the
# internal slug, so opening it does not require knowing this app's own
# naming scheme at all.
# --------------------------------------------------------------------------

def send_folder():
    """Where finished CVs and packages are also copied, from Settings
    (profile/app_settings.json "send_folder"). None: no copy is made. It was a
    hard-coded Desktop/Job Applications folder, which not every user wants."""
    raw = (load_json(APP_SETTINGS, {}).get("send_folder") or "").strip()
    return Path(raw) if raw and Path(raw).is_absolute() else None


def entry_for_slug(slug):
    """The pipeline entry a render slug belongs to, if any. A slug with no
    match (an ad hoc render, or --slug typed by hand on the Render tab) is a
    normal case, not an error: there is simply nowhere to file a Desktop copy."""
    for e in load_pipeline():
        if app_dir(e["id"]).name == slug:
            return e
    return None


def desktop_prospect_folder(entry):
    name = "%s - %s" % (entry.get("company", "Unknown"), entry.get("role", "Role"))
    name = re.sub(r'[<>:"/\\|?*]', "-", name).strip()[:150] or "Application"
    base = send_folder()
    if base is None:
        return None
    folder = base / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ensure_exact_case(path):
    """Remove a same-named file whose on-disk casing differs from what is
    about to be written. The identical fix as render.py's own copy, kept
    separately because this server never imports render.py - it only ever
    shells out to it - and the duplication is five lines rather than a new
    import path into a module built to be run as a script."""
    path = Path(path)
    if not path.parent.is_dir():
        return
    real = next((p.name for p in path.parent.iterdir() if p.name.lower() == path.name.lower()), None)
    if real is not None and real != path.name:
        (path.parent / real).unlink()


def sync_to_desktop(slug, file_path):
    """Copy one rendered file to its prospect's Desktop folder. Never raises:
    a failed copy (a locked file, a full disk, permissions) should not turn a
    successful render into a reported failure, since the project's own copy
    already exists and is the one every other feature reads from."""
    try:
        entry = entry_for_slug(slug)
        if not entry:
            return None
        folder = desktop_prospect_folder(entry)
        if folder is None:
            return None
        dest = folder / Path(file_path).name
        ensure_exact_case(dest)
        shutil.copyfile(file_path, dest)
        return str(dest)
    except OSError:
        return None


def api_posting_save(body):
    """Keep a pasted posting for an entry, screened like every other way in.
    What the Build panel and Deadline mode read before building."""
    entries = load_pipeline()
    entry = next((e for e in entries if e["id"] == body.get("id")), None)
    if not entry:
        return {"ok": False, "err": "no such pipeline entry"}
    text = (body.get("posting") or "").strip()
    if len(text) < MIN_POSTING_CHARS:
        return {"ok": False, "err": "that is too short to be a posting (under %d characters)"
                                    % MIN_POSTING_CHARS}
    try:
        save_posting(entry["id"], text)
    except PostingFlagged as exc:
        return flagged_reply(str(exc))
    return {"ok": True}


def api_package(body):
    """tools/package.py for one application: named submission files, the last
    checks, then a copy of each to the Desktop folder they send from."""
    slug = safe_slug(body.get("slug"), "")
    if not slug or not (APPS / slug).is_dir():
        return {"ok": False, "err": "no application selected"}
    sys.path.insert(0, str(ROOT / "tools"))
    import package  # noqa: E402
    written, problems, warnings = package.build(slug, merge=bool(body.get("merge")))
    # A CV that was never finalized is built here instead of sending him back
    # to find the button (2026-10-19: "no CV PDF in the folder").
    saved_spec = load_json(APPS / slug / "build.json", None)
    if saved_spec and any("no CV PDF" in p for p in problems):
        entry = next((e for e in load_pipeline() if app_dir(e["id"]).name == slug), None)
        if entry:
            fin = api_build_finalize({"id": entry["id"], "spec": saved_spec})
            if not fin.get("ok"):
                why = "; ".join(fin.get("problems") or []) or (fin.get("ats") or "see the Build panel")[:300]
                return {"ok": False, "warnings": warnings,
                        "problems": ["The CV had not been built yet, and building it failed: %s" % why]}
            written, problems, warnings = package.build(slug, merge=bool(body.get("merge")))
    if not problems:
        with PIPELINE_LOCK:
            entries = load_pipeline()
            if any(promote_to_drafted(e) for e in entries if app_dir(e["id"]).name == slug):
                save_pipeline(entries)
    if problems:
        return {"ok": False, "problems": problems, "warnings": warnings}
    for path in written:
        sync_to_desktop(slug, path)
    return {"ok": True, "files": [p.name for p in written], "warnings": warnings,
            "dir": str(APPS / slug / "submit")}


def api_screen(body):
    text = (body.get("body") or "").strip()
    if not text:
        return {"ok": False, "err": "no posting text"}
    title = str(body.get("title") or "")[:120]

    pre = run([PY, "tools/prescreen.py", "-", "--title", title], stdin_text=text)
    return {"ok": pre["ok"], "prescreen": pre["out"] + pre["err"]}


def api_open(body):
    target = body.get("path", "")
    if not target or not inside_project(target) or not Path(target).exists():
        return {"ok": False, "err": "refused: path must exist inside the project"}
    try:
        if sys.platform == "win32":
            os.startfile(str(Path(target).resolve()))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "err": str(exc)}


def api_sources(query=None):
    cfg = load_json(PROFILE / "sources.json", {"sources": []})
    seen = load_jsonl(DATA / "jobs-seen.jsonl")
    recent = [s for s in seen if s.get("company")][-40:]
    recent.reverse()
    return {"sources": cfg.get("sources", []),
            "not_found": (cfg.get("_not_found") or {}).get("companies", []),
            "seen_total": len(seen),
            "recent": recent}


def api_sources_run(body):
    cmd = [PY, "tools/watch_ats.py", "--run", "--json"]
    show_all = bool(body.get("all"))
    if show_all:
        cmd.append("--all")
    if body.get("anywhere"):
        cmd.append("--anywhere")
    res = run(cmd)
    if not res["ok"]:
        return {"ok": False, "err": res["err"] or res["out"]}
    try:
        result = {"ok": True, **json.loads(res["out"])}
    except ValueError:
        return {"ok": False, "err": "watcher returned unparseable output"}

    # A hit shown once in this response and never added to the pipeline used
    # to be gone for good: watch_ats.py's own seen-history only remembers a
    # fingerprint, which stops it being shown again, not the hit itself. That
    # made it possible to lose a genuine match by being busy the moment it
    # appeared. Every new hit now also lands in the same durable capture
    # inbox a bookmarklet grab uses, so it survives until it is acted on.
    # Skipped for an --all run: that flag means "ignore history and show me
    # everything", which would otherwise re-file the same hits into the
    # inbox on every click.
    if not show_all and result.get("new"):
        rows = load_captures()
        for hit in result["new"]:
            bits = [b for b in (
                hit.get("location") or "",
                ("matched: %s" % ", ".join(hit.get("matched") or [])) if hit.get("matched") else "",
                hit.get("pay") or "",
            ) if b]
            rows.append({
                "id": uuid.uuid4().hex[:12],
                "url": (hit.get("url") or "")[:500],
                "title": "%s at %s" % (hit.get("title", ""), hit.get("company", "")),
                "text": ". ".join(bits) or "Found by the job board watcher.",
                "captured_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "origin": "watcher",
            })
        save_captures(rows)

    return result


def api_sources_discover(body):
    name = (body.get("company") or "").strip()
    if not name:
        return {"ok": False, "err": "company name required"}
    res = run([PY, "tools/watch_ats.py", "--discover", name[:80], "--json"])
    if not res["ok"]:
        return {"ok": False, "err": res["err"] or res["out"]}
    try:
        return {"ok": True, "found": json.loads(res["out"])}
    except ValueError:
        return {"ok": False, "err": "discover returned unparseable output"}


REQUIREMENT = re.compile(
    r"(you have|you will|you bring|experience (with|in|of)|proficien|fluent|"
    r"required|must have|we are looking for|ideally|nice to have|responsib|"
    r"erfahrung|kenntnisse|ausbildung|w(ü|ue)nschenswert|du bringst|du hast|sie haben|"
    r"sie bringen|voraussetzung|anforderung|freude an|ansprechp|beratung)", re.I)

# How-to-apply and contact lines. Quoted into the scaffold as requirements,
# they asked the letter to "answer" "Bei Fragen kannst du dich gern an ... wenden".
CLOSING = re.compile(
    r"(bei fragen|freuen uns auf|bewirb dich|bewerben sie sich|online-bewerbung|"
    r"deine bewerbung|ihre bewerbung|unterlagen|m(ö|oe)chtest du teil|erreichst (du )?ihn|"
    r"erreichen sie|apply now|how to apply|send (us )?your|questions\?|"
    r"bewerbungen (per|an|bitte)|personalvermittlung|recruiters?\b.{0,20}\bagenc|"
    r"^source:|^quelle:|@[\w-]+\.[a-z]{2,})"
    r"|\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]", re.I)   # a German postal address

# Headings of the part of a posting that lists what the employer offers. Lines
# under one are perks, not things the letter should answer.
BENEFITS = re.compile(
    r"(gefallen|wir bieten|was wir bieten|bieten wir|deine vorteile|ihre vorteile|"
    r"benefits|we offer|what we offer|perks|why join|our offer|in it for you|"
    r"unser angebot|das bieten wir|berufliche zukunft|deine zukunft|ihre zukunft|"
    r"what you get|what's in it|darauf kannst du dich freuen|deine benefits|ihre benefits|"
    # Anywhere in the (short) heading, not only the whole line: "Growing together -
    # what you can expect at voize" was read as a requirements list, and its team
    # events and stock options counted as gaps against the score.
    r"what you can expect|what to expect|why you.{0,3}ll love|life at|growing together|"
    r"our culture|what we give|was dich bei uns erwartet|das erwartet dich bei uns)", re.I)


# Section headings. Lines under a requirements heading are what the posting
# asks a candidate to have; lines under a tasks heading are the job itself.
# Taking the first bullets of a page quoted tasks ("Co-create success plans")
# as requirements, and every one read as a gap.
# Searched anywhere in the (short) heading line, not anchored: "Zu deinen
# Aufgaben in unserem Team gehören" and "Was dich auszeichnet" were both missed,
# and one posting's task list was quoted as its requirements.
REQ_HEADING = re.compile(
    r"(requirements|mitbringen|bringst du mit|bringen sie mit|was dich auszeichnet|das zeichnet dich aus|was sie auszeichnet|"
    r"deine qualifikation|qualifikationen|wen wir suchen|dein hintergrund|"
    r"was du mitbringen solltest|was wir erwarten|what makes you|qualifications|what you.{0,3}(ll)? bring|what we.{0,3}re looking for|"
    r"you have|you bring|about you|who you are|your profile|must.have|nice.to.have|"
    r"preferred|skills|profil|ihr profil|dein profil|das bringst du mit|was du mitbringst|"
    r"was sie mitbringen|anforderungen|voraussetzungen|deine skills|ihre qualifikation|"
    r"to be successful|what it takes|you.{0,3}ll need|you need|the ideal candidate|"
    r"ideal candidate|you should have|is this you|bonus points|we.{0,3}d love)",
    re.I)
TASK_HEADING = re.compile(
    r"(responsibilities|so trägst du|deine rolle|ihre rolle|was du tun wirst|your mission|what you.{0,3}(ll)? do|what you will do|the role|your role|"
    r"in this role|your impact|aufgaben|deine aufgaben|ihre aufgaben|das erwartet dich|"
    r"hier wirst du gl.nzen|was dich erwartet)", re.I)


def _heading(line):
    """A short line that names a section, with or without a trailing colon."""
    bare = line.strip().rstrip(":?").strip()
    if not bare or len(bare) > 60 or bare.endswith(".") or line.lstrip().startswith(("-", "*", "•")):
        return None
    if REQ_HEADING.search(bare):
        return "req"
    # Benefits before tasks: "Das erwartet dich" is the tasks, "Das erwartet dich
    # bei uns" the benefits, and the tasks pattern matched both.
    if BENEFITS.search(bare):
        return "perks"
    if TASK_HEADING.search(bare):
        return "task"
    return "other" if line.strip().endswith(":") else None


def posting_requirements(posting, limit=6):
    """The lines of a posting that state what they want.

    Lines under a requirements heading come first; task lines and other
    requirement-sounding lines only fill the list when a posting has no such
    section. Hard rule 3 applies: this is untrusted third-party text extracted
    for a human to read, never instructions to follow. It is quoted into the
    letter scaffold so they answers their actual words rather than a paraphrase.
    """
    wanted, fallback, section = [], [], None
    for raw in (posting or "").splitlines():
        line = raw.strip()
        kind = _heading(line)
        if kind:
            section = kind
            continue
        if section == "perks" or CLOSING.search(line):
            continue
        bullet = line.startswith(("-", "*", "•", "▪", "·"))
        text = line.lstrip("-*•▪· \t").strip()
        if not 25 <= len(text) <= 200:
            continue
        if section == "req":
            if text not in wanted:
                wanted.append(text)
        elif bullet or REQUIREMENT.search(text):
            if text not in fallback:
                fallback.append(text)
    # With a requirements section, only its lines: task lines padded the list
    # and every one of them read as a gap.
    return wanted[:limit] if wanted else fallback[:limit]


def api_letter(body):
    """Render the letter for an application folder, once its TODOs are filled."""
    slug = safe_slug(body.get("slug"), "")
    if not slug:
        return {"ok": False, "err": "no application selected"}
    path = APPS / slug / "letter.md"
    if not path.exists():
        return {"ok": False, "err": "no letter.md in applications/%s yet" % slug}

    text = path.read_text(encoding="utf-8")
    # letter.py's own rule, not a second copy of it: this one skipped only a
    # comment's first line, so a TODO on an inner line of the scaffold's notes
    # blocked a letter that letter.py itself would have rendered.
    sys.path.insert(0, str(ROOT / "render"))
    from letter import find_todos  # noqa: E402
    todos = find_todos(text)
    if todos:
        return {"ok": False, "todos": todos[:8],
                "err": "%d line(s) still say TODO. A letter with a placeholder in it "
                       "is worse than no letter." % len(todos),
                "path": str(path)}

    # Voice before paper. A letter that reads as generated is worse than a late
    # one, and writing-style.md has been unenforced since it was written.
    voice = run([PY, "tools/voice_check.py", str(path), "--json"])
    findings = []
    try:
        findings = json.loads(voice["out"]).get("findings", [])
    except ValueError:
        pass
    if any(f["level"] == "FAIL" for f in findings):
        return {"ok": False, "voice": findings, "path": str(path),
                "err": "the voice check failed. Every one of these is a rule in "
                       "writing-style.md, and they are what makes a letter read "
                       "as generated."}

    res = run([PY, "render/letter.py", str(path)])
    pdf = path.with_suffix(".pdf")
    pdf_ok = pdf.exists()
    return {"ok": res["ok"], "out": res["out"], "err": res["err"], "voice": findings,
            "pdf": str(pdf) if pdf_ok else "", "path": str(path),
            "desktop_copy": sync_to_desktop(slug, pdf) if pdf_ok else None}


def api_letter_draft(body):
    """Run tools/draft_letter.py: a headless Claude Code session fills in the
    letter's TODOs, then tools/claim_check.py verifies the result before this
    ever reaches 'Render letter'. Requires the claude CLI installed and logged
    in on this machine - that part is a one-time, interactive, human step."""
    slug = safe_slug(body.get("slug"), "")
    if not slug:
        return {"ok": False, "err": "no application selected"}
    if not (APPS / slug / "letter.md").exists():
        return {"ok": False, "err": "no letter.md in applications/%s yet - "
                                     "prepare the application first" % slug}
    entry = entry_for_slug(slug)
    company = (entry or {}).get("company") or ""
    if not company:
        return {"ok": False, "err": "no company on record for this application - "
                                     "set one in the pipeline entry first"}
    # The drafter answers the posting, so it needs the posting. Fetch it from
    # the entry's own link rather than failing with "paste it in".
    note = ""
    if not saved_posting(APPS / slug):
        text, note = fetch_and_save_posting(entry)
        if not text:
            return {"ok": False, "err": "no posting text to write the letter from. %s "
                    "Paste the posting into Prepare and try again." % note}
    res = run([PY, "tools/draft_letter.py", "--slug", slug, "--company", company],
              timeout=DRAFT_TIMEOUT)
    out = ("%s\n\n" % note if note else "") + res["out"]
    return {"ok": res["ok"], "out": out, "err": res["err"]}


def api_fit_analyze(body):
    """Run tools/fit_and_select.py: a headless Claude Code session reads the
    full career history against this specific posting and reasons about real
    fit - which thread should Lead, which existing bullets honestly
    support which requirement, and where a genuine but differently-phrased
    connection exists (an "honest bridge") versus a plain gap. Writes
    applications/<slug>/fit-analysis.json. Same one-time claude-CLI-login
    requirement as api_letter_draft."""
    slug = safe_slug(body.get("slug"), "")
    if not slug:
        return {"ok": False, "err": "no application selected"}
    entry = entry_for_slug(slug)
    if not saved_posting(APPS / slug):
        text, note = fetch_and_save_posting(entry or {})
        if not text:
            return {"ok": False, "err": "no posting text to analyze. %s Paste the "
                                         "posting into Prepare and try again." % note}
    company = (entry or {}).get("company") or ""
    cmd = [PY, "tools/fit_and_select.py", "--slug", slug]
    if company:
        cmd += ["--company", company]
    res = run(cmd, timeout=DRAFT_TIMEOUT)
    out_path = APPS / slug / "fit-analysis.json"
    analysis = load_json(out_path, None) if out_path.exists() else None
    return {"ok": res["ok"], "out": res["out"], "err": res["err"], "analysis": analysis}


def api_sources_add(body):
    """Persist a discovered job board. Shells out so the verify-then-write
    rule lives in one place and the UI cannot bypass it."""
    name = (body.get("company") or "").strip()
    ats = (body.get("ats") or "").strip()
    slug = (body.get("slug") or "").strip()
    if not name or not ats:
        return {"ok": False, "err": "company and ats are both required"}
    cmd = [PY, "tools/watch_ats.py", "--add", name[:80], "--ats", ats[:24],
           "--slug", slug[:80], "--json"]
    if body.get("note"):
        cmd += ["--note", str(body["note"])[:200]]
    res = run(cmd)
    try:
        return json.loads(res["out"])
    except ValueError:
        return {"ok": False, "err": res["err"] or res["out"] or "add produced no output"}


def api_sources_toggle(body):
    """Stop polling a source without losing the verified endpoint."""
    path = PROFILE / "sources.json"
    cfg = load_json(path, {})
    ats, slug = body.get("ats"), body.get("slug", "")
    for src in cfg.get("sources", []):
        if src.get("ats") == ats and src.get("slug", "") == slug:
            src["enabled"] = bool(body.get("enabled"))
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            os.replace(str(tmp), str(path))
            return {"ok": True, "company": src.get("company"),
                    "enabled": src["enabled"]}
    return {"ok": False, "err": "no source %s/%s" % (ats, slug)}


def api_import(body):
    """Bring a batch of postings in from a JSON file.

    The Indeed connector is a Claude-side tool, not an HTTP endpoint, so this
    server cannot call it. The workable flow is that Claude runs the search,
    writes the batch to applications/_scout/, and this imports it.
    """
    name = safe_slug(body.get("file", ""), "")
    candidates = sorted((APPS / "_scout").glob("*.json")) if (APPS / "_scout").exists() else []
    if not name:
        return {"ok": True, "files": [p.name for p in candidates]}
    match = [p for p in candidates if safe_slug(p.stem) == name or p.name == body.get("file")]
    if not match:
        return {"ok": False, "err": "no such batch file", "files": [p.name for p in candidates]}
    jobs = load_json(match[0], [])
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", [])
    added, skipped = [], []
    for j in jobs:
        r = api_pipeline_add({"company": j.get("company"), "role": j.get("title") or j.get("role"),
                              "url": j.get("url"), "stage": "found"})
        (added if r.get("ok") else skipped).append(j.get("company"))
    return {"ok": True, "added": len(added), "skipped": len(skipped)}


DOC_STATUS_FILE = ".doc_status.json"


def load_doc_status(app_folder):
    return load_json(app_folder / DOC_STATUS_FILE, {})


def docs_for(entry_id):
    """The documents made for one application, for the card badges and the
    viewer: [{kind, label, name, path}]. What is in submit/ is what gets
    uploaded, so a packaged file is listed first."""
    d = app_dir(entry_id)
    if not d.is_dir():
        return []
    out = []
    submit = d / "submit"
    if submit.is_dir():
        for p in sorted(submit.glob("*.pdf")):
            n = p.name.lower()
            kind = ("application" if ("_application" in n or "_bewerbung" in n) else
                    "letter" if ("letter" in n or "anschreiben" in n) else
                    "cv" if ("_cv" in n or "lebenslauf" in n) else "enclosure")
            out.append({"kind": kind, "label": "Sent set: " + p.stem.split("_")[-1],
                        "name": "submit/" + p.name, "path": str(p)})
    cvs = sorted((p for p in d.glob("*.pdf") if "letter" not in p.name.lower()),
                 key=lambda p: p.stat().st_mtime, reverse=True)
    for i, p in enumerate(cvs):
        out.append({"kind": "cv", "label": "CV" if i == 0 else "Older CV (%s)" % p.stem,
                    "name": p.name, "path": str(p)})
    if (d / "letter.pdf").exists():
        out.append({"kind": "letter", "label": "Cover letter", "name": "letter.pdf",
                    "path": str(d / "letter.pdf")})
    if (d / "letter.md").exists():
        out.append({"kind": "letter-draft", "label": "Letter draft (text)",
                    "name": "letter.md", "path": str(d / "letter.md")})
    return out


def api_workspace(query):
    target = (query.get("id") or [""])[0]
    if not target:
        return {"ok": False, "err": "id required"}
    entry = next((e for e in load_pipeline() if e["id"] == target), None)
    url = (entry or {}).get("url", "")
    d = app_dir(target)
    if not d.exists() or not inside_project(d):
        return {"ok": True, "dir": str(d), "exists": False, "files": [], "url": url}
    statuses = load_doc_status(d)
    files = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.name != DOC_STATUS_FILE:
            files.append({"name": str(p.relative_to(d)), "path": str(p),
                          "kb": round(p.stat().st_size / 1024, 1),
                          "status": statuses.get(str(p.relative_to(d)))})
    return {"ok": True, "dir": str(d), "exists": True, "files": files, "url": url,
            "docs": docs_for(target)}


def api_doc_status(body):
    """Mark a rendered document accepted or flagged for manual edits, so the
    workspace list shows what is actually finished versus still a draft
    instead of every file looking equally done the moment it exists."""
    entry_id_ = body.get("id")
    name = (body.get("name") or "").strip()
    status = body.get("status")
    if not entry_id_ or not name:
        return {"ok": False, "err": "id and name are required"}
    if status not in (None, "", "accepted", "needs-edits"):
        return {"ok": False, "err": "status must be accepted, needs-edits, or empty"}
    d = app_dir(entry_id_)
    if not d.exists():
        return {"ok": False, "err": "no such application folder"}
    statuses = load_doc_status(d)
    if status:
        statuses[name] = status
    else:
        statuses.pop(name, None)
    save_json_atomic(d / DOC_STATUS_FILE, statuses)
    return {"ok": True}


def api_posting(query):
    """The posting text already saved for a pipeline entry, if there is one.

    Used to prefill the detail panel's paste box, so an entry screened from
    the Screen tab (or already prepared once) does not ask for the posting a
    second or third time.
    """
    target = (query.get("id") or [""])[0]
    if not target:
        return {"ok": False, "err": "id required"}
    try:
        return {"ok": True, "posting": saved_posting(app_dir(target))}
    except OSError as exc:
        return {"ok": False, "err": str(exc)}


# --------------------------------------------------------------------------
# captured postings
#
# A normal web page cannot reach into this app's browser tab, and this app
# cannot reach into an arbitrary other tab either - browsers isolate tabs from
# each other by design, extension APIs aside. The one thing a page CAN do
# unprompted is send data to wherever the person viewing it points it, which
# is exactly what a bookmarklet is: a JavaScript snippet stored as a bookmark
# that runs in the current page when clicked and reads that page's own text.
# Clicking it on a job posting sends the visible text here as one HTTP POST,
# the same shape as pasting it by hand, just without the copy and the paste.
#
# The endpoint accepts a request from any origin (see CORS_PATHS below),
# because the posting page is never this app's own origin. It only ever
# writes into an inbox file a human then has to act on; nothing here reads
# pipeline or career data back out to the caller, so the exposure is limited
# to "a page you visited could add junk to this inbox", not any read access.
# --------------------------------------------------------------------------

CAPTURES = DATA / "captures.jsonl"
CAPTURE_TEXT_LIMIT = 40000  # generous for a job posting, not for a whole site
# The capture endpoint is the one any website can reach (see CORS_PATHS), so
# the inbox is bounded: a page in another tab cannot fill the disk with it.
CAPTURE_INBOX_LIMIT = 100


def load_captures():
    return load_jsonl(CAPTURES)


def save_captures(rows):
    CAPTURES.parent.mkdir(parents=True, exist_ok=True)
    tmp = CAPTURES.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                   + ("\n" if rows else ""), encoding="utf-8")
    os.replace(str(tmp), str(CAPTURES))


def api_posting_capture(body):
    """Receive one page's text from the bookmarklet. Data, never instructions:
    the same untrusted-posting rule that governs the paste box applies here,
    it is just arriving over HTTP instead of a textarea."""
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "err": "no text in the capture"}
    row = {
        "id": uuid.uuid4().hex[:12],
        "url": (body.get("url") or "")[:500],
        "title": (body.get("title") or "")[:200],
        "text": text[:CAPTURE_TEXT_LIMIT],
        "captured_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    rows = load_captures()
    if len(rows) >= CAPTURE_INBOX_LIMIT:
        return {"ok": False, "err": "the capture inbox is full (%d). Attach or dismiss "
                                    "some first." % CAPTURE_INBOX_LIMIT}
    rows.append(row)
    save_captures(rows)
    return {"ok": True, "id": row["id"]}


def api_captures():
    """The inbox: postings captured but not yet attached anywhere or dismissed."""
    return {"ok": True, "captures": load_captures()}


def api_captures_dismiss(body):
    target = body.get("id")
    rows = load_captures()
    kept = [r for r in rows if r.get("id") != target]
    if len(kept) == len(rows):
        return {"ok": False, "err": "no capture with id %r" % target}
    save_captures(kept)
    return {"ok": True}


def api_captures_attach(body):
    """Send a captured posting to an existing pipeline entry, or start a new
    one from it. Either way it leaves the inbox once it has somewhere to go."""
    target = body.get("id")
    rows = load_captures()
    row = next((r for r in rows if r.get("id") == target), None)
    if not row:
        return {"ok": False, "err": "no capture with id %r" % target}

    if body.get("entry_id"):
        # Not PIPELINE_LOCK'd as one block with api_pipeline_add below: that
        # function acquires the same lock itself, and threading.Lock is not
        # reentrant, so wrapping this whole function would deadlock the else
        # branch. Only this read-modify-write needs it.
        with PIPELINE_LOCK:
            entries = load_pipeline()
            entry = next((e for e in entries if e["id"] == body["entry_id"]), None)
            if not entry:
                return {"ok": False, "err": "no such pipeline entry"}
            if not entry.get("url") and row.get("url"):
                entry["url"] = row["url"]
                save_pipeline(entries)
        try:
            save_posting(entry["id"], row["text"])
        except PostingFlagged as exc:
            return flagged_reply(str(exc))
        result = {"ok": True, "entry_id": entry["id"]}
    else:
        company = (body.get("company") or "").strip()
        role = (body.get("role") or "").strip()
        if not company or not role:
            return {"ok": False, "err": "company and role are required for a new entry"}
        added = api_pipeline_add({"company": company, "role": role,
                                  "url": row.get("url", ""), "stage": "found",
                                  "posting": row["text"]})
        if not added.get("ok"):
            return added
        result = {"ok": True, "entry_id": added["entry"]["id"]}

    save_captures([r for r in rows if r.get("id") != target])
    return result


# --------------------------------------------------------------------------
# CV builder (plans/cv-builder.md)
#
# The Build panel: a base, a Lead thread and dials instead of a persona, with a
# live preview. The spec an application was built with is kept in its folder as
# build.json, so a later change in the suggestions never silently alters a CV
# that was already made.
# --------------------------------------------------------------------------

CV_PRESETS = PROFILE / "cv_presets.json"
BUILD_OVERRIDES = DATA / "build-overrides.jsonl"


def record_override(entry, spec, suggestion):
    """What the app suggested next to what they finalized, one line per CV.
    Read back as hints only; suggestions never change silently."""
    if not suggestion:
        return
    sug = suggestion["spec"]["dials"]
    row = {"date": datetime.date.today().isoformat(), "id": entry["id"],
           "base": spec["base"],
           "suggested_lead": next((k for k, v in sug.items() if v == "lead"), None),
           "suggested": sug, "final": spec["dials"]}
    BUILD_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    with BUILD_OVERRIDES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def override_hints(spec, suggestion, ctx):
    """'You usually set X to Y for roles like this', once the same override has
    happened at least twice for the same base and the same suggested Lead."""
    if not suggestion:
        return {}
    sug = suggestion["spec"]["dials"]
    lead = next((k for k, v in sug.items() if v == "lead"), None)
    rows = [r for r in load_jsonl(BUILD_OVERRIDES)
            if r.get("base") == spec["base"] and r.get("suggested_lead") == lead]
    hints = {}
    for tid, suggested in sug.items():
        chosen = [r["final"].get(tid) for r in rows
                  if r.get("final", {}).get(tid) and r["final"].get(tid) != r.get("suggested", {}).get(tid)]
        if len(chosen) >= 2:
            level = max(set(chosen), key=chosen.count)
            if chosen.count(level) >= 2 and level != suggested:
                label = ctx["by_id"].get(tid, {}).get("label", tid)
                hints[tid] = "You usually set %s to %s for roles like this (%d times)." % (
                    label, level.capitalize(), chosen.count(level))
    return hints


def _builder():
    sys.path.insert(0, str(ROOT / "render"))
    sys.path.insert(0, str(ROOT / "tools"))
    import cv_builder  # noqa: E402
    import cv_suggest  # noqa: E402
    return cv_builder, cv_suggest


def _build_entry(body):
    entry = next((e for e in load_pipeline() if e["id"] == body.get("id")), None)
    if not entry:
        raise ValueError("no pipeline entry with id %r" % body.get("id"))
    return entry


def _build_ctx(B, entry):
    """The builder's context plus this posting's distinctive words, so bullet
    choice, trimming and requirement coverage all see the same posting."""
    ctx = B.load_context()
    try:
        posting, _ = _posting_for(entry)
    except (OSError, ValueError):
        posting = ""
    ctx["posting_terms"] = B.posting_terms(posting, ctx)
    return ctx


_POSTING_FAILED = {}   # entry id -> (time, note): a failed fetch is not retried per keystroke


def _posting_for(entry):
    text = saved_posting(app_dir(entry["id"]))
    if text:
        return text, ""
    failed = _POSTING_FAILED.get(entry["id"])
    if failed and time.time() - failed[0] < 600:
        return "", failed[1]
    text, note = fetch_and_save_posting(entry)
    if not text:
        _POSTING_FAILED[entry["id"]] = (time.time(), note)
    return text, note


def _bullet_index(career):
    return {b["id"]: (r, b) for r in career.get("roles", []) for b in r.get("bullets", [])
            if b.get("id")}


def _roles_for_panel(ctx, plan, lang):
    """Every job and project with its bullets, marked as shown or not by the plan."""
    import render as R  # noqa: E402  on sys.path via _builder()
    shown = {b["id"] for g in (plan["jobs"], plan["projects"]) for x in g for b in x["bullets"]}
    out = []
    for role in sorted(ctx["career"].get("roles", []), key=R.sort_key, reverse=True):
        out.append({
            "id": role["id"], "title": role.get("title", ""), "org": role.get("org", ""),
            "dates": R.date_range(role, lang),
            "project": role.get("org_type") in R.PROJECT_ORG_TYPES,
            "earlier": role.get("project_tier") == "earlier",
            "bullets": [{"id": b["id"], "text": b.get("text", ""),
                         "text_de": b.get("text_de", ""),
                         "de_stale": bool(b.get("text_de_stale")),
                         "threads": b.get("threads") or [], "star": bool(b.get("star")),
                         "shown": b["id"] in shown}
                        for b in role.get("bullets", []) if b.get("id")],
        })
    return out


def _panel_payload(entry, spec, suggestion, ctx, B):
    plan = B.plan(spec, ctx)
    presets = load_json(CV_PRESETS, {})
    return {
        "ok": True, "id": entry["id"], "slug": app_dir(entry["id"]).name,
        "company": entry.get("company", ""), "role": entry.get("role", ""),
        "spec": spec, "problems": B.validate(spec, ctx),
        "suggestion": suggestion,
        "threads": [{k: t.get(k, "") for k in ("id", "base", "label", "label_de", "description")}
                    for t in ctx["threads"]["threads"]],
        "bases": {k: {"label": v["label"], "label_de": v.get("label_de", v["label"]),
                      "max_pages": v["max_pages"], "photo_allowed": v["photo_allowed"]}
                  for k, v in ctx["threads"]["bases"].items()},
        "max_strong": ctx["threads"].get("max_strong", 2),
        "roles": _roles_for_panel(ctx, plan, spec["lang"]),
        "untranslated": plan.get("untranslated", []),
        "presets": sorted(presets),
        "photo_available": any(p.exists() for p in B.PHOTO_CANDIDATES),
        "letter": str(app_dir(entry["id"]) / "letter.md")
                  if (app_dir(entry["id"]) / "letter.md").exists() else None,
    }


def fallback_spec(B, ctx, entry, base=None):
    """The starting CV when there is no posting to suggest from.

    Defaulting to Professional, Lead Enablement, English turned a German
    Volkshochschule teaching application and a German retail one into English
    enablement CVs. An entry still carries the persona it was screened under,
    and every thread names the personas it came from (threads.json
    from_personas), so the most specific thread for that persona leads: dozent
    maps to Enablement and to Service Teaching, and Service Teaching, the
    narrower one, wins. The base's own language applies, and a German gender
    tag in the title ("(m/w/d)") makes it German. A `thread` recorded by /fit
    since the switch-over wins over the persona.
    """
    pid = entry.get("persona")
    role = entry.get("role") or ""
    sys.path.insert(0, str(ROOT / "tools"))
    import cv_suggest  # noqa: E402
    german = bool(GENDER_TAG.search(role)) and "de" in cv_suggest.cv_languages()
    tid = entry.get("thread")
    matches = [t for t in ctx["threads"]["threads"]
               if (t["id"] == tid if tid in ctx["by_id"] else
                   pid and pid in (t.get("from_personas") or []))
               and (base is None or t["base"] == base)]
    if matches:
        lead = min(matches, key=lambda t: len(t.get("from_personas") or []))["id"]
        spec = B.default_spec(ctx["by_id"][lead]["base"], lang="de" if german else None,
                              lead=lead, ctx=ctx)
    else:
        # No persona recorded: the title is still evidence, and the suggestion
        # engine reads it the same way it reads a posting.
        _, S = _builder()
        spec = S.suggest(role, role, ctx=ctx, force_base=base)["spec"]
        if german:
            spec["lang"] = "de"
    spec["headline"] = clean_title(role)
    return spec


def api_build_state(body):
    """Open the Build panel for an application: the saved spec, or a fresh
    suggestion from the posting when there is none yet."""
    B, S = _builder()
    entry = _build_entry(body)
    ctx = _build_ctx(B, entry)
    posting, note = _posting_for(entry)
    base = body.get("base") if body.get("base") in ctx["threads"]["bases"] else None
    suggestion = (S.suggest(posting, entry.get("role", ""), ctx=ctx, force_base=base)
                  if posting else None)
    saved = load_json(app_dir(entry["id"]) / "build.json", None)
    if saved and not body.get("fresh"):
        spec = saved
    elif suggestion:
        spec = suggestion["spec"]
    else:
        spec = fallback_spec(B, ctx, entry, base)
    payload = _panel_payload(entry, spec, suggestion, ctx, B)
    payload["hints"] = override_hints(spec, suggestion, ctx)
    payload["posting_note"] = note if not posting else ""
    payload["saved"] = bool(saved) and not body.get("fresh")
    return payload


def api_build_preview(body):
    """HTML for the live preview (no PDF), plus requirement coverage for the spec."""
    B, S = _builder()
    entry = _build_entry(body)
    ctx = _build_ctx(B, entry)
    spec = body.get("spec") or {}
    problems = B.validate(spec, ctx)
    if problems:
        return {"ok": False, "problems": problems}
    html_text, plan = B.preview(spec, ctx)
    posting, _ = _posting_for(entry)
    shown = [b["id"] for g in (plan["jobs"], plan["projects"]) for x in g for b in x["bullets"]]
    return {"ok": True, "html": html_text, "shown": shown,
            "bullet_count": len(shown), "untranslated": plan.get("untranslated", []),
            "requirements": S.requirements(posting, spec, ctx) if posting else [],
            "max_pages": int((spec.get("advanced") or {}).get("max_pages")
                             or ctx["threads"]["bases"][spec["base"]]["max_pages"]),
            # A one-page base goes to two when one page would be thin
            # (cv_builder.THIN_BULLETS), unless they set the page count themselves.
            "may_extend": not (spec.get("advanced") or {}).get("max_pages")
                          and ctx["threads"]["bases"][spec["base"]]["max_pages"] == 1}


def api_build_save(body):
    B, _ = _builder()
    entry = _build_entry(body)
    ctx = _build_ctx(B, entry)
    spec = body.get("spec") or {}
    problems = B.validate(spec, ctx)
    if problems:
        return {"ok": False, "problems": problems}
    out = app_dir(entry["id"])
    out.mkdir(parents=True, exist_ok=True)
    save_json_atomic(out / "build.json", spec)
    return {"ok": True}


def api_build_finalize(body):
    """Save the spec, build the PDF with page fitting, run the ATS and substance
    checks, copy to the Desktop folder. The finished CV."""
    B, _ = _builder()
    entry = _build_entry(body)
    ctx = _build_ctx(B, entry)
    spec = body.get("spec") or {}
    problems = B.validate(spec, ctx)
    if problems:
        return {"ok": False, "problems": problems}
    out = app_dir(entry["id"])
    out.mkdir(parents=True, exist_ok=True)
    save_json_atomic(out / "build.json", spec)
    name = (ctx["career"].get("identity") or {}).get("name", "CV")
    stem = "%s_%s" % (re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "CV",
                      "Lebenslauf" if spec.get("lang") == "de" else "CV")
    result = B.build(spec, out, stem, ctx=ctx)
    try:
        _, S = _builder()
        posting, _ = _posting_for(entry)
        if posting:
            record_override(entry, spec, S.suggest(posting, entry.get("role", ""), ctx=ctx,
                                                   force_base=spec["base"]))
    except (OSError, ValueError, KeyError):
        pass  # a hint record is never worth failing a finalize over
    if result.get("pdf"):
        check = run([PY, "render/ats_check.py", result["pdf"],
                     "--max-pages", str(result["max_pages"])])
        result["ats"] = check["out"] + check["err"]
        result["ats_ok"] = check["ok"]
    # Only a CV that passed is copied to the folder they send from and recorded
    # as what was sent. A failed one stays in the project for inspection.
    if result.get("pdf") and result.get("ats_ok"):
        result["desktop_copy"] = sync_to_desktop(out.name, Path(result["pdf"]))
        # What was actually sent, for the learning log (plans/cv-builder.md 3.2).
        with PIPELINE_LOCK:
            entries = load_pipeline()
            for e in entries:
                if e["id"] == entry["id"]:
                    e["build"] = {"base": spec["base"], "lang": spec["lang"],
                                  "lead": B.lead_of(spec),
                                  "dials": {k: v for k, v in spec["dials"].items() if v != "off"},
                                  "bullets": result.get("shown_bullets", []),
                                  "date": datetime.date.today().isoformat()}
                    promote_to_drafted(e)
            save_pipeline(entries)
    result["ok"] = bool(result.get("ok")) and result.get("ats_ok") is not False
    return result


def api_build_star(body):
    """Star or unstar a bullet as a conversation starter. Stored in career.json:
    a story worth being asked about is worth it on every CV."""
    path = PROFILE / "career.json"
    career = load_json(path, {})
    hit = _bullet_index(career).get(body.get("bullet"))
    if not hit:
        return {"ok": False, "err": "no bullet with that id"}
    _, b = hit
    if body.get("star"):
        b["star"] = True
    else:
        b.pop("star", None)
    save_json_atomic(path, career)
    return {"ok": True}


def api_build_edit(body):
    """Reword a bullet inline. Same checks as the career editor; a German version
    of the old wording is kept but marked outdated until it is re-translated."""
    path = PROFILE / "career.json"
    career = load_json(path, {})
    hit = _bullet_index(career).get(body.get("bullet"))
    if not hit:
        return {"ok": False, "err": "no bullet with that id"}
    _, b = hit
    text = str(body.get("text") or "").strip()
    text_de = body.get("text_de")
    if text:
        problem = vet_career_text(text)
        if problem:
            return {"ok": False, "err": problem}
        if text != b.get("text"):
            b["text"] = text
            if b.get("text_de") and text_de is None:
                b["text_de_stale"] = True
    if text_de is not None:
        text_de = str(text_de).strip()
        problem = vet_career_text(text_de)
        if problem:
            return {"ok": False, "err": problem}
        if text_de:
            b["text_de"] = text_de
        else:
            b.pop("text_de", None)
        b.pop("text_de_stale", None)
    save_json_atomic(path, career)
    return {"ok": True, "de_stale": bool(b.get("text_de_stale"))}


def api_build_preset(body):
    """Save or delete a named preset: base, language and dials."""
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        return {"ok": False, "err": "a preset needs a name"}
    presets = load_json(CV_PRESETS, {})
    if body.get("delete"):
        presets.pop(name, None)
    else:
        spec = body.get("spec") or {}
        presets[name] = {k: spec.get(k) for k in ("base", "lang", "dials")}
    save_json_atomic(CV_PRESETS, presets)
    return {"ok": True, "presets": sorted(presets)}


def api_build_preset_load(body):
    presets = load_json(CV_PRESETS, {})
    preset = presets.get(str(body.get("name") or ""))
    if not preset:
        return {"ok": False, "err": "no such preset"}
    return {"ok": True, "preset": preset}


def _checks(text, company=""):
    """claim_check + voice_check findings for a short generated text."""
    sys.path.insert(0, str(ROOT / "tools"))
    import claim_check  # noqa: E402
    import voice_check  # noqa: E402
    found = voice_check.scan(text, voice_check.load_banned()) + claim_check.scan(text, company)
    return [f for f in found if f["level"] in ("FAIL", "WARN")]


def _shown_evidence(spec, ctx, B):
    plan = B.plan(spec, ctx)
    lang = spec.get("lang", "en")
    lines = []
    for g in (plan["jobs"], plan["projects"]):
        for x in g:
            r = x["role"]
            for b in x["bullets"]:
                text = (b.get("text_de") if lang == "de" and b.get("text_de") else b.get("text"))
                lines.append("- [%s, %s] %s" % (r.get("title", ""), r.get("org", ""), text))
    return plan, lines


def api_build_summary(body):
    """AI draft of the 2-3 line profile summary, grounded in what this CV shows.
    Returned for approval with the claim and voice findings; nothing is saved."""
    B, S = _builder()
    sys.path.insert(0, str(ROOT / "tools"))
    import claude_run  # noqa: E402
    entry = _build_entry(body)
    ctx = _build_ctx(B, entry)
    spec = body.get("spec") or {}
    problems = B.validate(spec, ctx)
    if problems:
        return {"ok": False, "err": " ".join(problems)}
    posting, _ = _posting_for(entry)
    plan, evidence = _shown_evidence(spec, ctx, B)
    lead = ctx["by_id"][B.lead_of(spec)]
    strong = [ctx["by_id"][k]["label"] for k, v in spec["dials"].items() if v == "strong"]
    tenure = (ctx["career"].get("tenure_claim") or {}).get("defensible", [])
    gaps = [r["text"] for r in S.requirements(posting, spec, ctx) if r["status"] == "gap"] if posting else []
    de = spec.get("lang") == "de"
    prompt = "\n".join([
        "Write the profile summary at the top of a CV. Return only the summary text, "
        "nothing else: no heading, no quotes, no explanation.",
        "Language: %s." % ("German, as in a German Lebenslauf (Kurzprofil)" if de else "American English"),
        "Length: 2 or 3 sentences, at most 55 words. Implied first person, no 'I' "
        "(e.g. 'Enablement lead who ...').",
        "Target role: %s." % (spec.get("headline") or entry.get("role", "")),
        "Lead angle: %s: %s" % (lead["label"], lead["description"]),
        "Supporting angles: %s." % (", ".join(strong) or "none"),
        "Use only facts from the evidence and tenure lines below. Every claim must be "
        "literally supported there. Do not raise scope: no 'sole', 'led', 'managed', "
        "'entire' unless the evidence says so. No numbers that are not in the evidence.",
        "Style: no em dashes; never use: passionate, leverage, synergy, seamless, robust, "
        "cutting-edge, proven track record, results-driven, dynamic, spearheaded.",
        "Do not mention these gaps from the posting; they are not their experience: %s"
        % ("; ".join(gaps[:4]) or "none"),
        "",
        "Tenure lines (defensible):",
    ] + ["- " + t.split(" - ")[0] for t in tenure] + ["", "Evidence (what the CV shows):"] + evidence[:30])
    ok, text = claude_run.ask(prompt)
    if not ok:
        return {"ok": False, "err": text}
    text = " ".join(text.split())
    return {"ok": True, "text": text, "findings": _checks(text, entry.get("company", ""))}


def _translate_prompt(career, texts):
    examples = [x.get("text_de") for r in career.get("roles", []) for x in r.get("bullets", [])
                if x.get("text_de") and not x.get("text_de_stale")][:4]
    never = "; ".join("%s (use %s)" % (x.get("term"), x.get("instead"))
                      for x in load_json(PROFILE / "de-glossary.json", {}).get("never_use", []))
    rules = [
        "Keep product, company and course names as they are. Keep every number exactly. "
        "Use the nominal style of German CVs, like the examples. No dashes of any kind "
        "(no em dash, no en dash): use commas or a colon. Do not add or remove any claim.",
        "These German words claim a credential they do not hold; never use them: " + never,
        "", "Examples of their existing German bullets:"] + ["- " + e for e in examples]
    if len(texts) == 1:
        return "\n".join(["Translate this CV bullet into German for a German Lebenslauf. "
                          "Return only the German line."] + rules
                         + ["", "Bullet to translate:", texts[0]])
    return "\n".join(["Translate these CV bullets into German for a German Lebenslauf. "
                      "Return only a JSON array of strings, one German line per bullet, "
                      "in the same order, and nothing else."] + rules
                     + ["", "Bullets to translate:"]
                     + ["%d. %s" % (i + 1, t) for i, t in enumerate(texts)])


def _clean_de(text):
    text = " ".join(str(text).strip().strip('"').split())
    # A dash used as a pause becomes a comma: mechanical, and the style rule
    # the model most often slips on in German.
    return re.sub(r"\s+[\u2013\u2014-]\s+", ", ", text)


def api_build_translate(body):
    """AI German versions of bullets, for approval. Nothing is saved here:
    accepting one goes through /api/build/edit like any other wording.

    One bullet (`bullet`) or several at once (`bullets`): a German CV can leave
    out fifteen untranslated bullets, and fifteen separate requests meant
    several minutes of waiting for one click."""
    sys.path.insert(0, str(ROOT / "tools"))
    import claude_run  # noqa: E402
    career = load_json(PROFILE / "career.json", {})
    index = _bullet_index(career)
    ids = body.get("bullets") if isinstance(body.get("bullets"), list) else [body.get("bullet")]
    ids = [i for i in ids if i in index][:30]
    if not ids:
        return {"ok": False, "err": "no bullet with that id"}
    texts = [index[i][1].get("text", "") for i in ids]
    ok, answer = claude_run.ask(_translate_prompt(career, texts), timeout=240 + 20 * len(ids))
    if not ok:
        return {"ok": False, "err": answer}
    if len(ids) == 1:
        text = _clean_de(answer)
        return {"ok": True, "text": text, "findings": _checks(text),
                "items": [{"id": ids[0], "text": text, "findings": _checks(text)}]}
    m = re.search(r"\[.*\]", answer, re.S)
    try:
        lines = json.loads(m.group(0)) if m else []
    except ValueError:
        lines = []
    if len(lines) != len(ids):
        return {"ok": False, "err": "the translation came back with %d lines for %d bullets; "
                                    "try again, or translate them one at a time"
                                    % (len(lines), len(ids))}
    items = [{"id": i, "text": _clean_de(t), "findings": _checks(_clean_de(t))}
             for i, t in zip(ids, lines)]
    return {"ok": True, "items": items}


def build_letter_scaffold(entry, spec, ctx, B, posting):
    """letter.md for a Build-panel application: the frontmatter and the notes
    come from the base, the dials and what this CV actually shows."""
    _, S = _builder()
    lead = ctx["by_id"][B.lead_of(spec)]
    strong = [ctx["by_id"][k] for k, v in spec["dials"].items() if v == "strong"]
    _, evidence = _shown_evidence(spec, ctx, B)
    reqs = S.requirements(posting, spec, ctx) if posting else []
    asks = [r["text"] for r in reqs if r["status"] != "gap"][:3]
    gaps = [r["text"] for r in reqs if r["status"] == "gap"][:4]
    avoid = sorted({a for t in [lead] + strong for a in t.get("avoid", [])})[:10]
    service = spec["base"] == "service"
    lines = ['- TODO answer this, with evidence: "%s"' % a for a in asks] or [
        "- TODO the single most relevant thing from the posting, with evidence"]
    body = "\n".join([
        "TODO opening. One sentence on why this specific role, referring to something",
        "only true of this company.", "",
        ("TODO why this role now, in one plain sentence (a deliberate change of direction, "
         "comfortable at this level), and availability." if service else
         "TODO the lead angle, in your own words."), "",
    ] + lines + ["", "TODO closing. What you want to happen next, in one sentence."])
    notes = "\n".join([
        "<!--",
        "Built from the CV builder (applications/<slug>/build.json).",
        "Base: %s. Tone: %s." % (ctx["threads"]["bases"][spec["base"]]["label"],
                                  ctx["threads"]["bases"][spec["base"]]["tone"]),
        "Lead angle: %s - %s" % (lead["label"], lead["description"]),
        "Supporting: %s" % (", ".join(t["label"] for t in strong) or "none"),
        "Never use: %s" % ", ".join(avoid),
        "Not found in the data (leave these out of the letter; never say he lacks or has "
        "not done them, because the data being silent is not the same as him not having "
        "the experience): %s" % ("; ".join(gaps) or "none"),
        "Confirmed gaps he may state, plainly and once, if central: %s"
        % ("; ".join(g.get("text", "") for g in ctx["career"].get("confirmed_gaps") or []) or "none"),
        "Evidence the CV shows (draw from these, do not restate them):",
    ] + evidence[:24] + ["-->"])
    return ("---\ncompany: %s\nrole: %s\nrecipient: TODO the contact person the posting "
            "names, else \"Hiring Team\" / \"Personalabteilung\"\ncity: \nlang: %s\n---\n\n"
            "%s\n\n%s\n" % (entry.get("company", ""), spec.get("headline") or
                           clean_title(entry.get("role", "")), spec.get("lang", "en"), body, notes))


def api_build_letter(body):
    """Write the Build-aware letter scaffold (never over a drafted letter), and
    optionally run Draft with AI on it."""
    B, _ = _builder()
    entry = _build_entry(body)
    ctx = _build_ctx(B, entry)
    spec = body.get("spec") or {}
    problems = B.validate(spec, ctx)
    if problems:
        return {"ok": False, "err": " ".join(problems)}
    out = app_dir(entry["id"])
    out.mkdir(parents=True, exist_ok=True)
    save_json_atomic(out / "build.json", spec)
    posting, note = _posting_for(entry)
    letter = out / "letter.md"
    sys.path.insert(0, str(ROOT / "render"))
    from letter import find_todos  # noqa: E402
    drafted = letter.exists() and len(find_todos(letter.read_text(encoding="utf-8"))) < 2
    if drafted and not body.get("replace"):
        written = False
    else:
        letter.write_text(build_letter_scaffold(entry, spec, ctx, B, posting), encoding="utf-8")
        written = True
    res = {"ok": True, "scaffold_written": written, "letter": str(letter), "slug": out.name}
    if body.get("draft"):
        d = api_letter_draft({"slug": out.name})
        res.update({"ok": d["ok"], "out": d.get("out", ""), "err": d.get("err", "")})
    return res


ROUTES_GET = {
    "/api/status": api_status,
    "/api/claude-auth": api_claude_auth,
    "/api/watchlist": api_watchlist,
    "/api/career": api_career,
    "/api/pipeline": api_pipeline,
    "/api/sources": api_sources,
    "/api/workspace": api_workspace,
    "/api/posting": api_posting,
    "/api/captures": api_captures,
    "/api/today": api_today,
    "/api/notes/count": api_notes_count,
    "/api/settings": api_settings,
    "/api/log": api_log,
}
ROUTES_POST = {
    "/api/letter": api_letter,
    "/api/letter/draft": api_letter_draft,
    "/api/fit/analyze": api_fit_analyze,
    "/api/screen": api_screen,
    "/api/package": api_package,
    "/api/posting/save": api_posting_save,
    "/api/open": api_open,
    "/api/pipeline/add": api_pipeline_add,
    "/api/pipeline/update": api_pipeline_update,
    "/api/pipeline/qualify": api_qualify,
    "/api/pipeline/delete": api_pipeline_delete,
    "/api/pipeline/log": api_pipeline_log,
    "/api/pipeline/report-wrong": api_pipeline_report_wrong,
    "/api/sources/run": api_sources_run,
    "/api/sources/discover": api_sources_discover,
    "/api/sources/add": api_sources_add,
    "/api/sources/toggle": api_sources_toggle,
    "/api/import": api_import,
    "/api/posting/capture": api_posting_capture,
    "/api/captures/attach": api_captures_attach,
    "/api/captures/dismiss": api_captures_dismiss,
    "/api/notes/add": api_notes_add,
    "/api/settings/availability": api_settings_availability,
    "/api/settings/thresholds": api_settings_thresholds,
    "/api/settings/send-folder": api_settings_send_folder,
    "/api/settings/term": api_settings_term,
    "/api/settings/company": api_settings_company,
    "/api/career/certification": api_career_certification,
    "/api/career/certification/delete": api_career_certification_delete,
    "/api/career/bullet": api_career_bullet,
    "/api/career/bullet/update": api_career_bullet_update,
    "/api/career/skill": api_career_skill,
    "/api/doc-status": api_doc_status,
    "/api/build/state": api_build_state,
    "/api/build/preview": api_build_preview,
    "/api/build/save": api_build_save,
    "/api/build/finalize": api_build_finalize,
    "/api/build/star": api_build_star,
    "/api/build/edit": api_build_edit,
    "/api/build/preset": api_build_preset,
    "/api/build/preset/load": api_build_preset_load,
    "/api/build/summary": api_build_summary,
    "/api/build/translate": api_build_translate,
    "/api/build/letter": api_build_letter,
}

# The only endpoint reachable from a page that is not this app's own origin.
# See the comment above api_posting_capture for why that is an acceptable,
# narrowly-scoped exception to "this server only ever talks to itself".
CORS_PATHS = {"/api/posting/capture"}


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "JobSearchUI/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # Any web page open in any browser tab can send requests to 127.0.0.1.
    # A cross-site POST with Content-Type text/plain needs no permission from
    # this server, and do_POST parsed every body as JSON regardless, so a
    # page visited in passing could rewrite career.json bullets or delete
    # pipeline entries. And with no Host check, a DNS-rebinding page could
    # read everything back. These two checks close both.
    def _local_names(self):
        port = self.server.server_address[1]
        return {"127.0.0.1:%d" % port, "localhost:%d" % port}

    def _host_ok(self):
        return (self.headers.get("Host") or "").lower() in self._local_names()

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if origin is None:  # not a browser page: the smoke test, curl, a script
            return True
        return origin.lower() in {"http://" + n for n in self._local_names()}

    def _send(self, code, payload, ctype="application/json; charset=utf-8", cors=False):
        raw = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"err": "refused: unexpected Host header"})
        parsed = urlparse(self.path)
        path = parsed.path

        # A rendered PDF or letter, served raw for the in-app viewer (an
        # iframe over this URL). Handled before ROUTES_GET, which assumes
        # every handler returns JSON; this one returns a file's own bytes and
        # its own content type, the same shape as the static-file branch
        # below serves this app's own HTML/CSS/JS, just for a path outside
        # the web/ folder and guarded by inside_project instead.
        if path == "/api/file":
            target = (parse_qs(parsed.query).get("path") or [""])[0]
            if not target or not inside_project(target) or not Path(target).is_file():
                return self._send(404, {"err": "refused: path must exist inside the project"})
            p = Path(target)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            # Shown in the viewer, not downloaded: markdown and text as text.
            if p.suffix.lower() in (".md", ".txt", ".json"):
                ctype = "text/plain; charset=utf-8"
            try:
                return self._send(200, p.read_bytes(), ctype)
            except OSError as exc:
                # is_file() passing a moment ago does not guarantee the read
                # still succeeds now - a PDF open in a viewer, or a render
                # replacing it mid-request, raises here on Windows. This is
                # exactly the file this app's own PDF/letter viewer iframe
                # depends on, so a clean error beats a dropped connection.
                return self._send(409, {"err": "could not read %s: %s" % (p.name, exc)})

        if path in ROUTES_GET:
            fn = ROUTES_GET[path]
            try:
                import inspect
                if inspect.signature(fn).parameters:
                    return self._send(200, fn(parse_qs(parsed.query)))
                return self._send(200, fn())
            except Exception as exc:  # noqa: BLE001 - surface it in the UI
                app_log("ERROR", "Load " + path.replace("/api/", ""), "",
                        "%s: %s" % (type(exc).__name__, exc))
                return self._send(500, {"err": "%s: %s" % (type(exc).__name__, exc)})

        name = "ui.html" if path in ("/", "/index.html") else path.lstrip("/")
        target = (WEB / name).resolve()
        # relative_to, not str.startswith: a sibling directory that merely
        # starts with "web" (e.g. a hypothetical web-old/) would pass a plain
        # prefix check with no separator boundary. Not exploitable today (no
        # such sibling exists), but this is the one static-asset branch that
        # was not using the same inside_project()-style check as every other
        # path in this file, which CLAUDE.md documents as universal.
        try:
            target.relative_to(WEB)
        except ValueError:
            return self._send(404, {"err": "not found"})
        if not target.is_file():
            return self._send(404, {"err": "not found"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        try:
            data = target.read_bytes()
        except OSError as exc:
            return self._send(409, {"err": "could not read %s: %s" % (target.name, exc)})
        return self._send(200, data,
                          ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))

    def do_OPTIONS(self):
        """CORS preflight, for the one endpoint a bookmarklet on another
        origin needs to reach. Nothing else answers OPTIONS."""
        path = urlparse(self.path).path
        if path not in CORS_PATHS:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ROUTES_POST:
            return self._send(404, {"err": "not found"})
        cors = path in CORS_PATHS
        if not self._host_ok():
            return self._send(403, {"err": "refused: unexpected Host header"}, cors=cors)
        if not cors:
            ctype = (self.headers.get("Content-Type") or "").lower()
            if not self._same_origin() or not ctype.startswith("application/json"):
                return self._send(403, {"err": "refused: requests must come from this "
                                               "app's own page, as JSON"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError) as exc:
            return self._send(400, {"err": "bad request: %s" % exc}, cors=cors)
        # Every handler reads fields with body.get(); a JSON null or array got
        # as far as that and failed as a 500 with a Python error in the UI.
        if not isinstance(body, dict):
            return self._send(400, {"err": "bad request: expected a JSON object"}, cors=cors)
        action = ACTION_NAMES.get(path, path)
        subject = str(body.get("id") or body.get("slug") or body.get("company") or "")[:80]
        started = time.time()
        try:
            res = ROUTES_POST[path](body)
        except Exception as exc:  # noqa: BLE001
            import traceback
            app_log("ERROR", action, subject,
                    "%s: %s\n%s" % (type(exc).__name__, exc,
                                    "".join(traceback.format_exc().splitlines(True)[-6:])))
            return self._send(500, {"err": "%s: %s" % (type(exc).__name__, exc)}, cors=cors)
        took = " (%.1fs)" % (time.time() - started)
        failed = isinstance(res, dict) and res.get("ok") is False
        if failed:
            app_log("FAILED", action, subject + took, result_detail(res))
        elif path not in QUIET_ACTIONS:
            app_log("ok", action, subject + took,
                    "\n".join("warning: %s" % w for w in (res.get("warnings") or []))
                    if isinstance(res, dict) else "")
        return self._send(200, res, cors=cors)


class Server(ThreadingHTTPServer):
    """A server that refuses to share its port.

    ThreadingHTTPServer sets SO_REUSEADDR, and on Windows that permits a second
    socket to bind a port another process is already serving. Launching the
    shortcut twice then leaves two servers on 8777, each announcing 8777, with
    requests landing on whichever socket the OS picks and both writing to the
    same files. Failing the bind instead lets the loop below move to the next
    port, so the second window is a second server on 8778 and says so.
    """

    allow_reuse_address = False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--no-desktop", action="store_true",
                    help="do not copy rendered files to Desktop\\Job Applications "
                         "(for testing: a test render once replaced a real CV there)")
    args = ap.parse_args()
    if args.no_desktop:
        global sync_to_desktop  # noqa: PLW0603
        sync_to_desktop = lambda *a, **k: None  # noqa: E731

    port = args.port
    for attempt in range(10):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    else:
        sys.exit("could not find a free port between %d and %d" % (args.port, port))

    url = "http://127.0.0.1:%d/" % port
    app_log("start", "App started", url)
    catch_up_drafted()
    threading.Thread(target=background_scoring, daemon=True).start()
    print("Job search UI")
    print("  %s" % url)
    print("  project: %s" % ROOT)
    print("  close this window to stop")
    # Flushed, because the port is the one thing you need and stdout to a pipe
    # is block-buffered: launched non-interactively it otherwise says nothing.
    print(flush=True)
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
