---
name: evidence
description: Decide whether to ship a working artifact with an application, scope it, build it, and register it. Use during /apply for strong-fit roles, or when the user asks what they could build to prove a skill.
---

# Evidence Engine

The premise of this whole system: for a candidate who builds things, a working artifact
outperforms another paragraph claiming competence. This workflow decides when that is
true and then does it.

Read `profile/evidence.json`, including its `engine_rules`.

## Step 1 — Is an artifact warranted?

Not every application deserves one. Build only when the fit score is strong (78+), or
when the role's central ask is something the CV can only assert.

Ask the sharper question: **what would this employer need to believe to interview
someone with no formal credential in their exact domain?** That belief is what the
artifact has to produce. If a document can produce it just as well, skip the build.

## Step 2 — Match against the registry

Three outcomes, in order of preference:

**Something already fits.** Name it. Decide where it appears: a CV line, a letter
sentence, a link, or a short recorded walkthrough. Cheapest and usually sufficient.

**Something can be adapted.** An existing base extended toward this employer's domain.
This is the sweet spot: a weekend at most, and it reads as purpose-built because it is.

**Nothing fits.** Say so and proceed on documents. A from-scratch build is how
applications stop shipping.

Never propose an artifact whose `shareable` is `never`, or whose `status` contains TODO.

## Step 3 — Scope honestly

State before any work begins: what it will be, what it will demonstrate, roughly how long
it will take, and what it will *not* do. Then let the user decline. An artifact that
arrives two weeks after the posting closed has negative value.

Hard ceiling: a weekend, from an existing base. If the scope exceeds that, cut it until
it does not, or drop it.

## Step 4 — Build

Build it properly. A broken demo is worse than no demo, because it demonstrates
precisely the wrong thing.

Constraints:

- It must run for someone who has never seen it, with no setup.
- It must be honest about its limits. A README noting what it does not handle reads as
  engineering maturity, not weakness.
- **Never use the target company's logo, branding, name-as-owner, or anything that could
  be mistaken for their own material.** This is your work, made for their problem, and it
  says so.
- No credentials, no scraping their systems, no live data you were not offered.

Publish as a private-by-default page when a link is the right format. The user decides
whether it is shared.

## Step 5 — Register

Append it to `profile/evidence.json` with `proves`, `threads`, `shareable`, and where it
was sent. Today's bespoke artifact is next month's existing-artifact match, which is how
this compounds instead of restarting each time.

## Step 6 — Place it

An artifact nobody opens is wasted. It needs a single sentence in the application saying
what it is and why it exists, in the plainest possible terms.

Good: "I built a small demo of constraint-checked generation against the kind of content
you publish, because your posting asks for reliability rather than fluency. Two minutes:
<link>."

Bad: anything containing "showcase", "passion project", or "I took the liberty of".

## Standing ideas

Reusable moves for this candidate, drawn from what already exists:

- **The canon-lock demo.** Extract the mechanism from SBtA, minus the manuscript. It
  demonstrates hallucination control by architecture. Aim it at any AI product team
  whose problem is consistency rather than capability.
- **The teardown.** Take the employer's public docs, onboarding, or help centre and
  produce a short, specific critique with a rebuilt sample. Aimed at enablement and
  customer-education roles, where it doubles as a work sample and a first-week plan.
- **The scored walkthrough.** A two-minute recorded product or concept walkthrough,
  written, voiced, and scored. Almost nobody applying to a content role can do the whole
  chain alone, and the recording proves it in a way a CV line cannot.
