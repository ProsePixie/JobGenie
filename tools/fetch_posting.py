#!/usr/bin/env python3
"""Fetch the text of a job posting from the link recorded on its pipeline entry.

The watchers record a title, a company and a link, never the posting itself, so
every entry they found reached Prepare with nothing for the letter drafter or
the persona scorer to read. This closes that gap for the one link the entry
already carries.

Hard rule 3 still holds. The only URL fetched is the entry's own. Nothing found
inside a posting is ever followed, including the Bundesagentur's `externeURL`,
which points at a third-party board. The text is data: a posting containing
text addressed to an AI is refused rather than saved, and the matching passage
is reported so a person can read it.

    py tools/fetch_posting.py https://www.arbeitsagentur.de/jobsuche/jobdetail/12811-2332826-S
"""

import base64
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 20
UA = {"User-Agent": "Mozilla/5.0 (job-search personal tool)"}

# The Bundesagentur's public key, the same constant tools/watch_ats.py uses for
# the search. The detail endpoint takes the reference number base64-encoded.
BA_DETAIL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/%s"
BA_KEY = "jobboerse-jobsuche"
BA_LINK = re.compile(r"arbeitsagentur\.de/jobsuche/jobdetail/([^/?#]+)", re.I)

# Text written for a model rather than a reader, screened by the one shared
# screen. The old pattern here matched any mention of ChatGPT, Claude or an
# "AI assistant", which refused most of the AI enablement postings this search
# is for. tools/posting_screen.py flags text addressed to an AI, not about it.
from posting_screen import screen as _screen  # noqa: E402


class FetchError(Exception):
    pass


def ai_directed(text):
    """The first passage that reads as addressed to an AI, or None."""
    return _screen(text)[1]


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            charset = r.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError("could not fetch %s: %s" % (url, exc))
    return raw.decode(charset, "replace")


def job_posting_ld(page):
    """The posting from a page's schema.org JobPosting block, or "".

    Most boards and aggregators embed one for search engines. The visible page
    around it is navigation: an Arbeitnow page saved as the "posting" was ten
    thousand characters of city and category menus, and the CV suggestion
    scored "Minijob" and "Quereinsteiger" from it.
    """
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page):
        try:
            data = json.loads(html.unescape(block.strip()))
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for d in items:
            if not isinstance(d, dict):
                continue
            kind = d.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                org = d.get("hiringOrganization") or {}
                loc = d.get("jobLocation") or {}
                loc = loc[0] if isinstance(loc, list) and loc else loc
                addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
                head = [d.get("title") or "",
                        org.get("name", "") if isinstance(org, dict) else str(org),
                        addr.get("addressLocality", "") if isinstance(addr, dict) else ""]
                body = html_to_text(html.unescape(d.get("description") or ""))
                if len(body) >= 200:
                    return "\n".join(h for h in head if h) + "\n\n" + body
    return ""


def page_text(page):
    """Posting text from a generic page: the JobPosting block if there is one,
    else the <main> or <article> element, else the whole page, with navigation,
    header and footer removed in every case."""
    ld = job_posting_ld(page)
    if ld:
        return ld
    page = re.sub(r"(?is)<(nav|header|footer|aside)\b[^>]*>.*?</\1>", " ", page)
    for tag in ("main", "article"):
        m = re.search(r"(?is)<%s\b[^>]*>(.*)</%s>" % (tag, tag), page)
        if m and len(html_to_text(m.group(1))) >= 200:
            return html_to_text(m.group(1))
    return html_to_text(page)


