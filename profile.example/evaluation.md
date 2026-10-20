# Fit evaluation

Run before any drafting. Cheap to run, and its main job is to stop applications that
should not be written.

## Stage 1 — Hard gates

Any FAIL ends the evaluation. Do not score, do not draft.

Work authorization, relocation and language are **computed mechanically** by
`tools/prescreen.py` from `profile/market.json` (`home_places`, `home_countries`,
`wide_regions`, `us_home`, `language_gates`) — run it before reasoning about a posting,
and treat its `gates_triggered` output as authoritative, not this file. Nothing here
duplicates that logic or hardcodes a country or language: `market.json` is the single
place that changes when the user's situation does.

A gate this file *does* own, because it isn't a location/language fact:

| Gate | FAIL when |
|---|---|
| **Compensation** | A stated band whose upper bound is below the public target in `career.json` |
| **Legitimacy** | Unnamed employer, upfront payment, personal-email contact, or a request for identity documents before an interview |

Silence is not permission. A posting that says nothing about visa sponsorship has not
offered it. Proceed, but flag it as a question for first contact rather than assuming.

A language the user holds only partly (`language_gates` in `market.json`, e.g. "fluent
spoken, not professional written") is a genuine, specific limit, not a blanket pass or
fail: a posting that needs that language only for stakeholder conversations can clear
the gate even where one that needs polished unaided written output in it cannot. State
the actual distinction for the language and posting in front of you, from
`market.json`'s own gate note — never assume a limit the user hasn't recorded there.

## Stage 2 — Base and Lead thread

Pick the base (Professional or Service) and score the posting against each thread in
`threads.json` (`python3 tools/cv_suggest.py` does this mechanically). Record the Lead and the
margin.

A clear winner is required before scoring proceeds. If the top two are close, the posting
is a blend, and a blended application reads as unfocused. Surface it to the user and ask,
rather than averaging.

## The app's own score comes first

Every saved posting is scored automatically by `tools/qualify.py`: requirement
coverage against the CV the Build panel would make, Lead clarity, people-or-systems
orientation, and evidence. The breakdown is on the pipeline card. It is word-level and
mechanical. The rubric below is the judgement a /fit review adds on top: record its
score with `tools/pipeline.py`, which marks it `score_source: fit` so the automatic
score never replaces it.

## Stage 3 — Weighted score

| Dimension | Weight | 80–100 | 55–79 | 30–54 | 0–29 |
|---|---|---|---|---|---|
| **Affinity** | 20% | All three tests pass clearly | Two pass | One passes | None pass |
| **Capability** | 20% | Holds the core requirements outright | Most, with learnable gaps | Significant upskilling | Fundamental mismatch |
| **Environment** | 20% | English-first, arrangement fits, band clears comfortably | Workable with questions | Real friction | Wrong shape of company |
| **Evidence** | 15% | An existing artifact directly proves the central ask | Something adjacent can be adapted | Only assertion available | Nothing to show |
| **Career alignment** | 15% | Builds directly toward where you are going | Partial | Lateral, no compounding | Dead end |
| **Lead clarity** | 10% | One thread owns it cleanly | Clear winner, some blending | Two compete | No thread fits |

Score = (Affinity × 0.20) + (Capability × 0.20) + (Environment × 0.20) + (Evidence × 0.15) + (Career × 0.15) + (Lead × 0.10)

## Stage 3b — Bridge-job scoring (Service base)

Use this instead of Stage 3 whenever Stage 2 picks the Service base with a thread the
user treats as income-now rather than a career step — a bridge, not a destination. There
is no fixed list of which thread ids this applies to: if a `threads.json` service-base
thread's own `description` frames it this way, apply this stage to it.

Scoring a bridge thread against Evidence and Career alignment measures the wrong thing
and does real damage: a genuinely good local match structurally can't clear either
dimension (there is rarely a portfolio artifact for this kind of work, and it is not
supposed to build toward anything), which drags a strong fit down into the "skip" band
at exactly the moment `availability.json`'s own urgency note says income matters most.

Same total weight, same 0-100 scale, same verdict bands in Stage 4. Affinity, Capability,
Environment and Lead clarity keep their exact Stage 3 definitions and weights (20%,
20%, 20%, 10%). Evidence and Career alignment are replaced:

| Dimension | Weight | 80–100 | 55–79 | 30–54 | 0–29 |
|---|---|---|---|---|---|
| **Immediacy** | 15% | Hiring now, reachable within the stated commute/hours, no long process | Likely soon, minor friction | Unclear timeline or a real scheduling conflict | Not actually available now |
| **Honest reachability** | 15% | Every requirement has an honest match or a stated, closeable gap | One requirement is a real, open gap | Several open gaps, or one that cannot honestly be bridged | Requires a credential or experience they do not have and cannot honestly claim (e.g. a licence the posting requires that the user doesn't hold) |

Score = (Affinity × 0.20) + (Capability × 0.20) + (Environment × 0.20) + (Immediacy × 0.15)
+ (Honest reachability × 0.15) + (Lead × 0.10)

**Immediacy** replaces Career alignment: the question for a bridge job is not "does this
lead somewhere" but "does this actually solve the immediate problem." **Honest
reachability** replaces Evidence: there is no artifact to point to for this tier, so what
actually matters is whether the application can be built without fabrication or
overselling. If a thread's own notes in `threads.json` record which requirements are
honest, closeable gaps versus ones that can't be bridged, read those before scoring this
dimension rather than guessing.

### Affinity, and why it outweighs Lead clarity

TODO — once you have outcome data (`/outcome` on a few closed applications), replace
this with your own observed pattern: what distinguishes a role you'd choose to talk
about anyway from one that was merely plausible on paper. Until then, three general
tests:

1. **Subject matter.** Is this something the user would choose to talk about anyway?
2. **Framing.** Is the work framed around people and narrative, or around compliance,
   governance and metrics (when the user's threads are people-focused) — or around a
   real problem worth solving versus the technology being the deliverable itself (when
   they're not)?
3. **Purpose.** Is the work in service of a problem worth solving, or is the tool or
   process itself the deliverable?

Weight it at 20% because, empirically for most people, affinity predicts outcome at
least as well as capability: a role that's survivable on skill alone can still end badly
if the subject matter or its framing was never something the candidate wanted. A role
can also pass affinity while scoring modestly elsewhere and still be the right answer,
because the person will be good at it on a bad day.

`tools/prescreen.py` gives a rough proxy in the people-to-systems orientation ratio
(when the Lead thread's `people_focused` flag is set), but test 1 needs a human read of
the subject matter and cannot be automated.

**Evidence** is weighted this heavily because it is the one dimension that is *actionable*.
A low evidence score is not a reason to skip — it is a prompt to ask whether an artifact
could be built. That question is the highest-leverage moment in the whole process.

**Lead clarity** exists because an application that cannot decide what it is loses to
one that can, even when the underlying candidate is stronger.

## Stage 4 — Verdict

| Score | Action |
|---|---|
| **78+** | Apply with a purpose-built evidence artifact. Full effort. |
| **62–77** | Apply. Standard pipeline, existing evidence only. |
| **45–61** | Apply only if a warm path exists, or if the company is strategically worth the entry. Otherwise skip. |
| **< 45** | Skip. Say so plainly and do not offer to draft anyway. |

Before applying at any tier, check for a warm path first. A referral outperforms a
stronger cold application, and finding one takes minutes.

## Stage 5 — Record

Record the posting in `data/applications.jsonl` regardless of whether you apply,
including skips. Skips are training data: the pattern in what gets declined is as
informative as the pattern in what converts.

There is one line per application, keyed by `id` (company--role). Later steps update that
line; they never add a second one. Use the tool, which creates or updates as needed:

```bash
python3 tools/pipeline.py record --company "<company>" --role "<role>" --set \
    url=<url> thread=<lead id> score=<n> verdict=<band> stage=scored \
    'dimensions={"affinity":0,"capability":0,"environment":0,"evidence":0,"career":0,"persona":0}'
    # the Lead-clarity dimension keeps the key "persona" so older entries compare
```

Fields: `id`, `date`, `company`, `role`, `url`, `stage` (found, screened, scored,
drafted, sent, responded, interviewing, closed), `thread` (the Lead; older entries
carry `persona`), `score`, `dimensions`,
`verdict`, `evidence_artifact`, `warm_path`, `applied`, `outcome`, `outcome_date`,
`next_action`, `notes`. A skip is recorded with `outcome=skipped`, which closes it.

## Recurring anti-patterns

- Scoring a posting generously because the company is appealing. Environment is already a
  dimension; do not let it inflate capability.
- Treating a long requirements list as a checklist. Most are aspirational. Weight what the
  role's first ninety days would actually demand.
- Applying because the application is now cheap to produce. Cheap production raises volume,
  not conversion. The gates exist to keep the pipeline honest.
