#!/usr/bin/env python3
"""Poll company job boards directly, at their ATS endpoints.

Most careers pages render their listings in JavaScript, so fetching the page
gets you a shell and no jobs. The applicant tracking systems behind them almost
all expose a public JSON endpoint intended for exactly this. That is what this
polls.

Standard library only.

    py tools/watch_ats.py --discover "Hoxhunt"   find which ATS a company uses
    py tools/watch_ats.py --add "Hoxhunt" --ats ashby --slug hoxhunt
    py tools/watch_ats.py --run                  poll everything configured
    py tools/watch_ats.py --run --all            ignore the seen history
    py tools/watch_ats.py --run --json

Config lives in profile/sources.json. New roles are matched against the target
terms in profile/watchlist.json, so a security company's finance vacancies do
not end up in the shortlist. Everything seen is recorded in data/jobs-seen.jsonl
so a later run only reports what is genuinely new.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "profile" / "sources.json"
WATCHLIST = ROOT / "profile" / "watchlist.json"
AVAILABILITY = ROOT / "profile" / "availability.json"
SEEN = ROOT / "data" / "jobs-seen.jsonl"

UA = {"User-Agent": "Mozilla/5.0 (compatible; job-search-watcher/1.0)"}
TIMEOUT = 20

# url template, and how to pull (title, location, link) out of the response
ATS = {
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    "personio": "https://{slug}.jobs.personio.de/search.json",
    "arbeitnow": "https://www.arbeitnow.com/api/job-board-api",
    "arbeitsagentur": "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs",
}

# The Bundesagentur board is the only source here that covers local employers:
# retail, logistics, hospitals, public sector. It takes a postal code and a
# radius, which is what makes a 25 km search possible at all. The key is a
# public constant used by the agency's own site, not a secret, and it is
# documented at github.com/bundesAPI/jobsuche-api. Note the version: v4 and v5
# answer 403 and only v6 is live.
BA_KEY = "jobboerse-jobsuche"

# arbeitszeit values the board accepts, for reference when editing sources.json:
#   vz Vollzeit   tz Teilzeit   ho home office   mj Minijob   snw shift/night/weekend
BA_DEFAULTS = {"angebotsart": "1", "size": "100"}


def load_json_safe(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch(url, headers=None):
    """Fetch and decode one ATS response.

    Not every board serves UTF-8. At least one greenhouse feed answers in
    cp1252, and decoding that as UTF-8 turns "Triebfahrzeugfuehrer" into a row
    of replacement characters, which then ends up in the shortlist.
    """
    req = urllib.request.Request(url, headers=dict(UA, **(headers or {})))
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        declared = r.headers.get_content_charset()
    for enc in dict.fromkeys([declared, "utf-8", "cp1252"]):
        if not enc:
            continue
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, LookupError, ValueError):
            continue
    return json.loads(raw.decode("utf-8", "replace"))


def norm(ats, payload, company):
    """Flatten one ATS response into a common shape."""
    rows = []
    if ats == "ashby":
        for j in payload.get("jobs", []):
            rows.append((j.get("title"), j.get("location"), j.get("jobUrl")))
    elif ats == "greenhouse":
        for j in payload.get("jobs", []):
            rows.append((j.get("title"), (j.get("location") or {}).get("name"),
                         j.get("absolute_url")))
    elif ats == "lever":
        for j in payload if isinstance(payload, list) else []:
            rows.append((j.get("text"), (j.get("categories") or {}).get("location"),
                         j.get("hostedUrl")))
    elif ats == "smartrecruiters":
        for j in payload.get("content", []):
            loc = j.get("location") or {}
            rows.append((j.get("name"), loc.get("city"),
                         "https://jobs.smartrecruiters.com/%s" % j.get("id", "")))
    elif ats == "recruitee":
        for j in payload.get("offers", []):
            rows.append((j.get("title"), j.get("location"), j.get("careers_url")))
    elif ats == "workable":
        for j in payload.get("jobs", []):
            rows.append((j.get("title"), j.get("location"), j.get("url")))
    elif ats == "personio":
        pool = payload if isinstance(payload, list) else payload.get("data", [])
        for j in pool:
            rows.append((j.get("name") or j.get("title"), j.get("office"), j.get("url")))
    elif ats == "arbeitnow":
        for j in payload.get("data", []):
            rows.append((j.get("title"), j.get("location"), j.get("url")))
            company = j.get("company_name") or company
            rows[-1] = rows[-1] + (company,)
    out = []
    for r in rows:
        title, loc, url = r[0], r[1], r[2]
        co = r[3] if len(r) > 3 else company
        if title:
            out.append({"company": co, "title": title.strip(),
                        "location": (loc or "").strip() if isinstance(loc, str) else "",
                        "url": url or ""})
    return out


def ba_search(params, pages=3):
    """Query the Bundesagentur board and flatten it into the common shape.

    Handled apart from the slug-and-template sources because it is a search
    rather than one company's board: it takes parameters, pages, and its own
    key header. It also returns things the ATS feeds do not, so pay, distance
    and the working-time flags are carried through rather than discarded.
    """
    rows, seen_refs = [], set()
    query = dict(BA_DEFAULTS, **{k: str(v) for k, v in (params or {}).items()})
    for page in range(1, max(1, pages) + 1):
        query["page"] = str(page)
        url = "%s?%s" % (ATS["arbeitsagentur"], urllib.parse.urlencode(query))
        try:
            payload = fetch(url, {"X-API-Key": BA_KEY, "Accept": "application/json"})
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
            break
        batch = payload.get("ergebnisliste") or []
        if not batch:
            break
        for j in batch:
            ref = j.get("referenznummer") or ""
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            loc = (j.get("stellenlokationen") or [{}])[0].get("adresse") or {}
            km = j.get("entfernung")
            where = loc.get("ort") or loc.get("plz") or ""
            if km is not None and where:
                where = "%s (%s km)" % (where, km)
            rows.append({
                "company": j.get("firma") or "employer not named",
                "title": (j.get("stellenangebotsTitel") or j.get("hauptberuf") or "").strip(),
                "location": where,
                "url": ("https://www.arbeitsagentur.de/jobsuche/jobdetail/%s"
                        % urllib.parse.quote(ref, safe="")) if ref else "",
                "km": km,
                "pay": ba_pay(j),
                "schedule": ba_schedule(j),
                "posted": (j.get("veroeffentlichungszeitraum") or {}).get("von") or "",
            })
        if len(batch) < int(query.get("size", 100)):
            break
    return [r for r in rows if r["title"]]


# Confirmed live against the real API (not guessed): verguetungsangabe takes
# STUNDENLOHN, JAHRESGEHALT, or KEINE_ANGABEN in the wild. The old code
# treated anything that wasn't STUNDENLOHN as "per month" - live-observed
# mislabeling a real JAHRESGEHALT (annual) EUR 50,000-65,000 posting as a
# monthly figure. No monthly-specific value has ever been observed, so
# KEINE_ANGABEN (or any future unrecognized value) is reported without a
# guessed unit rather than repeating that mistake with a different default.
PAY_UNITS = {"STUNDENLOHN": "per hour", "JAHRESGEHALT": "per year"}


def ba_pay(j):
    """Pay as a readable string, when the advert states one. Most do not."""
    lo, hi = j.get("gehaltsspanneVon"), j.get("gehaltsspanneBis")
    if lo is None and hi is None:
        return ""
    span = ("%s-%s" % (lo, hi)) if (lo is not None and hi is not None and lo != hi) \
        else str(lo if lo is not None else hi)
    unit = PAY_UNITS.get(j.get("verguetungsangabe"))
    return "%s %s" % (span, unit) if unit else "%s (unit not stated)" % span


def ba_schedule(j):
    """The working-time flags, which decide whether a job fits the hours at all."""
    tags = []
    if j.get("arbeitszeitTeilzeit"):
        tags.append("part-time")
    if j.get("arbeitszeitVollzeit"):
        tags.append("full-time")
    if j.get("arbeitszeitSchichtNachtWochenende"):
        tags.append("shift/night/weekend")
    if j.get("arbeitszeitMinijob"):
        tags.append("minijob")
    if j.get("arbeitszeitHeimarbeitTelearbeit"):
        tags.append("home office")
    return tags


def load_terms():
    w = json.loads(WATCHLIST.read_text(encoding="utf-8")) if WATCHLIST.exists() else {}
    t = w.get("search_terms", {})
    terms = [x.lower() for x in (t.get("primary", []) + t.get("secondary", []))]
    # Single words that matter on their own, since titles vary wildly.
    terms += ["enablement", "instructional", "curriculum", "training", "trainer",
              "learning", "education", "academy", "courseware", "content producer",
              "technical writer", "documentation", "tutorial", "developer advocate",
              "onboarding"]
    # Added for the US-facing remote direction chosen 2026-09-18. Customer
    # success and solutions work is prepared performance against a product he
    # would know, which is the shape that suits him, and it is the only one of
    # the three chosen routes that carries a salary and benefits.
    terms += ["customer success", "customer education", "customer onboarding",
              "solutions consultant", "solutions engineer", "sales engineer",
              "presales", "pre-sales", "technical account", "implementation consultant",
              "technical enablement", "revenue enablement", "partner enablement",
              "certification", "knowledge base", "technical content",
              "instructional designer", "learning experience", "voice over",
              "narration", "curriculum developer", "technical instructor"]
    # German titles. Arbeitnow and several company boards are German-language,
    # and this default list had no German in it beyond "trainer", so
    # "Schulungsreferent", "Dozent" and "Weiterbildung" titles never matched.
    # Matched as substrings like the English terms, so compounds count:
    # "Kundenschulung", "Schulungsmanager", "IT-Dozent".
    terms += ["schulung", "dozent", "weiterbildung", "e-learning", "kursleiter",
              "technischer redakteur", "technische redaktion", "onboarding",
              "wissensvermittlung", "lernbegleit", "trainerin", "lehrkraft"]
    return sorted(set(terms))


# Titles that match a term for the wrong reason. The first run surfaced a
# full-stack engineer (matched "training") and a physics postdoc (matched
# "learning", from "Deep Learning"). Rejection beats a looser term list.
NEGATIVE = [
    "machine learning", "deep learning", "reinforcement learning", "ml engineer",
    "software engineer", "backend", "frontend", "full-stack", "fullstack",
    "data scientist", "data engineer", "research scientist", "research engineer",
    "pre-training", "pretraining", "postdoctoral",
    "postdoc", "phd", "account executive", "sales development", "sdr", "bdr",
    "recruiter", "controller", "accountant", "intern", "working student",
    "werkstudent", "praktikum",
    # German trades and shift work the local board surfaces through words like
    # Kundenservice and Quereinsteiger. A bakery counter and a tanning salon
    # both matched before these. "fahrer" is deliberately absent: it is a
    # substring of "erfahrener".
    "pflege", "lager", "produktion", "reinigung", "küche", "bäcker", "metzger",
    "friseur", "kosmetik", "sonnenstudio", "haushaltshilfe", "zerspanung",
    "elektriker", "monteur", "schlosser", "maler", "gabelstapler",
    # Added 2026-09-21 alongside werkschutz/objektschutz/sicherheitsmitarbeiter
    # as positive terms for physical security work: "it-sicherheit" is a
    # different job (hands-on cybersecurity engineering) that a "sicherheit"
    # root could otherwise pull in through a compound title.
    "it-sicherheit",
    # Skilled trades with a German apprenticeship behind them. He is not one
    # and cannot become one quickly, and they flooded the local results through
    # the word Elektronik.
    "elektroniker", "mechatroniker", "industriemechaniker", "montage",
    "fertigung", "prüffeld", "optoelektronik", "hardwareentwickler",
    "solarium", "sonnenstudio",
    # Safe now that German stems match only at the start of a word: "fahrer"
    # was left out before because it is a substring of "erfahrener". A LOX
    # delivery driver reached the shortlist through the word Kundenservice.
    "fahrer", "technischer zeichner", "vermessungstechnik",
    # A bare "trainer"/"training" match found two completely different job
    # meanings of those words: an autonomous-vehicle safety/test driver
    # (Wayve) and military drone-systems instruction (Quantum-Systems' "UXS
    # Training"). Neither has anything to do with corporate enablement, and
    # both slipped through because the title alone gave the term list nothing
    # else to check. "personal trainer"/"fitness"-context and combat-sport
    # trainer roles hit the same bare-word problem from the other direction.
    "uxs", "unmanned", "autonomous vehicle", "self-driving", "safety driver",
    "test driver", "kampfsport", "personal trainer", "fitnessstudio",
    "fitness studio",
]

# Company names known to be the wrong domain entirely, found by a title with
# no other word to filter on ("Trainer", alone, at a self-driving car
# company). Title-only matching cannot catch this case any other way - add
# to this list only once a specific company has actually produced a false
# positive, never speculatively.
# Quantum-Systems (military reconnaissance drones) posts under both "UXS
# Training & Demo Manager" (caught by the "uxs" NEGATIVE term) and a plain
# "Training Manager" with no giveaway word at all - same as Wayve, the
# company itself is the signal, not any one title.
NEGATIVE_COMPANIES = ["wayve", "quantum-systems"]

# Location is free text and wildly inconsistent, so classify rather than filter.
# The order these are tested in matters: "Remote - US" and "Remote: India" both
# contain "remote", so testing the allow list first passed every one of them.
# Bare "vienna" was here until it live-tagged two ServiceNow "U.S. Federal"
# postings as "dach" - they were Vienna, VA and Vienna, IL. "vienna, austria"
# still catches the real one; "wien" and "austria" alone already cover most
# genuine Austria postings that omit the city.
# "germany", not "german": the bare stem tagged Germantown, Maryland as DACH.
# German cities beyond the largest are listed because the Bundesagentur board
# often gives only the town, and "Mainz" or "Bremen" came back "unclear".
LOC_DACH = ["germany", "deutschland", "munich", "münchen", "muenchen", "berlin",
            "hamburg", "cologne", "köln", "frankfurt", "stuttgart", "bavaria",
            "bayern", "dach", "austria", "österreich", "vienna, austria",
            "wien", "switzerland", "schweiz", "zurich", "zürich", "düsseldorf",
            "dusseldorf", "leipzig", "dresden", "nuremberg", "nürnberg",
            "mainz", "bremen", "hannover", "hanover", "essen", "dortmund", "bonn",
            "mannheim", "karlsruhe", "augsburg", "regensburg", "ingolstadt",
            "würzburg", "freiburg", "heidelberg", "darmstadt", "wiesbaden",
            "münster", "kiel", "lübeck", "rostock", "potsdam", "erfurt", "jena",
            "magdeburg", "braunschweig", "bielefeld", "aachen", "duisburg",
            "bochum", "wuppertal", "saarbrücken", "ulm", "fürstenfeldbruck",
            "germering", "starnberg", "dachau", "freising", "erding", "garching",
            "unterschleißheim", "ismaning", "planegg", "martinsried", "gräfelfing",
            "puchheim", "grafrath"]

# Wide enough to include Germany, so a role scoped this way is reachable.
LOC_WIDE = ["emea", "europe", "european", "eu remote", "remote eu"]
# Wide only when nothing narrower is named: "Remote US or Canada; global team"
# describes the company, not where the role may sit, while a bare "Global" or
# "Worldwide" is genuinely open.
LOC_WIDE_WEAK = ["anywhere", "worldwide", "global", "globally"]
# A DACH country named outright, which a US-style ", ST" suffix cannot outrank.
LOC_DACH_COUNTRY = ["germany", "deutschland", "austria", "österreich", "switzerland",
                    "schweiz", "dach"]

# Somewhere he cannot be, since Munich is fixed. Non-DACH Europe is in here
# too: an on-site role in Sofia is no more available to him than one in Pune.
LOC_ELSEWHERE = [
    "united states", "usa", "canada", "toronto", "ontario", "vancouver",
    "india", "bangalore", "bengaluru", "pune", "maharashtra", "hyderabad",
    "mumbai", "delhi", "chennai", "gurgaon", "noida", "singapore", "australia",
    "sydney", "melbourne", "japan", "tokyo", "korea", "china", "shanghai",
    "beijing", "hong kong", "taiwan", "philippines", "manila", "vietnam",
    "indonesia", "thailand", "malaysia", "brazil", "mexico", "argentina",
    "colombia", "chile", "peru", "costa rica", "guadalajara", "israel",
    "united arab", "dubai", "egypt", "south africa", "cape town", "kenya",
    "nigeria", "turkey", "istanbul", "poland", "warsaw", "krakow", "romania",
    "bucharest", "bulgaria", "sofia", "czech", "prague", "hungary", "budapest",
    "ukraine", "serbia", "belgrade", "croatia", "greece", "athens",
    "spain", "madrid", "barcelona", "portugal", "lisbon", "porto", "france",
    "paris", "italy", "milan", "rome", "netherlands", "amsterdam", "utrecht",
    "belgium", "brussels", "ghent", "sweden", "stockholm", "denmark",
    "copenhagen", "norway", "oslo", "finland", "helsinki", "estonia", "latvia",
    "lithuania", "ireland", "dublin", "united kingdom", "england", "scotland",
    "wales", "northern ireland", "london", "manchester",
    "bristol", "edinburgh", "new york", "san francisco", "austin", "boston",
    "chicago", "seattle", "denver", "atlanta", "california", "texas",
    # Named cities, because a posting often gives the city and not the state.
    # "Santa Clara" reached the shortlist while "california" sat in this list.
    "santa clara", "san jose", "palo alto", "mountain view", "sunnyvale",
    "san diego", "los angeles", "portland", "phoenix", "dallas", "houston",
    "miami", "raleigh", "nashville", "salt lake", "pittsburgh", "detroit",
    "minneapolis", "philadelphia", "washington dc", "arlington", "waterloo",
    "ottawa", "montreal",
]

# Short forms need a word boundary; "us" as a substring matches "customer".
LOC_ELSEWHERE_RE = re.compile(r"\b(u\.?s\.?a?|uk|uae|apac|latam|na|namer|nam)\b")

# "Town, ST" with a US state code, which is how most US boards give a location
# ("Germantown, MD"). Delaware's DE is left out: ", DE" is also Germany's
# country code, and a German town with no other marker must not be rejected.
US_STATE_RE = re.compile(
    r",\s*(al|ak|az|ar|ca|co|ct|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|"
    r"mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|"
    r"wy|dc)\b")

LOC_REMOTE = ["remote", "home office", "hybrid", "flexible", "distributed"]


# German trade words are matched at the start of a word only, because German
# builds compounds: "Lagerist" and "Produktionshelfer" are the trades, while
# "Kundenpflege" (customer care) and "Videoproduktion" are exactly his work
# and were being thrown away. Everything else matches as a whole word: as a
# substring, "intern" rejected every "International ..." and "Internal ..."
# title, including an International Customer Success Manager.
NEGATIVE_STEMS = {
    "pflege", "lager", "produktion", "reinigung", "küche", "bäcker", "metzger",
    "friseur", "kosmetik", "sonnenstudio", "haushaltshilfe", "zerspanung",
    "elektriker", "monteur", "schlosser", "maler", "gabelstapler", "elektroniker",
    "mechatroniker", "industriemechaniker", "montage", "fertigung", "prüffeld",
    "optoelektronik", "hardwareentwickler", "solarium", "werkstudent", "praktikum",
    "kampfsport", "fitnessstudio", "fahrer", "technischer zeichner",
    "vermessungstechnik",
}


def _negative_pattern(term):
    t = re.escape(term)
    if term in NEGATIVE_STEMS:
        return r"(?<![a-zäöüß])%s" % t
    return r"(?<![a-z0-9])%ss?(?![a-z0-9])" % t


NEGATIVE_RE = re.compile("|".join(_negative_pattern(n) for n in NEGATIVE), re.I)


def relevant(title, terms, company=""):
    low = title.lower()
    if NEGATIVE_RE.search(low):
        return []
    if any(n in (company or "").lower() for n in NEGATIVE_COMPANIES):
        return []
    return [t for t in terms if t in low]


def classify_location(loc):
    """allow, unclear or reject.

    Tested in this order on purpose. A DACH city wins outright. A role scoped
    to all of Europe or EMEA includes Germany, so it is allowed unless it also
    names somewhere he cannot be. Anything naming only a place he cannot be is
    rejected even when the word "remote" is in the string, which is where this
    used to let through a whole page of US and India roles. Bare "remote" with
    no place attached is allowed, and an empty location stays unclear, because
    a missing location is more often remote than disqualifying.
    """
    low = (loc or "").lower()
    if not low.strip():
        return "unclear"
    # A US state code outranks a German city name: Hanover NH, Potsdam NY,
    # Berlin NH, Frankfurt KY and a dozen more are real US towns, and testing
    # the DACH list first passed every one of them (the fix for Vienna, VA
    # covered only Vienna). A named DACH country still wins.
    if US_STATE_RE.search(low) and not any(k in low for k in LOC_DACH_COUNTRY):
        return "reject"
    if any(k in low for k in LOC_DACH):
        return "dach"
    # A role scoped to Europe, EMEA or the whole world includes Germany even
    # when it also names somewhere he cannot be, so "Remote - US or Europe" is
    # reachable. Testing this before the reject list is the whole point: the
    # other order discarded every posting that offered both, which is most of
    # the remote roles worth having.
    if any(k in low for k in LOC_WIDE):
        return "europe"
    if (any(k in low for k in LOC_ELSEWHERE)
            or bool(LOC_ELSEWHERE_RE.search(low)) or bool(US_STATE_RE.search(low))):
        return "reject"
    if any(k in low for k in LOC_WIDE_WEAK):
        return "europe"
    if any(k in low for k in LOC_REMOTE):
        return "remote"
    return "unclear"


def load_seen():
    ids = set()
    if SEEN.exists():
        for line in SEEN.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    row = json.loads(line)
                    ids.add(row.get("fingerprint") or row.get("id") or "")
                except ValueError:
                    continue
    return ids


def fingerprint(job):
    key = "%s::%s" % (job["company"], job["title"])
    return re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")


LEGAL_SUFFIX = re.compile(r"\b(gmbh|ag|se|kg|inc|ltd|llc|plc|bv|nv|corp|co)\b")
UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                        "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def slug_candidates(name):
    """The slugs an ATS might plausibly use for a company typed by a human.

    Umlauts are the sharp edge here. Stripping non-ASCII turns "TUV SUD" into
    "tvsd" and nothing answers, so the German transliteration is tried too,
    as is the name with its legal suffix removed.
    """
    low = name.lower().strip()
    variants = [
        low.translate(UMLAUT),
        unicodedata.normalize("NFKD", low).encode("ascii", "ignore").decode(),
        low,
    ]
    out = []
    for base in dict.fromkeys(variants):
        for stripped in dict.fromkeys([base, LEGAL_SUFFIX.sub(" ", base)]):
            out.append(re.sub(r"[^a-z0-9]+", "", stripped))
            out.append(re.sub(r"[^a-z0-9]+", "-", stripped).strip("-"))
    return [s for s in dict.fromkeys(out) if len(s) > 1]


PLACEHOLDER = re.compile(r"^(test|demo|sample|example|api|job)\b[\s\d:-]*", re.I)


def looks_like_demo(rows):
    """An ATS tenant someone created and never used.

    These answer with a couple of postings called "test" or "Job 1", which is
    indistinguishable from a real board by status code alone. The premise of
    sources.json is that every entry answered with real work, so this extends
    "zero roles means no board" to cover a board holding nothing real.
    """
    if not rows or len(rows) > 3:
        return False
    return all(PLACEHOLDER.match(r["title"].strip()) for r in rows)


def probe(ats, slug, name):
    """Ask one ATS about one slug. Returns the roles it lists, or None."""
    if ats not in ATS or ats == "arbeitnow":
        return None
    try:
        data = fetch(ATS[ats].format(slug=slug))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
        return None
    rows = norm(ats, data, name)
    if not rows or looks_like_demo(rows):
        return None
    return rows


def discover(name):
    found = []
    for ats in ATS:
        if ats == "arbeitnow":
            continue
        for s in slug_candidates(name):
            rows = probe(ats, s, name)
            if rows is None:
                continue
            found.append({"ats": ats, "slug": s, "roles": len(rows),
                          "sample": [r["title"] for r in rows[:3]]})
            break
    return found


def add_source(name, ats, slug, note="", force=False):
    """Write a verified source into profile/sources.json.

    Verifies before writing, because the whole point of sources.json is that
    every entry in it was known to answer at least once. A zero-role reply is
    usually an ATS being polite about a company it has never heard of.
    """
    if ats not in ATS:
        return {"ok": False, "err": "unknown ats %r; known: %s"
                                    % (ats, ", ".join(sorted(ATS)))}
    roles = None
    if ats != "arbeitnow":
        roles = probe(ats, slug, name)
        if roles is None and not force:
            return {"ok": False, "err": "%s/%s listed no roles, so it was not added"
                                        % (ats, slug)}

    cfg = json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.exists() else {}
    cfg.setdefault("sources", [])
    for src in cfg["sources"]:
        if src.get("ats") == ats and src.get("slug", "") == slug:
            return {"ok": False, "err": "already configured: %s (%s/%s)"
                                        % (src.get("company"), ats, slug)}

    entry = {"company": name, "ats": ats, "slug": slug, "enabled": True,
             "note": note or ("%d roles at discovery." % len(roles) if roles else
                              "Added without a role count.")}
    cfg["sources"].append(entry)

    # It answered, so it no longer belongs on the list of companies that did not.
    nf = cfg.get("_not_found") or {}
    misses = nf.get("companies") or []
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    kept = [c for c in misses if re.sub(r"[^a-z0-9]+", "", c.lower()) != key]
    if len(kept) != len(misses):
        nf["companies"] = kept
        cfg["_not_found"] = nf

    tmp = SOURCES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(SOURCES)
    return {"ok": True, "added": entry, "roles": len(roles) if roles else 0}


def record_miss(name):
    """Remember a company that answered nothing, so it is not re-guessed blind."""
    cfg = json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.exists() else {}
    nf = cfg.get("_not_found") or {}
    misses = nf.get("companies") or []
    key = re.sub(r"[^a-z0-9]+", "", name.lower())
    if any(re.sub(r"[^a-z0-9]+", "", c.lower()) == key for c in misses):
        return False
    nf["companies"] = sorted(misses + [name])
    cfg["_not_found"] = nf
    tmp = SOURCES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(SOURCES)
    return True


def run(only_new=True, anywhere=False):
    cfg = json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.exists() else {"sources": []}
    terms = load_terms()
    seen = load_seen() if only_new else set()
    hits, errors, checked = [], [], 0

    for src in cfg.get("sources", []):
        if not src.get("enabled", True):
            continue
        ats, slug = src.get("ats"), src.get("slug", "")
        if ats not in ATS:
            errors.append({"company": src.get("company"), "err": "unknown ats %r" % ats})
            continue

        # A source may carry its own term list. The default list is written for
        # knowledge work and would throw away every local job on the
        # Bundesagentur board, which is the one place local work is listed.
        src_terms = [t.lower() for t in src.get("terms") or []] or terms
        preset = None

        if ats == "arbeitsagentur":
            params = dict(src.get("params") or {})
            # A source scoped to a radius ("wo") is the local-commute search,
            # and the postal code and radius that actually matter live in his
            # availability, editable from Settings, not in this file. Without
            # this, changing the radius in Settings had no effect at all:
            # sources.json's own stored value is what a discovery happened to
            # write down once, and nothing ever read it back out again.
            if "wo" in params:
                # load_json_safe() returns {} for both "file missing" (fine,
                # nothing to override) and "file exists but is malformed
                # JSON" - the second case would otherwise silently fall back
                # to sources.json's own stale stored wo/umkreis, exactly the
                # bug the comment above says this whole block exists to fix.
                # Told apart by parsing directly here rather than trusting
                # load_json_safe's ambiguous {}, since a genuinely empty but
                # validly-parsed file must not raise a false alarm.
                if AVAILABILITY.exists():
                    try:
                        json.loads(AVAILABILITY.read_text(encoding="utf-8"))
                    except ValueError:
                        errors.append({"company": src.get("company"),
                                       "err": "profile/availability.json exists but did "
                                              "not parse - using this source's stale "
                                              "stored wo/umkreis instead of Settings' "
                                              "current radius"})
                loc = (load_json_safe(AVAILABILITY).get("location") or {})
                if loc.get("home_plz"):
                    params["wo"] = str(loc["home_plz"])
                if loc.get("radius_km"):
                    params["umkreis"] = str(loc["radius_km"])
            jobs = ba_search(params, int(src.get("pages", 3)))
            if not jobs:
                errors.append({"company": src.get("company"), "err": "no results"})
                continue
            # The radius was enforced by the query, so these need no guessing.
            if params.get("wo"):
                preset = "local"
            elif "ho" in str(params.get("arbeitszeit", "")):
                preset = "remote"
        else:
            url = ATS[ats].format(slug=slug)
            try:
                data = fetch(url)
            except urllib.error.HTTPError as exc:
                errors.append({"company": src.get("company"), "err": "HTTP %s" % exc.code})
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append({"company": src.get("company"), "err": type(exc).__name__})
                continue
            jobs = norm(ats, data, src.get("company", slug))

        checked += 1
        for job in jobs:
            matched = relevant(job["title"], src_terms, job.get("company"))
            if not matched:
                continue
            where = preset or classify_location(job["location"])
            if where == "reject" and not anywhere:
                continue
            fp = fingerprint(job)
            if fp in seen:
                continue
            seen.add(fp)
            job["fingerprint"] = fp
            job["matched"] = matched[:4]
            job["source"] = ats
            job["location_class"] = where
            hits.append(job)

    if hits and only_new:
        SEEN.parent.mkdir(parents=True, exist_ok=True)
        with SEEN.open("a", encoding="utf-8") as f:
            for h in hits:
                f.write(json.dumps(h, ensure_ascii=False) + "\n")

    return {"checked": checked, "new": hits, "errors": errors}


def main():
    # Job titles are full of umlauts and en dashes. Without this, redirecting
    # this script's output on Windows encodes them in the ANSI codepage and
    # whatever reads the file back as UTF-8 gets mojibake.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--discover", metavar="COMPANY")
    ap.add_argument("--add", metavar="COMPANY",
                    help="write a verified company into profile/sources.json")
    ap.add_argument("--ats", help="with --add: which applicant tracking system")
    ap.add_argument("--slug", help="with --add: the company's slug on that ATS")
    ap.add_argument("--note", default="", help="with --add: why it is worth polling")
    ap.add_argument("--force", action="store_true",
                    help="with --add: write it even if it lists no roles today")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--all", action="store_true", help="ignore the seen history")
    ap.add_argument("--anywhere", action="store_true",
                    help="include roles outside Germany, DACH and remote")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    if args.add:
        if not args.ats or not args.slug:
            ap.error("--add needs --ats and --slug (run --discover first)")
        res = add_source(args.add, args.ats, args.slug.strip(), args.note, args.force)
        if args.as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif res["ok"]:
            print("  added %s (%s/%s), %d roles listed now."
                  % (args.add, args.ats, args.slug, res["roles"]))
        else:
            print("  not added: %s" % res["err"])
        return 0 if res["ok"] else 1

    if args.discover:
        found = discover(args.discover)
        if args.as_json:
            print(json.dumps(found, indent=2, ensure_ascii=False))
        elif found:
            for f in found:
                print("  %-16s slug=%-22s %d roles   %s"
                      % (f["ats"], f["slug"], f["roles"], "; ".join(f["sample"])[:70]))
            best = found[0]
            print("\nTo keep it:\n  py tools/watch_ats.py --add %r --ats %s --slug %s"
                  % (args.discover, best["ats"], best["slug"]))
        else:
            print("  no public ATS endpoint found by slug guessing.")
            print("  Open the careers page and look at the URL it posts to.")
            record_miss(args.discover)
        return 0

    if not args.run:
        ap.error("use --run or --discover")

    res = run(only_new=not args.all, anywhere=args.anywhere)
    if args.as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print("checked %d sources, %d new matching role(s)\n" % (res["checked"], len(res["new"])))
    for h in res["new"]:
        print("  %-26s %s" % (h["company"][:26], h["title"]))
        print("  %-26s %s  (%s)  [%s]" % ("", h["location"] or "location not given",
                                        h.get("location_class", "?"),
                                        ", ".join(h["matched"])))
        if h["url"]:
            print("  %-26s %s" % ("", h["url"]))
        print()
    for e in res["errors"]:
        print("  error  %-24s %s" % ((e.get("company") or "?")[:24], e["err"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
