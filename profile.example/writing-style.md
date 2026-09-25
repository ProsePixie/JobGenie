# Writing style

Rules for every generated CV, letter, form answer, and outreach message.

## Spelling: American English, always

The candidate is a native American English speaker and does not write British English.
Use American spellings in every document, every profile file, and every draft:

organization, program, standardize, localization, behavior, skeptical, recognize,
analyze, center, specialize, catalog, license, fiber, judgment, canceled, modeling.

Not: organisation, programme, standardise, localisation, behaviour, sceptical.

This applies even when writing to a UK or European employer. It is his voice, not a
regional convention to be matched to the reader.

**One exception: dates are European order, day, month, year.** Stated by the user on
2026-09-24. Write "24 September 2026", never "September 24, 2026". Spell the month out
in prose and letters so the date cannot be misread as the US order; in the CV the
existing "Sep 2026" month-year form stays as it is.

## Voice

First person, active, specific. "I built the certification path for X" — not "was
responsible for the development of certification pathways".

Warm and direct. Confident without swagger, plain without flatness. Write the way a
competent person talks about work they actually did.

Demonstrate, do not state. Replace every adjective about yourself with the thing that
would make a reader conclude it unprompted. "Detail-oriented" is worthless; a sentence
showing the detail is not.

## Banned outright

These are LLM tells, recruiter clichés, or both. They are never acceptable:

- Em-dashes. Use a comma, a full stop, or a colon.
- "passionate about", "excited about the opportunity"
- "I believe I would be a great fit", "I am confident that I would"
- "leverage", "leveraging" in any form
- "hit the ground running", "drive results", "synergy", "synergies"
- "spearheaded", "orchestrated", "champion" as a verb
- "proven track record", "results-driven", "dynamic professional"
- "seamless", "robust", "cutting-edge", "state-of-the-art", "best-in-class"
- "delve", "tapestry", "testament to", "in today's fast-paced world"
- Apologetic hedging: "I think I could contribute", "I may not have X but"
- Rhetorical tricolons ("not just X, but Y and Z")

Also banned: opening a letter with "I am writing to apply for". State the connection
between you and the work in the first sentence instead.

## Never in the document

Photo. Date of birth. Marital status. Nationality. Family or dependents. Health.
Religion. A full postal address — city and country is sufficient.

This is deliberate and it overrides local convention. Including protected-characteristic
data creates screening liability for international employers, and some recruiters are
trained to set such applications aside rather than risk it.

## Structural rules

**CV**
- Never generic, never mostly blank (the user's rule, 2026-09-24). Every job in
  `career.json` is listed, at least as one line with title, employer and dates; at least
  four bullets of real work; applicable skills shown. `render/ats_check.py` fails any CV
  that breaks this, and `tools/smoke_test.py` runs it for every persona. A persona that
  fails gets more of his real bullets tagged, never a softer rule.
- Two pages maximum. One page is fine and often better.
- Reverse chronological within sections; section order comes from the selected persona.
- Every bullet starts with a concrete verb or a category label, never with "Responsible for".
- Numbers where the data has them. No number where the data does not — never estimate.
- Vary bullet construction. Three identical shapes in a row reads as generated.
- No prose paragraph summary at the top unless the persona calls for it. If present, two
  sentences, and it must say something a competitor could not copy.

**Letter (only when the posting asks, or when there is something a CV cannot carry)**
- One page, and usually well under.
- Open with the specific connection: what they are doing, what you have built that bears
  on it. Two or three sentences.
- Do not restate the CV. The letter is forward-looking: what you would do about their
  problem.
- Close briefly and without pleading.

**Form answers**
- Write one version per persona, not one for all applications. A prompt-engineering
  employer and an enablement employer are asking different questions with the same words.
- Supply both a full and a trimmed variant. Portals truncate silently.

## Evidence rules

A link to a working artifact outranks any sentence claiming the same competence. Where a
bullet and an artifact make the same point, cut the bullet and keep the link.

Never reference an artifact whose registry `shareable` is `never`, and never one whose
`status` still contains a TODO.

## The grounding tests

Applied to every line before it ships.

**Backtrack test.** Could this survive "tell me more about that" in an interview,
answered without hedging? If not, cut it.

**Source test.** Does this trace to `career.json`, `evidence.json`, or something the user
said in this conversation? If not, it does not exist.

**Terminology test.** Am I describing adjacent work using this posting's specific
vocabulary? Adjacent is not the same. Say what the work was, in words that were true
before this posting existed.

**Merge test.** Am I combining separate roles or projects into one claim that implies
more scope than any single one had? Split it or drop it.

## Language

English by default, including for German employers, because the target is English-first
international companies.

Write in German only when the posting is in German **and** the user confirms it for that
application. When writing German, it is still an English-market CV in German words: no
photo, no personal data, no Lebenslauf table conventions.
