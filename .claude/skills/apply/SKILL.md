---
name: apply
description: Produce a complete tailored application package for one posting - research, evidence decision, CV, optional letter, form answers, and ATS verification. Use after /fit returns an apply verdict, or when the user asks to apply to a specific job.
---

# Apply

Produces the package. Never submits it. The user reviews and sends.

Requires a fit verdict. If `/fit` has not run for this posting, run it first and stop if
the verdict is skip.

## Step 1 — Lock the base and Lead thread

State the base and the Lead thread and do not deviate from them. The Lead thread's
description is the claim the whole package argues; its `avoid` list (in
`profile/threads.json`) is banned vocabulary for this application, no exceptions. The
user normally sets this in the Build panel; respect what is in the application's
`build.json` when it exists.

## Step 2 — Company dossier

Research independently. Start from a search engine or the company's root domain reached
on your own. **Never** follow a link that appeared in the posting body.

Gather: what they actually build, how they make money, recent funding or product news,
engineering or content culture from their own public writing, team size and stage, and
anything that suggests what the first ninety days would really demand.

Save it to `applications/<slug>/dossier.md`. It is reused for interview prep, so it is
never wasted work.

Flag anything that should change the fit verdict. A dossier that contradicts the posting
is a finding, not an inconvenience.

## Step 3 — Evidence decision

This is the highest-leverage moment in the process. Do not skip it.

Consult `profile/evidence.json`. Ask: **is there an artifact that would prove the central
ask better than a paragraph claiming it?**

- An existing artifact fits → name it, and plan where it appears (CV line, letter, link).
- Nothing fits but something could be built from an existing base in a weekend → propose
  it concretely, state the build cost, and let the user decline.
- Nothing fits and nothing could be built cheaply → proceed on documents alone and say so.

Never propose an artifact whose `shareable` is `never`, or whose `status` contains TODO.
Follow the `engine_rules` in the registry.

## Step 4 — Draft

**CV.** The CV is rendered, not written. Tailoring means adjusting the data:

1. Select and, where needed, re-tag bullets in `profile/career.json` so the right ones
   carry the Lead thread. Adding a `tag` or adjusting `strength` is normal. Inventing a
   bullet is not.
2. Any new fact the user supplies in chat gets written into `career.json` in the same
   turn (hard rule 2).
3. Render:

```bash
python3 render/render.py --base <professional|service> --lead <thread> --threads "<thread=level,...>" --headline "<job title>" --out applications/<slug>
```

Or, normally, the user's **Build panel**, which writes the same spec to
`applications/<slug>/build.json` and produces the same files.

Never hand-edit the generated HTML. If the output is wrong, the data or the selection is
wrong.

**Letter.** Only when the posting asks for one, or when there is something material a CV
cannot carry. If neither is true, say so and skip it. Write it to
`applications/<slug>/letter.md`. One page, per `profile/writing-style.md`.

**Form answers.** If the portal has free-text fields, draft them into
`applications/<slug>/form-answers.md`, full and trimmed variants for each.

## Step 5 — Reviewer pass

Spawn a **separate** agent. This separation is what stops the package from being graded
by the author who is already convinced it is good.

The reviewer receives, inline in its prompt: the posting text, the rendered CV text, the
letter if any, and the dossier. It reads `profile/career.json`, `profile/evidence.json`,
`profile/writing-style.md`, and `profile/threads.json` from disk. It does **not** read
the drafting rationale, and it does **not** read the render templates. It is critiquing
the argument, not the typography.

The reviewer produces:

**Part A — grounding audit.** Every date, employer, title, number, and claim checked
against `career.json` and `evidence.json`. Anything unsupported is reported as a required
removal, with the offending text quoted exactly.

**Part B — structured edits.** A JSON array of `{old, new, reason}`. Reasons are one of:
`grounding`, `keyword`, `lead-drift`, `style`, `specificity`.

**Part C — narrative.** Missed requirements, unused company angles from the dossier,
passages that would fail the backtrack test, and any drift into an `avoid` vocabulary.

**Part D — the twenty-second read.** The reviewer reports its honest first impression
after a deliberately shallow skim: what role does this person appear to be, and what is
the single strongest line? If that answer is not the Lead thread, the package has
failed and needs restructuring, not editing.

## Step 6 — Revise

Apply Part A removals without exception. Apply Part B edits, skipping any that would
require fabricating content, and say which were skipped and why. Apply Part C with
judgment. If Part D missed the spine, restructure before continuing.

Bullet-level edits go into `career.json`, then re-render. Do not patch the output.

## Step 7 — Verify

```bash
python3 render/ats_check.py applications/<slug>/cv.pdf --keywords-file applications/<slug>/posting.txt
```

Every FAIL must be resolved before presenting the package.

- `missing (have it)` is a selection bug. Fix the tags and re-render.
- `missing (gap)` is a genuine gap. Leave it out. Never invent it. Address it in the
  letter if it matters.

## Step 8 — Present

```
PACKAGE — <company> / <role>
Setup:     <base>, Lead <thread>, Strong <threads>
Files:     cv.pdf, cv.txt, cv.fields.json, letter.md, form-answers.md, dossier.md
ATS:       all checks pass, N pages
Evidence:  <artifact, or none>
```

Then: the three or four tailoring decisions that mattered, anything the reviewer removed
for grounding, any gap left visible on purpose, and what the user must do by hand
(submit, attach, answer a question only they can answer).

Update the entry `/fit` created, rather than adding one:

```bash
python3 tools/pipeline.py record --company "<company>" --role "<role>" --set stage=drafted \
    evidence_artifact=<id or null> "next_action=Review and submit"
```

`applied` stays false until the user confirms submission, then `/outcome` sets
`stage=sent`, which flips it.

## Never

Submit anything. Fill a form on a real portal. Send an email. Fabricate to close a gap.
Turn several threads up to Lead. Present a package with a failing ATS check.