def html_to_text(page):
    """Visible text of an HTML page, one block per line. Crude on purpose:
    good enough for a posting page, and no dependency."""
    page = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", page)
    page = re.sub(r"(?i)<li[^>]*>", "- ", page)
    page = re.sub(r"<[^>]+>", " ", page)
    lines = [" ".join(html.unescape(ln).split()) for ln in page.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def restore_lines(text):
    """Put back the line structure the Bundesagentur flattens away.

    Its descriptions arrive as one paragraph. List items are separated by a
    non-breaking space next to a normal one (a lone non-breaking space also
    appears inside phrases, so it alone is not a break), and section headings
    end in a colon. Everything downstream (the requirement quotes in the letter
    scaffold, the prescreen's section scoping) reads line by line, and on one
    paragraph it found nothing. Some items are joined by a plain space only;
    those stay on one line, which is untidy but loses nothing.
    """
    text = re.sub(r"\xa0[ \t]|[ \t]\xa0|[ \t]{2,}", "\n", text)
    text = text.replace("\xa0", " ")
    # "Deine Skills: Du liebst..." -> heading, then the list. Not "10:00".
    text = re.sub(r"(?<=[A-Za-zÄÖÜäöüß)]):[ \t]+(?=\S)", ":\n", text)
    out, in_list = [], False
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if line.endswith(":") and len(line) <= 80:
            out += ["", line]
            in_list = True
        elif in_list and len(line) <= 200:
            out.append("- " + line)
        else:
            out.append(line)
            in_list = False
    return "\n".join(out).strip()


def fetch_bundesagentur(ref):
    ref = urllib.parse.unquote(ref)
    enc = base64.b64encode(ref.encode("utf-8")).decode("ascii")
    try:
        d = json.loads(_get(BA_DETAIL % enc, {"X-API-Key": BA_KEY,
                                             "Accept": "application/json"}))
    except ValueError:
        raise FetchError("the Bundesagentur answered with something that is not JSON")
    body = (d.get("stellenangebotsBeschreibung") or "").strip()
    if not body:
        raise FetchError("the Bundesagentur has no description for %s "
                         "(the posting may have expired)" % ref)
    where = ((d.get("stellenlokationen") or [{}])[0].get("adresse") or {})
    head = [
        d.get("stellenangebotsTitel") or "",
        d.get("firma") or "",
        " ".join(x for x in (where.get("plz"), where.get("ort")) if x),
    ]
    terms = []
    if d.get("arbeitszeitVollzeit"):
        terms.append("Vollzeit")
    if d.get("homeofficemoeglich"):
        terms.append("Homeoffice möglich")
    if d.get("vertragsdauer"):
        terms.append(d["vertragsdauer"].replace("_", " ").lower())
    if terms:
        head.append(", ".join(terms))
    return "\n".join(h for h in head if h) + "\n\n" + restore_lines(body)


# The job boards the watcher polls render their posting pages in JavaScript, so
# fetching the page returns a shell. Each has a public JSON API that serves the
# same posting; the id comes from the entry's own link, and nothing else is fetched.
ASHBY_LINK = re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", re.I)
GREENHOUSE_LINK = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#&]+)(?:/jobs/|&token=)(\d+)", re.I)
LEVER_LINK = re.compile(r"jobs\.(?:eu\.)?lever\.co/([^/?#]+)/([0-9a-f-]{36})", re.I)


def _json(url):
    try:
        return json.loads(_get(url, {"Accept": "application/json"}))
    except ValueError:
        raise FetchError("the job board answered %s with something that is not JSON" % url)


def fetch_ashby(board, job_id):
    d = _json("https://api.ashbyhq.com/posting-api/job-board/%s" % board)
    for j in d.get("jobs") or []:
        if (j.get("id") or "").lower() == job_id.lower() or job_id.lower() in (j.get("jobUrl") or "").lower():
            head = [j.get("title") or "", j.get("location") or "",
                    ", ".join(x for x in (j.get("employmentType"), j.get("workplaceType")) if x)]
            body = html_to_text(j.get("descriptionHtml") or "") or j.get("descriptionPlain") or ""
            return "\n".join(h for h in head if h) + "\n\n" + body
    raise FetchError("the Ashby board %r no longer lists this posting (it may have closed)" % board)


def fetch_greenhouse(board, job_id):
    d = _json("https://boards-api.greenhouse.io/v1/boards/%s/jobs/%s" % (board, job_id))
    head = [d.get("title") or "", (d.get("location") or {}).get("name") or ""]
    return "\n".join(h for h in head if h) + "\n\n" + html_to_text(html.unescape(d.get("content") or ""))


def fetch_lever(board, job_id):
    host = "api.eu.lever.co" if "eu.lever.co" in board else "api.lever.co"
    d = _json("https://%s/v0/postings/%s/%s" % (host, board, job_id))
    parts = [d.get("text") or "", (d.get("categories") or {}).get("location") or "", "",
             html_to_text(d.get("description") or "")]
    for block in d.get("lists") or []:
        parts += ["", (block.get("text") or "") + ":", html_to_text(block.get("content") or "")]
    parts += ["", html_to_text(d.get("additional") or "")]
    return "\n".join(parts).strip()


def fetch_posting(url):
    """Posting text for a pipeline entry's own URL. Raises FetchError."""
    if not url or not re.match(r"https?://", url, re.I):
        raise FetchError("this entry has no web link to fetch the posting from")
    m = BA_LINK.search(url)
    if m:
        text = fetch_bundesagentur(m.group(1))
    elif ASHBY_LINK.search(url):
        text = fetch_ashby(*ASHBY_LINK.search(url).groups())
    elif GREENHOUSE_LINK.search(url):
        text = fetch_greenhouse(*GREENHOUSE_LINK.search(url).groups())
    elif LEVER_LINK.search(url):
        text = fetch_lever(*LEVER_LINK.search(url).groups())
    else:
        text = page_text(_get(url))
    if len(text) < 200:
        raise FetchError("the page at %s returned too little text to be a posting; "
                         "it probably needs a browser. Paste the posting in instead." % url)
    flagged = ai_directed(text)
    if flagged:
        raise FetchError("the posting contains text addressed to an AI, so it was not "
                         "saved. Read it before deciding what to do:\n\n    %s" % flagged)
    return text


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        print(fetch_posting(sys.argv[1]))
    except FetchError as exc:
        sys.exit(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
