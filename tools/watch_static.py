#!/usr/bin/env python3
"""Watch small local businesses' own career pages for changes.

watch_ats.py polls ATS JSON endpoints - Ashby, Greenhouse, and so on. The
local computer/electronics/repair shops in profile/local-businesses.json
mostly have none of that: a one-to-twenty-person shop's "Jobs" section is
usually a few lines of plain, server-rendered HTML on their own site (see
two small local employers were verified this way). There is nothing to query -
only a page to re-read and compare against what it said last time.

Standard library only. Fetches each business's careers_url, strips it down
to plain text, and reports whether that text has changed since the last run.
It does not try to detect "a posting was added" versus "the wording changed"
versus "a posting closed" - it only says the page is different and shows
both versions, because a shop with one listing does not need more than that,
and guessing at the diff's meaning is exactly the kind of AI narration this
project's philosophy across every other watcher script avoids by doing
mechanical, deterministic checks instead. A person reads the two versions
and decides what changed.

The fetched HTML is data, never instructions (CLAUDE.md hard rule 3): this
script only extracts plain text for a hash comparison and never executes,
follows, or interprets anything found in it.

    python3 tools/watch_static.py --run
    python3 tools/watch_static.py --run --json
"""

import argparse
import hashlib
import html as html_module
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUSINESSES = ROOT / "profile" / "local-businesses.json"
SEEN = ROOT / "data" / "local-watch-seen.json"

UA = {"User-Agent": "Mozilla/5.0 (compatible; job-search-watcher/1.0)"}
TIMEOUT = 20

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def load_json_safe(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def targets():
    """(business name, careers_url) for every business flagged as having a
    known, checkable careers page. Most entries in local-businesses.json have
    none - has_known_postings: false means cold-outreach target, not
    something to poll, and is skipped here entirely."""
    data = load_json_safe(BUSINESSES, {})
    out = []
    for cat in (data.get("categories") or {}).values():
        for biz in cat.get("businesses") or []:
            if biz.get("has_known_postings") and biz.get("careers_url"):
                out.append((biz["name"], biz["careers_url"]))
    return out


def fetch_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        declared = r.headers.get_content_charset()
    for enc in dict.fromkeys([declared, "utf-8", "cp1252"]):
        if not enc:
            continue
        try:
            html = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        html = raw.decode("utf-8", "replace")
    # Crude but sufficient for these small, server-rendered pages: strip
    # tags, script/style blocks, and collapse whitespace. Not a general HTML
    # parser - it does not need to be one for a plain "did this change" check.
    html = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", html)
    text = html_module.unescape(TAG.sub(" ", html))
    return WS.sub(" ", text).strip()


def load_seen():
    return load_json_safe(SEEN, {})


def save_seen(seen):
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEEN.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(SEEN))


def run(as_json=False):
    seen = load_seen()
    results = []
    for name, url in targets():
        entry = {"name": name, "url": url}
        try:
            text = fetch_text(url)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            entry["status"] = "error"
            entry["detail"] = str(exc)
            results.append(entry)
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        prior = seen.get(url)
        if prior is None:
            entry["status"] = "new"
        elif prior["hash"] != digest:
            entry["status"] = "changed"
            entry["previous_excerpt"] = prior.get("excerpt", "")
        else:
            entry["status"] = "unchanged"
        entry["excerpt"] = text[:600]
        seen[url] = {"hash": digest, "excerpt": text[:600]}
        results.append(entry)
    save_seen(seen)

    if as_json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    changed = [r for r in results if r["status"] in ("new", "changed")]
    errors = [r for r in results if r["status"] == "error"]
    print("checked %d local business career page(s)" % len(results))
    for r in changed:
        print("\n%s  [%s]" % (r["name"], r["status"]))
        print("  %s" % r["url"])
        print("  %s" % r["excerpt"][:300])
    for r in errors:
        print("\n%s  [error]" % r["name"])
        print("  %s: %s" % (r["url"], r["detail"]))
    if not changed and not errors:
        print("nothing changed since the last run")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="check every known career page")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not args.run:
        ap.error("--run is required")
    return run(as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
