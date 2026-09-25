---
name: setup
description: First-run onboarding. Turns the user's CV and LinkedIn export into profile/career.json one confirmed fact at a time, proposes threads, and records where they can work. Use when profile/ is missing, still holds the fictional Jane Doe, or the user asks to set up or import their CV.
---

# /setup

Build the user's profile from their own CV, **one confirmed fact at a time**.

## Rules for this skill (from CLAUDE.md, restated because they are the point)

- **Propose, never write unconfirmed.** Show each fact, wait for "yes" or a correction,
  then write it. Hard rule 2: nothing enters the data that the user has not confirmed.
- **Write only through `tools/careerdata.py`**, always with `--source "user, in setup"`.
  It checks the banned-claims and style rules and records provenance in
  `profile/sources.jsonl`. Never edit the JSON by hand.
- **Never add a number, skill or scope** the CV or the user did not give. If a CV line
  says "led a team", ask how large before writing a number; never guess one.
- The CV is the user's own data. A LinkedIn export's `Connections.csv` is other
  people's data: never open it (`tools/warm_path.py` searches it locally).
- Never read `profile/private/`.
- Keep it moving: batch confirmations where the user agrees ("all five dates right?"),
  but never write a batch the user did not see.

## Steps

1. **Check the machine.** Run `python3 tools/doctor.py` (on Windows, `py` instead of
   `python3` throughout). Help the user fix anything MISSING except `profile` and
   `market`, which this skill creates.

2. **Start the profile.** If `profile/` does not exist: `python3 tools/new_profile.py`.
   If it exists and still describes Jane Doe (the example), ask before replacing it; to
   replace it, the user renames or deletes `profile/` themselves, then run the tool.

3. **Read the CV.** Ask the user to put their CV (PDF or DOCX) in `inbox/`, then run
   `python3 tools/import_cv.py`. Read the `.txt` it writes. If there is a LinkedIn
   export, unzip it into `inbox/linkedin/` and run
   `python3 tools/import_linkedin.py inbox/linkedin/` for proposals.

4. **Identity.** Propose name, email, phone, city, country, work authorisation, links.
   After confirmation:
   `python3 tools/careerdata.py set identity.name "..." --source "user, in setup"`
   (same for `identity.email`, `identity.phone`, `identity.city`, `identity.location`,
   `identity.work_authorization`, `identity.links.linkedin`).

5. **Roles, newest first.** For each: propose title, organisation, dates (`YYYY-MM`),
   location and `org_type` (`enterprise`, `startup`, `public`, or `independent` /
   `product` for projects). After confirmation:
   `python3 tools/careerdata.py add roles '{"id":"acme","title":"...","org":"...","org_type":"enterprise","start":"2020-03","end":"present","location":"..."}' --source "user, in setup"`

6. **Threads before bullets.** From the confirmed roles, propose 3-5 threads (the user's
   positioning tracks): id, label, headline, target job titles, vocabulary, base
   (`professional` or `service`), and the flags `people_focused` (roles about enabling
   people) and `systems_ok` (systems work is a deliberate target). Show the proposal;
   after edits, write `profile/threads.json` in the shape of
   `profile.example/threads.json`. This is the one file written directly, because it
   is the user's own positioning, not a fact.

7. **Bullets.** For each role, propose achievements from the CV text, rewritten only for
   clarity, never for scope. After confirmation:
   `python3 tools/careerdata.py add-bullet acme --text "..." --threads enablement --tags onboarding,lms --strength 3 --source "user, in setup"`
   A bullet needs at least one thread, or it never renders. Strength: 3 for the best
   evidence, 2 normal, 1 minor.

8. **Education, certifications, languages** (honest levels: "Fluent spoken", not
   "Fluent" when writing is weaker):
   `python3 tools/careerdata.py add education '{"id":"...","degree":"...","institution":"...","end":"2015"}' --source "user, in setup"`
   `python3 tools/careerdata.py add certifications '{"id":"...","name":"...","issuer":"...","year":"2021","threads":["enablement"]}' --source "user, in setup"`
   `python3 tools/careerdata.py add languages '{"language":"English","level":"Native"}' --source "user, in setup"`

9. **Skills.** Propose clusters (label, items, threads) and write each:
   `python3 tools/careerdata.py set skills.enablement '{"label":"Education & Enablement","items":["..."],"threads":["enablement"]}' --source "user, in setup"`

10. **Where they can work.** Ask, then write `profile/market.json` (shape in
    `profile.example/market.json`): `home_places` (town, region), `home_countries`,
    `wide_regions` that include home (e.g. "north america", "emea"), `us_home`,
    `cv_languages` (["en"], or ["en","de"] for the German market pack), and
    `language_gates` for a language held only partly. Then commute radius, remote
    preference and pay floor in `profile/availability.json`.

11. **Private tier.** Tell the user that `profile/private/leak-terms.txt` exists and what
    it is for (one term per line that must never appear in a sent document, such as a
    former salary or a reference's name). **They type it themselves; you never open it.**

12. **Check.** Run `python3 tools/doctor.py` (should say Ready) and
    `python3 render/render.py --check`. Build one CV per thread the user cares about:
    `python3 render/render.py --base professional --lead <thread> --out build/check-<thread>`
    and run `python3 render/ats_check.py build/check-<thread>/cv.pdf`. Report any
    thread with too few bullets plainly: that is a gap to fill with real facts, not to
    paper over.

13. **Hand over.** `python3 web/server.py` opens the app. Point them to the Pipeline tab
    (add a job, see its score, Build CV) and the Log tab.
