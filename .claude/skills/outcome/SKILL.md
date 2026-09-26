---
name: outcome
description: Record what happened to an application and report what the accumulated log now shows. Use when the user hears back from a company, confirms a submission, or asks what is working in their job search.
---

# Outcome

Closes the loop. Tracking alone changes nothing; this exists to turn the log into a
decision about what to do differently.

## Recording

Update the application's entry with `tools/pipeline.py record`, using the same company
and role it was recorded under (`python3 tools/pipeline.py show` lists them). Set `outcome`
to one of:

`pending` · `rejected-auto` (no human involved, days) · `rejected-screen` ·
`rejected-interview` · `ghosted` (no reply after 30 days) · `screen` · `interview` ·
`offer` · `withdrawn`

A terminal outcome (rejected, ghosted, offer, withdrawn) closes the card and dates
itself. Add a note if there is a stated reason worth keeping:

```bash
python3 tools/pipeline.py record --company "<company>" --role "<role>" \
    --set outcome=rejected-screen "notes=Said they wanted deeper Salesforce admin"
```

`rejected-auto` and `ghosted` are distinct and the difference matters. Fast automated
rejection points at the CV or the eligibility signal. Silence points at the pile.

If the user is reporting a submission rather than a reply, set `stage=sent` and leave
`outcome` as `pending`; `applied` follows the stage.

## Reporting

Once there are ten or more applied entries, report the patterns. Below that, say so
plainly rather than reading noise as signal.

Break down response rate by:

- **Lead thread** (`build.lead` on each entry) — which one converts, which one you merely enjoy (older
  entries carry a `persona` instead; `threads.json` `from_personas` maps them)
- **evidence** — applications with a purpose-built artifact against those without
- **warm path** — referral against cold
- **fit score band** — whether the rubric predicts anything, which is how the rubric
  itself gets audited
- **company size and type** — where the replies come from

Report counts alongside every rate. "Two of three" is not sixty-seven percent, and
presenting it that way invents confidence that does not exist.

## The useful output

Do not stop at a table. End with the one change worth making, stated concretely.

Good: "Six of your eight `enablement` applications got a reply; one of seven for
`content-multimedia`. Stop applying under `content-multimedia` unless there is a warm
path."

Useless: "Consider focusing on your strongest areas."

If the log contradicts something in `profile/evaluation.md` — a dimension that predicts
nothing, a threshold set too low — say so and propose the edit. The rubric is a
hypothesis, not scripture.
