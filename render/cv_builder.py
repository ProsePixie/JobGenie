#!/usr/bin/env python3
"""Build a CV from a base and thread dials.

The design is in plans/cv-builder.md. In short: a spec names a base
(professional or service), a language, one lead thread and a dial for every
thread (lead, strong, light, off), plus any per-bullet overrides, a headline,
an accepted summary and the optional Service photo. This turns that spec into
the same outputs render.py produces (html, pdf, paste-ready txt, fields.json),
following the CV practice the user asked for:

  - every job is listed; recent jobs carry the detail, old ones one line
  - bullets come from the dialed-up threads, starred stories first
  - a Light thread contributes at most one bullet
  - the newest builds get entries, the earlier builds one compact line
  - page fitting trims by value, oldest and least relevant first, and never
    removes a bullet the user ticked by hand

Standard library only.

    spec = default_spec("professional", lead="enablement", dials={"ai": "strong"})
    result = build(spec, out_dir, "Jane_Doe_CV")
"""

import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "profile"
TEMPLATES = Path(__file__).resolve().parent / "templates"
PHOTO_CANDIDATES = [ROOT / "documents" / n for n in ("photo.jpg", "photo.jpeg", "photo.png")]

LEVEL = {"lead": 3, "strong": 2, "light": 1, "off": 0}

# Bullets per job by how long ago it ended, for each base. (years, cap) pairs,
# tested in order; anything older than the last bound is a one-line entry. A
# job whose bullets carry the lead thread keeps one bullet even when old, so a
# Service CV can still show the school IT work that is its real evidence.
RECENCY_CAPS = {
    "professional": [(5, 5), (10, 3), (12, 2)],
    "service": [(5, 3), (10, 2), (12, 1)],
}

SECTION_LABELS = {
    "en": dict(R.LABELS["en"], summary="Profile",
               earlier_builds="Earlier AI-assisted builds"),
    "de": dict(R.LABELS["de"], summary="Kurzprofil",
               earlier_builds="Frühere KI-gestützte Projekte"),
}


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def load_context():
    career = R.load("career.json")
    threads_doc = json.loads((PROFILE / "threads.json").read_text(encoding="utf-8"))
    return {"career": career, "threads": threads_doc,
            "by_id": {t["id"]: t for t in threads_doc["threads"]}}


def default_spec(base="professional", lang=None, lead=None, dials=None, ctx=None):
    """A complete spec from partial input: every thread gets a dial."""
    ctx = ctx or load_context()
    base_def = ctx["threads"]["bases"][base]
    dials = dict(dials or {})
    for t in ctx["threads"]["threads"]:
        dials.setdefault(t["id"], "off")
    if lead:
        for k, v in dials.items():
            if v == "lead" and k != lead:
                dials[k] = "strong"
        dials[lead] = "lead"
    return {"base": base, "lang": lang or base_def["lang"], "dials": dials,
            "bullets": {}, "headline": "", "summary": "", "summary_accepted": False,
            "photo": False, "sections": {}, "advanced": {},
            # The role's one-line description under its title (career.json
            # `context`). A spec saved before it existed has no value and gets none.
            "context_lines": True}


def validate(spec, ctx):
    """Problems that make a spec unusable, as plain sentences. Empty when fine."""
    problems = []
    if spec.get("base") not in ctx["threads"]["bases"]:
        problems.append("unknown base %r" % spec.get("base"))
    dials = spec.get("dials") or {}
    unknown = [k for k in dials if k not in ctx["by_id"]]
    if unknown:
        problems.append("unknown thread(s): %s" % ", ".join(unknown))
    bad = [k for k, v in dials.items() if v not in LEVEL]
    if bad:
        problems.append("bad dial level on: %s" % ", ".join(bad))
    leads = [k for k, v in dials.items() if v == "lead"]
    if len(leads) != 1:
        problems.append("exactly one thread must be Lead (found %d)" % len(leads))
    strong = [k for k, v in dials.items() if v == "strong"]
    if len(strong) > ctx["threads"].get("max_strong", 2):
        problems.append("at most %d threads can be Strong (found %d). Turning everything "
                        "up is what makes a CV read as unfocused."
                        % (ctx["threads"].get("max_strong", 2), len(strong)))
    return problems


def lead_of(spec):
    return next((k for k, v in spec["dials"].items() if v == "lead"), None)


def level_of(threads, spec):
    return max([LEVEL[spec["dials"].get(t, "off")] for t in threads or []] or [0])


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def years_ago(role, today=None):
    end = R.end_year(role)
    year = (today or datetime.date.today()).year
    return 0 if end >= year else year - end


