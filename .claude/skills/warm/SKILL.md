---
name: warm
description: Check for an existing connection at a target company before applying cold, and draft the approach. Use during /fit or /apply, or whenever the user names a company they are considering.
---

# Warm path

A referral converts far better than a stronger cold application, and checking costs
seconds. Run this **before** drafting, not after.

## Step 1 — Search locally

```bash
py tools/warm_path.py "Company Name"
```

The script filters the connections export on disk and prints only matching rows. Run it
rather than reading the CSV into context: the file is personal data about several hundred
people, and only the two or three relevant names need to surface.

If no export exists, the script says how to produce one. Do not work around its absence
by searching for the user's contacts online.

Widen with `--min-score 0.5` before concluding there is nothing. Use `--list-companies`
when the user wants to see where their network actually sits, which is often a better
guide to where to apply than any job board.

## Step 2 — Look for indirect paths

The export only records where people work *now*. Two other paths are worth checking by
hand:

- **Alumni overlap.** Check every employer in the user's career.json.
  People move. Ask whether they remember anyone who went to the target company.
- **Domain overlap.** Enablement and AI tooling are small worlds. A former colleague may
  know someone without working there.

Ask the user. Do not go looking through their social accounts or browser history.

## Step 3 — Grade the connection

Be honest, because a bad ask costs a relationship:

- **Strong** — worked together directly, would recognise the name instantly. A referral
  request is reasonable.
- **Weak** — connected but never worked together, or contact lapsed years ago. Ask for a
  conversation about the company, never for a referral outright.
- **Nominal** — a conference add from 2019. Treat as cold. Do not use.

## Step 4 — Draft the approach

Write it to `applications/<slug>/outreach.md`. Never send it. The user sends it, from
their own account, in their own words.

Rules for the draft:

- Short. Under 120 words. A long ask is a burden and reads as one.
- Lead with the actual connection, specifically. "We worked on the partner onboarding
  programme together" beats "we're connected on LinkedIn".
- Ask for the smallest useful thing. A referral is a large ask; ten minutes on what the
  team is actually like is a small one, and often produces the referral anyway.
- Say what you are considering and why, in one sentence.
- Make declining easy and unembarrassing. Explicitly.
- No flattery, no urgency, and never imply the relationship is closer than it is.

## Step 5 — Record

Record it on the application's entry:

```bash
py tools/pipeline.py record --company "<company>" --role "<role>" --set warm_path=true
```

The learning loop compares conversion with and without, and that comparison is usually
the most decisive number in the whole log.

## Never

Contact anyone on the user's behalf. Add people the user does not know. Mention a
connection's name inside an application without the user confirming it. Treat someone's
professional network as a lead list.
