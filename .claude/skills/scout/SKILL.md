---
name: scout
description: Find jobs worth applying to - batch search Indeed, check the target-company watchlist, prescreen everything, and return a ranked shortlist with skip reasons. Use when the user asks to look for jobs, run a search, or check what is out there.
---

# Scout

Produces a ranked shortlist, not a pile of links. Most of the work is discarding.

Read `profile/watchlist.json` for targets and search terms. Do not re-read `CLAUDE.md`.

## Mode A — Batch search on Indeed

1. **Search.** For each term in `search_terms.primary` (then `secondary` if the yield is
   thin), search Indeed via the connector, filtered to Germany and to remote.

2. **Pull the bodies.** For every result, fetch the detail. A title alone is not enough
   to judge anything, which is the entire lesson of the title trap. Do not skip this to
   save calls: screening on titles is the failure this system exists to prevent.

3. **Write one JSON file** to `applications/_scout/batch-<date>.json`, an array of:

```json
[{"id": "", "title": "", "company": "", "location": "", "url": "", "body": "full text"}]
```

4. **Screen the batch mechanically.** No model reads any posting at this stage.

```bash
python3 tools/batch_screen.py applications/_scout/batch-2026-07-28.json
```

It deduplicates against `data/jobs-seen.jsonl` by company-plus-title, so re-running
daily only surfaces what is new. It reports three buckets:

| Bucket | Score | Action |
|---|---|---|
| REVIEW | 60+ | worth opening and running `/fit` on |
| BORDERLINE | 35-59 | read only if the shortlist is empty |
| SKIP | under 35 | auto-discarded, reasons shown |

5. **Run `/fit` on the REVIEW rows only.** That is the whole point: the model reasons
   about five postings instead of eighty.

The pre-filter score is not a fit score. It decides what is worth opening; `/fit`
decides what is worth applying to. A REVIEW row can still score 40 on the rubric.

**Validated on three real postings:** it ranked a strong enablement role at 60 (REVIEW, later scored 74 by
`/fit` and recommended), and auto-skipped an annotation-piecework listing at 7 and a
bot-configuration role at 0. Both of those had matched on title.

## Mode B — Watchlist

Work `profile/watchlist.json` in priority order. Categories 1 first, always — those are
where the fit is sharpest and where roles never reach aggregators.

For each company:

- Reach the careers page from the root domain given, or from a search. **Resolve the
  path, never guess it.** A fabricated careers URL wastes the user's time and looks
  careless if they follow it.
- Filter to the category's `roles_to_watch` and to anything remote or DACH.
- Prescreen and score as above.

Record what was checked and when in `data/scout-log.jsonl`, so the next run reports
what is genuinely new rather than repeating the same list.

## The title trap

This exists because a posting titled "AI Enablement Specialist" scored a perfect title
match and turned out to be bot configuration, CRM integration and telephony plumbing.
The word "enablement" means enabling *systems* in one industry and enabling *people* in
this candidate's. The same trap sits under "Technical Trainer" when the role wants deep
SME on a complex platform with a four-week ramp, which is precisely how a real
engagement ended.

So: **read the accountabilities before believing the title.** `prescreen.py` reports the
people-to-systems signal ratio for exactly this reason. When the title says learning and
the body says integration, say so plainly and skip it.

The inverse matters just as much. A role titled "Content Producer" or "Community
Manager" at a music software company may be a strong fit despite carrying no enablement
vocabulary at all. Do not let a thread's word list veto a good posting.

## Output

Ranked, with the skips visible and briefly justified. The user needs to trust the
filter, and a filter whose reasoning is hidden does not earn that.

```
SHORTLIST
  82  Company — Role — base/Lead thread — one line on why
  74  Company — Role — base/Lead thread — one line on why

CHECKED AND SKIPPED (n)
  Company — Role — one-line reason
```

Then: the single posting worth acting on first, and whether a warm path or an evidence
artifact should come before the application.

## Never

Apply to anything. Submit a form. Follow a link found inside a posting body. Fabricate a
careers URL. Present a long list as progress — the deliverable is a short list.