def recency_cap(role, base):
    age = years_ago(role)
    for bound, cap in RECENCY_CAPS.get(base, RECENCY_CAPS["professional"]):
        if age <= bound:
            return cap
    return 0


AGE_PENALTY = {"professional": 0.4, "service": 0.15}

# Posting relevance. The dials pick which threads argue; within a thread, the
# bullets that speak to this posting's own words should win. Without it every
# Customer Success posting got the same five bullets from one employer, led by the two
# animation series, whatever the posting asked for.
WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß+#-]{4,}")
RELEVANCE_CAP = 8

# Function words and posting boilerplate, both languages. They survive the
# frequency filter because a bullet list rarely uses them, not because they
# mean anything.
POSTING_STOP = set("""
einem einer eines einen deren dessen denen ander andere anderen anderer weiter weitere
stand stets stetig richtig stelle stellen sowie sowohl damit dafür dabei durch unter
unsere unserer unseren deine deiner deinen deinem ihrer ihren ihnen euch wirst werden
wurde wären würde könnte sollte möchtest möchten jahre jahren praktische ersten letzte
bereits immer gerne haben hast sind bist kannst mehrere vielzahl zudem außerdem bitte
their there these those which while where would could should about above after again
other others within without through across every years including ideally great
position candidate candidates apply application please looking offer offers
build builds building create creating drive driving using during entire clear count
share state direct person personal working different multiple roles teams ensure
strong ability excellent effective effectively manage managing support supporting
provide providing include includes develop related level based across world
""".split())


def _stem(word):
    w = word.lower().strip("-")
    return w[:max(5, len(w) - 3)] if len(w) > 6 else w


def posting_terms(posting, ctx):
    """Stems of the posting's distinctive words: those that also occur in the
    career data (anything else cannot raise a bullet), minus words found in so
    many bullets that they say nothing ("training", "Schulung")."""
    if not (posting or "").strip():
        return frozenset()
    bullets = [(b.get("text", "") + " " + (b.get("text_de") or "")).lower()
               for r in ctx["career"].get("roles", []) for b in r.get("bullets", [])]
    if not bullets:
        return frozenset()
    terms = set()
    for w in WORD.findall(posting):
        if w.lower() in POSTING_STOP:
            continue
        st = _stem(w)
        if len(st) < 5 or st in {_stem(x) for x in ("einem", "einer", "eines", "weiter", "stellen")}:
            continue
        df = sum(1 for t in bullets if st in t)
        if 0 < df <= max(3, len(bullets) // 6):
            terms.add(st)
    return frozenset(terms)


def relevance(b, terms):
    """How many of the posting's distinctive terms a bullet contains."""
    if not terms:
        return 0
    text = (b.get("text", "") + " " + (b.get("text_de") or "")).lower()
    return sum(1 for t in terms if t in text)


def bullet_value(b, role, spec, prefer=(), terms=frozenset()):
    """Higher is more worth keeping. Used for ordering and for trimming.

    The dial dominates (10 per level), then strength, stars and relevance to
    the posting (2 per distinctive posting term, at most 8), then recency.
    A small penalty for position keeps the order they wrote a job's bullets in
    when the scores are close: the first bullet is usually the summary line.
    """
    level = level_of(b.get("threads"), spec)
    tags = {t.lower() for t in b.get("tags") or []}
    value = level * 10 + int(b.get("strength", 2)) * 2
    if b.get("star"):
        value += 15
    if tags & {p.lower() for p in prefer}:
        value += 3
    value += min(RELEVANCE_CAP, 2 * relevance(b, terms))
    value -= min(years_ago(role), 25) * AGE_PENALTY.get(spec.get("base"), 0.4)
    bullets = role.get("bullets", [])
    if b in bullets:
        value -= bullets.index(b) * 0.3
    return value


def plan(spec, ctx, trimmed=frozenset(), caps_override=None, prefer=()):
    """Decide what goes on the page. Pure data; no HTML.

    `trimmed` holds bullet ids removed by page fitting; `caps_override` holds
    section caps fitting lowered (certs, projects).
    """
    career, base = ctx["career"], spec["base"]
    base_def = ctx["threads"]["bases"][base]
    lead = lead_of(spec)
    overrides = spec.get("bullets") or {}
    caps = dict(caps_override or {})
    light_used = set()
    terms = ctx.get("posting_terms") or frozenset()
    untranslated = []

    def choose(role):
        pool = []
        for b in role.get("bullets", []):
            if R.is_todo(b.get("text")) or b["id"] in trimmed:
                continue
            forced = overrides.get(b["id"])
            if forced is False:
                continue
            # A story for the interview, not a line for the page: how a
            # project was built ("reset an over-built feature") is worth
            # telling and dull to read. Ticking it by hand still shows it.
            if b.get("interview_only") and forced is not True:
                continue
            # A German CV does not carry English lines. A bullet with no German
            # text is left out and listed, so the panel can offer a translation;
            # ticking it by hand still shows it (in English, flagged).
            if (spec.get("lang") == "de" and not (b.get("text_de") or "").strip()
                    and forced is not True):
                if level_of(b.get("threads"), spec) >= LEVEL["light"]:
                    untranslated.append(b["id"])
                continue
            level = level_of(b.get("threads"), spec)
            if forced is True or level >= LEVEL["strong"]:
                pool.append((b, forced is True))
            elif level == LEVEL["light"]:
                pool.append((b, False))
        pool.sort(key=lambda x: (not x[1], -bullet_value(x[0], role, spec, prefer, terms)))
        # A role may set its own cap (`bullet_cap`): an old job can be the main
        # evidence for one base (retail, say) and would otherwise get one bullet by age.
        cap = role.get("bullet_cap") or recency_cap(role, caps.get("recency", base))
        if cap == 0 and any(lead in (b.get("threads") or []) for b, _ in pool):
            cap = 1
        chosen, facts = [], set()
        for b, forced in pool:
            level = level_of(b.get("threads"), spec)
            # `variant_of` marks a plain-language rewording of another bullet
            # (a plain-language Service version of a line). The same fact never
            # appears twice: whichever version ranks higher takes it.
            fact = b.get("variant_of") or b["id"]
            if fact in facts and not forced:
                continue
            facts.add(fact)
            if forced:
                chosen.append(b)
                continue
            if len(chosen) >= cap:
                continue
            if level == LEVEL["light"]:
                light = [t for t in b.get("threads") or []
                         if spec["dials"].get(t) == "light"]
                if all(t in light_used for t in light):
                    continue
                light_used.update(light)
            chosen.append(b)
        # Chosen by value, shown starred first and then in the order they wrote
        # them: a job's first bullet usually says what the thing is, and value
        # order opened a project entry with a detail instead.
        order = {id(x): i for i, x in enumerate(role.get("bullets", []))}
        chosen.sort(key=lambda x: (not x.get("star"), order.get(id(x), 99)))
        return chosen

    roles = sorted(career.get("roles", []), key=R.sort_key, reverse=True)
    # A role that belongs to one base only (a retail job is for the Service CV and
    # would be a one-line row on a Professional one) is left off the other base.
    jobs = [{"role": role, "bullets": choose(role)} for role in roles
            if not (role.get("only_base") and role["only_base"] != base)]
    proj_entries = sorted(career.get("projects", []), key=R.sort_key, reverse=True)
    projects, earlier = [], []
    for proj in proj_entries:
        (earlier if proj.get("project_tier") == "earlier" else projects).append(proj)

    project_cap = caps.get("projects", base_def.get("max_projects", 0))
    shown_projects = []
    # A project they ticked by hand appears even where the base hides projects
    # (Service): ticking a bullet and seeing nothing change was confusing.
    forced_projects = [r for r in projects
                       if any(overrides.get(b.get("id")) is True for b in r.get("bullets", []))]
    if not project_cap and forced_projects:
        shown_projects = [{"role": r, "bullets": choose(r)} for r in forced_projects]
    if project_cap and "projects" in sections_for(spec, base_def):
        ranked = []
        for role in projects:
            # The pitch line says what the project is; the bullets only have
            # to say why it is impressive. Two when it carries the Lead, else one.
            bullets = choose(role)[:2 if level_of(
                [t for b in role.get("bullets", []) for t in b.get("threads") or []],
                spec) >= LEVEL["lead"] else 1]
            if bullets:
                best = max(level_of(b.get("threads"), spec) for b in bullets)
                strength = max(int(b.get("strength", 2)) for b in bullets
                               if level_of(b.get("threads"), spec) == best)
                ranked.append((best, strength, role.get("start") or "", role, bullets))
        # Most relevant first, then the stronger proof, then the newer. Date
        # alone as the tie-break put a game companion app above the framework
        # they taught live in an enablement casting, on an enablement CV.
        ranked.sort(key=lambda x: x[2], reverse=True)
        ranked.sort(key=lambda x: (-x[0], -x[1]))
        shown_projects = [{"role": r, "bullets": bl} for _, _, _, r, bl in ranked[:project_cap]]

    earlier_line = None
    if earlier and spec["dials"].get("ai", "off") != "off" and project_cap:
        names = [r.get("name") for r in sorted(earlier, key=R.sort_key)]
        years = sorted({(r.get("start") or "")[:4] for r in earlier if r.get("start")})
        earlier_line = {"names": names, "years": years}

    # A skill group or certification ticked by hand (spec["skills"], spec["certs"],
    # as the Build panel's Add button writes them) is shown whatever its threads
    # say and whatever the cap, exactly as a ticked bullet is.
    pin_skills = {k for k, v in (spec.get("skills") or {}).items() if v is True}
    pin_certs = {k for k, v in (spec.get("certs") or {}).items() if v is True}
    skills = []
    for key, cluster in (career.get("skills") or {}).items():
        level = level_of(cluster.get("threads"), spec)
        if level >= LEVEL["light"]:
            skills.append((level, key, cluster))
    skills.sort(key=lambda x: -x[0])
    strong = [x for x in skills if x[0] >= LEVEL["strong"]][:4]
    light = [x for x in skills if x[0] == LEVEL["light"]][:1]
    skills = strong + light
    have = {x[1] for x in skills}
    for key in (career.get("skills") or {}):
        if key in pin_skills and key not in have:
            skills.append((LEVEL["strong"], key, career["skills"][key]))

    cert_cap = caps.get("certifications", base_def.get("max_certs", 4))
    certs = []
    for c in career.get("certifications", []):
        level = level_of(c.get("threads"), spec)
        if level >= (LEVEL["strong"] if base == "service" else LEVEL["light"]):
            certs.append((level, c))
    certs.sort(key=lambda x: (x[1].get("year") or ""), reverse=True)
    certs.sort(key=lambda x: (-x[0], -int(x[1].get("strength", 2))))
    certs = [c for _, c in certs[:cert_cap]]
    have = {c.get("id") for c in certs}
    certs += [c for c in career.get("certifications", [])
              if c.get("id") in pin_certs and c.get("id") not in have]

    lead_in_jobs = sum(1 for j in jobs for b in j["bullets"]
                       if lead in (b.get("threads") or []))
    lead_in_projects = sum(1 for x in shown_projects for b in x["bullets"]
                           if lead in (b.get("threads") or []))
    return {"jobs": jobs, "projects": shown_projects, "earlier": earlier_line,
            "skills": skills, "certs": certs, "lead": lead,
            "projects_first": lead_in_projects > lead_in_jobs,
            "untranslated": list(dict.fromkeys(untranslated))}


def sections_for(spec, base_def, projects_first=False, has_projects=False):
    order = list(base_def["sections"])
    if has_projects and "projects" not in order and "roles" in order:
        order.insert(order.index("roles") + 1, "projects")
    if projects_first and "projects" in order and "roles" in order:
        order.remove("projects")
        order.insert(order.index("roles"), "projects")
    for name, on in (spec.get("sections") or {}).items():
        if on is False and name in order:
            order.remove(name)
        elif on is True and name not in order:
            order.append(name)
    return order


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def thread_links(ident, spec, ctx, omissions):
    """Links tied (`threads`) to a thread dialed Strong or Lead, plus any link
    not tied to a thread. The Spotify page follows Media, GitHub follows AI."""
    out = []
    for key, val in (ident.get("links") or {}).items():
        if isinstance(val, dict):
            tied = val.get("threads") or []
            if tied and not any(LEVEL[spec["dials"].get(t, "off")] >= LEVEL["strong"]
                                for t in tied):
                continue
            url = val.get("url")
        else:
            url = val
        clean = R.take(url, "identity.links.%s" % key, key, omissions)
        if clean:
            out.append((key, clean))
    return out


def headline_text(spec, ctx):
    if (spec.get("headline") or "").strip():
        return spec["headline"].strip()
    t = ctx["by_id"].get(lead_of(spec)) or {}
    return t.get("headline_de" if spec["lang"] == "de" else "headline") or ""


def photo_path(spec, ctx):
    base_def = ctx["threads"]["bases"][spec["base"]]
    if not (base_def.get("photo_allowed") and spec.get("photo")):
        return None
    return next((p for p in PHOTO_CANDIDATES if p.exists()), None)


def header_html(spec, ctx, omissions):
    ident = ctx["career"].get("identity", {})
    name = R.take(ident.get("name"), "identity.name", "name", omissions) or ""
    lang = spec["lang"]
    bits = []
    for key in ("email", "phone"):
        val = R.take(ident.get(key), "identity.%s" % key, key, omissions)
        if val:
            bits.append(R.e(val))
    city = ident.get("city")
    loc = city if not R.is_todo(city) else ident.get("location")
    if loc and not R.is_todo(loc):
        bits.append(R.e(R.places_de(loc) if lang == "de" else loc))
    for _key, url in thread_links(ident, spec, ctx, omissions):
        bits.append('<a href="%s">%s</a>' % (R.e(url), R.e(R.display_url(url))))
    out = []
    photo = photo_path(spec, ctx)
    if photo:
        out.append('<img class="photo" src="%s" alt="">' % R.e(photo.resolve().as_uri()))
    out.append('<h1>%s</h1>' % R.e(name))
    head = headline_text(spec, ctx)
    if head:
        out.append('<p class="headline">%s</p>' % R.e(head))
    if bits:
        out.append('<p class="contact">%s</p>' % '<span class="sep">|</span>'.join(bits))
    out.append('<hr class="rule">')
    return "\n".join(out)


def project_html(role, bullets, lang, omissions):
    """A project as one line saying what it is, then the proof.

    A project entry is never laid out like a job: there is no employer and a
    location is not the point. With a `pitch` in the CV's language it reads
    "Name - pitch"; without one (or with a TODO pitch) it is just the name.
    """
    de = lang == "de"
    pitch = (role.get("pitch_de") if de else role.get("pitch")) or ""
    name = (de and role.get("name_de")) or role.get("name") or ""
    if pitch.strip() and not R.is_todo(pitch):
        title = '%s<span class="entry-org"> - %s</span>' % (R.e(name), R.e(pitch.strip()))
    else:
        title = R.e(name)
    out = ['<div class="entry project">', '  <div class="entry-head">',
           '    <p class="entry-title">%s</p>' % title,
           '    <p class="entry-meta">%s</p>' % R.date_range(role, lang), '  </div>']
    if bullets:
        out.append('  <ul>')
        for b in bullets:
            out.append('    <li data-bullet="%s">%s</li>'
                       % (R.e(b["id"]), R.keep_compounds(R.e(R.bullet_text(b, lang, omissions)))))
        out.append('  </ul>')
    out.append('</div>')
    return "\n".join(out)


def entry_html(role, bullets, lang, omissions, context=False):
    meta_bits = [R.date_range(role, lang)]
    loc = R.location_text(role, lang)
    if loc:
        meta_bits.append(R.e(loc))
    meta = " | ".join(b for b in meta_bits if b)
    # title_de / org_de carry only the parts that are annotation, not the
    # title itself: "(contract)", "(acquired by Globex)", a project's
    # description. Titles held in English stay English.
    de = lang == "de"
    title = '%s<span class="entry-org">, %s</span>' % (
        R.e((de and role.get("title_de")) or role.get("title", "")),
        R.e((de and role.get("org_de")) or role.get("org", "")))
    if not bullets:
        return R.compact_row(title, meta)
    # Title and dates side by side only when both fit on one line. When both
    # wrap, the PDF text layer interleaves the two columns ("...Trainer, PGP
    # Jun 2006 - Mai 2011 | Utah, USA, danach Corporation (...)") and a
    # parser reads the employer name broken; stacked, each stays whole.
    plain = len("%s, %s %s" % (role.get("title", ""), role.get("org", ""), re.sub(r"<[^>]+>", "", meta)))
    stacked = " stacked" if plain > 92 else ""
    out = ['<div class="entry">', '  <div class="entry-head%s">' % stacked,
           '    <p class="entry-title">%s</p>' % title,
           '    <p class="entry-meta">%s</p>' % meta, '  </div>']
    # English only: there is no reviewed German line, and an English sentence
    # on a German CV is the thing the builder otherwise refuses to do.
    line = (role.get("context") or "").strip()
    if context and lang != "de" and line and not R.is_todo(line):
        out.append('  <p class="entry-context">%s</p>' % R.e(line))
    out.append('  <ul>')
    for b in bullets:
        out.append('    <li data-bullet="%s">%s</li>'
                   % (R.e(b["id"]), R.keep_compounds(R.e(R.bullet_text(b, lang, omissions)))))
    out += ['  </ul>', '</div>']
    return "\n".join(out)


def skills_html(skills, lang, omissions):
    rows = []
    for level, key, cluster in skills:
        items = [i for i in cluster.get("items", []) if not R.is_todo(i)]
        label = cluster.get("label", "Skills")
        if lang == "de":
            label = cluster.get("label_de") or label
            items_de = cluster.get("items_de") or []
            raw = cluster.get("items", [])
            items = []
            for i, orig in enumerate(raw):
                if R.is_todo(orig):
                    continue
                de = items_de[i] if i < len(items_de) else ""
                items.append(de if de and not R.is_todo(de) else orig)
        if level == LEVEL["light"]:
            items = items[:5]
        if items:
            rows.append('<p class="kv"><span class="kv-label">%s:</span> '
                        '<span class="kv-value">%s</span></p>'
                        % (R.e(label), R.e(", ".join(items))))
    return "\n".join(rows)


def certs_html(certs, lang, omissions):
    items = []
    for c in certs:
        issuer = R.take(c.get("issuer"), "cert.%s.issuer" % c.get("id"), "issuer", omissions)
        year = R.fmt_date(R.take(c.get("year"), "cert.%s.year" % c.get("id"), "year",
                                 omissions), lang)
        tail = ", ".join(x for x in (issuer, year) if x)
        items.append("<li>%s%s</li>" % (R.e(c.get("name", "")),
                                        (" (%s)" % R.e(tail)) if tail else ""))
    return '<ul class="cert-list">%s</ul>' % "".join(items) if items else ""


def body_html(spec, ctx, p, omissions):
    lang = spec["lang"]
    L = SECTION_LABELS.get(lang, SECTION_LABELS["en"])
    base_def = ctx["threads"]["bases"][spec["base"]]

    projects = "\n".join(project_html(x["role"], x["bullets"], lang, omissions)
                         for x in p["projects"])
    # The earlier-builds line only follows real project entries: on its own
    # under "Selected projects" it read as a section with nothing in it.
    if p["earlier"] and p["projects"]:
        years = p["earlier"]["years"]
        span = years[0] if len(years) == 1 else "%s-%s" % (years[0], years[-1])
        projects += "\n" + R.compact_row("%s: %s" % (R.e(L["earlier_builds"]),
                                                     R.e(", ".join(p["earlier"]["names"]))),
                                         R.e(span))
    summary = ""
    if spec.get("summary_accepted") and (spec.get("summary") or "").strip():
        summary = '<p class="summary">%s</p>' % R.e(spec["summary"].strip())

    sections = {
        "summary": R.build_section(L["summary"], summary),
        "roles": R.build_section(L["roles"], "\n".join(
            entry_html(j["role"], j["bullets"], lang, omissions,
                       context=bool(spec.get("context_lines"))) for j in p["jobs"])),
        "projects": R.build_section(L["projects"], projects),
        "skills": R.build_section(L["skills"], skills_html(p["skills"], lang, omissions)),
        "certifications": R.build_section(L["certifications"],
                                          certs_html(p["certs"], lang, omissions)),
        "education": R.build_section(L["education"], R.build_education(
            ctx["career"], omissions, lang)),
        "languages": R.build_section(L["languages"], R.build_languages(
            ctx["career"], lang, omissions)),
    }
    parts = [header_html(spec, ctx, omissions)]
    parts += [sections[k] for k in sections_for(spec, base_def, p.get("projects_first"),
                                                 bool(p["projects"]))
              if sections.get(k)]
    return "\n\n".join(x for x in parts if x)


def page_html(spec, ctx, p, omissions):
    shell = (TEMPLATES / "shell.html").read_text(encoding="utf-8")
    style = (TEMPLATES / "cv.css").read_text(encoding="utf-8")
    name = ctx["career"]["identity"].get("name", "CV")
    return (shell.replace("{{LANG}}", spec["lang"])
            .replace("{{TITLE}}", "%s - %s" % (name, headline_text(spec, ctx) or "CV"))
            .replace("{{STYLE}}", style)
            .replace("{{BODY}}", body_html(spec, ctx, p, omissions)))


def preview(spec, ctx=None, prefer=()):
    """HTML for the live preview: no Chrome, no fitting. Returns (html, plan)."""
    ctx = ctx or load_context()
    p = plan(spec, ctx, prefer=prefer)
    return page_html(spec, ctx, p, R.Omissions()), p


# --------------------------------------------------------------------------
# fitting and output
# --------------------------------------------------------------------------

def trim_order(spec, ctx, p):
    """Bullet ids in the order page fitting removes them: Light-thread bullets,
    then everything else by value, lowest first. Hand-ticked bullets never."""
    forced = {k for k, v in (spec.get("bullets") or {}).items() if v is True}
    rows = []
    for group in (p["jobs"], p["projects"]):
        for x in group:
            role = x["role"]
            keep_one = years_ago(role) <= 10 and len(x["bullets"]) >= 1
            for i, b in enumerate(x["bullets"]):
                if b["id"] in forced:
                    continue
                light = level_of(b.get("threads"), spec) == LEVEL["light"]
                value = bullet_value(b, role, spec, (), ctx.get("posting_terms") or frozenset())
                # The first bullet of a recent job goes last: a recent job with
                # no detail reads as a gap.
                if keep_one and i == 0:
                    value += 4
                rows.append((0 if light else 1, value,
                             len(R.bullet_text(b, spec["lang"])), b["id"]))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [(bid, chars) for _, _, chars, bid in rows]


# A one-page CV that fits by cutting to fewer bullets than this is the "list of
# job titles" CV: twelve years at two employers as bare title lines.
# When the page count is the base's default rather than their explicit choice,
# the builder goes to a second page instead and says so.
THIN_BULLETS = 8


def build(spec, out_dir, basename="cv", prefer=(), fit=True, ctx=None):
    """Render html, pdf, txt and fields.json. Returns a result dict."""
    ctx = ctx or load_context()
    problems = validate(spec, ctx)
    if problems:
        return {"ok": False, "problems": problems}
    base_def = ctx["threads"]["bases"][spec["base"]]
    chosen = (spec.get("advanced") or {}).get("max_pages")
    result = _build(spec, out_dir, basename, prefer, fit, ctx,
                    int(chosen or base_def["max_pages"]))
    if (fit and not chosen and result.get("max_pages") == 1 and result.get("pages")
            and (result["pages"] > 1 or len(result.get("shown_bullets", [])) < THIN_BULLETS)):
        thin = len(result["shown_bullets"]) if result["pages"] == 1 else "fewer than 4"
        # The second page is there for detail: the professional per-job
        # limits fill it, the service ones left it three-quarters empty.
        first = result
        result = _build(spec, out_dir, basename, prefer, fit, ctx, 2, recency="professional")
        if first["pages"] == 1 and len(result["shown_bullets"]) <= len(first["shown_bullets"]):
            # Nothing more to say: a second page would only be white space.
            result = _build(spec, out_dir, basename, prefer, fit, ctx, 1)
            result["notes"].insert(0, "only %d bullets carry the dialed threads; turn a "
                                      "thread up or tick more to fill the page"
                                   % len(result["shown_bullets"]))
        else:
            result["notes"].insert(0, "one page left only %s bullets, so this is two pages; "
                                      "set pages to 1 under Advanced to force one" % thin)
    return result


def _build(spec, out_dir, basename, prefer, fit, ctx, max_pages, recency=None):
    base_def = ctx["threads"]["bases"][spec["base"]]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("_") or "cv"
    html_path, pdf_path, txt_path = (out_dir / ("%s.%s" % (stem, x))
                                     for x in ("html", "pdf", "txt"))
    for path in (html_path, pdf_path, txt_path):
        R.ensure_exact_case(path)
    chrome, ptt = R.find_chrome(), R.find_pdftotext()

    trimmed, caps, notes = set(), ({"recency": recency} if recency else {}), []

    def attempt():
        omissions = R.Omissions()
        p = plan(spec, ctx, frozenset(trimmed), caps, prefer)
        page = page_html(spec, ctx, p, omissions)
        html_path.write_text(page, encoding="utf-8")
        if not chrome:
            return p, page, omissions, None, "no Chrome or Edge found"
        ok, err = R.write_pdf(html_path, pdf_path, chrome)
        if not ok:
            return p, page, omissions, None, "pdf failed: %s" % err
        if not ptt:
            return p, page, omissions, None, "pdftotext not found"
        text, err = R.write_text_layer(pdf_path, txt_path, ptt)
        return p, page, omissions, text, err or ""

    p, page, omissions, text, err = attempt()
    pages = R.page_count(text) if text else None

    # Section caps come off before any bullet does.
    section_steps = []
    if base_def.get("max_certs", 0) > 2:
        section_steps.append(("certifications", 2))
    if base_def.get("max_projects", 0) > 2:
        section_steps += [("projects", 3), ("projects", 2)]

    def shown_count(plan_):
        return sum(len(x["bullets"]) for g in (plan_["jobs"], plan_["projects"]) for x in g)

    removal = []   # bullet ids in the order they were trimmed
    rounds = 0
    while fit and text is not None and pages and pages > max_pages and rounds < 12:
        rounds += 1
        if section_steps:
            key, cap = section_steps.pop(0)
            caps[key] = cap
            notes.append("%s cut to %d" % (key, cap))
        else:
            order = [x for x in trim_order(spec, ctx, p) if x[0] not in trimmed]
            # Never trim below the substance minimum on our own: a thin CV that
            # fits is worse than a full one that tells them what to untick.
            room = shown_count(p) - R.MIN_BULLETS
            if not order or room <= 0:
                notes.append("could not fit %d page(s) without dropping below %d bullets; "
                             "untick something or turn a thread down" % (max_pages, R.MIN_BULLETS))
                break
            # Remove about what overflows onto the last page, in one step,
            # rather than one bullet per render. Backfill below undoes overshoot.
            pages_text = [pg for pg in text.split("\f") if pg.strip()]
            need = len(" ".join(pages_text[-1].split())) + 120 if pages_text else 300
            removed = 0
            for bid, chars in order[:room]:
                trimmed.add(bid)
                removal.append(bid)
                removed += chars
                if removed >= need:
                    break
        p, page, omissions, text, err = attempt()
        pages = R.page_count(text) if text else None

    # Backfill: trimming in chunks overshoots, most on a one-page CV. Put back
    # the most valuable trimmed bullets (the last ones removed) for as long as
    # the CV still fits, found by binary search in a handful of renders.
    if fit and removal and text is not None and pages and pages <= max_pages:
        lo, hi = 0, len(removal)          # restore the last k removed, k in [lo, hi]
        best = (p, page, omissions, text, err, set(trimmed))
        while lo < hi:
            k = (lo + hi + 1) // 2
            trimmed.clear()
            trimmed.update(removal[:len(removal) - k])
            cand = attempt()
            cand_pages = R.page_count(cand[3]) if cand[3] else None
            if cand_pages and cand_pages <= max_pages:
                lo, best = k, cand[:5] + (set(trimmed),)
            else:
                hi = k - 1
        p, page, omissions, text, err, kept = best
        trimmed.clear()
        trimmed.update(kept)
        # Re-render the winner so the files on disk match it.
        p, page, omissions, text, err = attempt()
        pages = R.page_count(text) if text else None

    if trimmed:
        notes.append("trimmed %d bullet(s) to fit %d page(s)" % (len(trimmed), max_pages))

    fields = write_fields(spec, ctx, out_dir, stem)
    if text is not None:
        txt_path.write_text(R.paste_text(page), encoding="utf-8")
    shown = [b["id"] for g in (p["jobs"], p["projects"]) for x in g for b in x["bullets"]]
    return {
        "ok": text is not None and not err and pages is not None and pages <= max_pages,
        "err": err, "pages": pages, "max_pages": max_pages,
        "html": str(html_path), "pdf": str(pdf_path) if pdf_path.exists() else "",
        "txt": str(txt_path), "fields": str(fields),
        "shown_bullets": shown, "trimmed": sorted(trimmed), "notes": notes,
        "untranslated": p.get("untranslated", []),
        "omissions": omissions.items,
    }


def write_fields(spec, ctx, out_dir, stem):
    ident = ctx["career"].get("identity", {})
    name = ident.get("name", "")
    parts = name.split() if not R.is_todo(name) else []
    fields = {
        "full_name": name if not R.is_todo(name) else None,
        "first_name": parts[0] if parts else None,
        "last_name": " ".join(parts[1:]) if len(parts) > 1 else None,
        "email": None if R.is_todo(ident.get("email")) else ident.get("email"),
        "phone": None if R.is_todo(ident.get("phone")) else ident.get("phone"),
        "location": ident.get("city") if not R.is_todo(ident.get("city"))
                    else ident.get("location"),
        "headline": headline_text(spec, ctx),
        "work_authorization": None if R.is_todo(ident.get("work_authorization"))
                              else ident.get("work_authorization"),
    }
    for key, url in thread_links(ident, spec, ctx, R.Omissions()):
        fields["link_%s" % key] = url
    path = Path(out_dir) / ("%s.fields.json" % stem)
    R.ensure_exact_case(path)
    path.write_text(json.dumps({k: v for k, v in fields.items() if v}, indent=2,
                               ensure_ascii=False), encoding="utf-8")
    return path
