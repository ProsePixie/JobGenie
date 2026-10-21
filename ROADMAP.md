# Roadmap

Scaffolded 2026-09-25 from a private, working job-search system, then generalised so it
works for anyone, anywhere. Verified on the fictional `profile.example/` (a US user):
add a job, automatic score, Build panel, preview, finalize with ATS check, letter
scaffold, package, document viewer, log. All regression tests pass, including the
location classifier for both a US and a German user.

## Done

- The original user's data, history and name are gone; code comments, skills and
  examples are neutral (they/them, Acme/Globex examples).
- `profile/market.json`: home places and countries, regions that include home, CV
  languages, language gates. Read by the job-board watcher, the prescreen and the CV
  builder, so location filtering and gates work anywhere.
- German market features are optional: German CVs only when `"de"` is in
  `cv_languages`; the Bundesagentur board only when added as a source.
- Thread behaviour is data, not ids: `people_focused` (scores orientation) and
  `systems_ok` (no penalty for systems work) in `threads.json`.
- A generic example `threads.json` (English bases, five example threads).
- `/setup` tools: `doctor`, `new_profile`, `import_cv` (PDF, DOCX), `import_linkedin`
  (proposes, never writes, never opens connections), `careerdata add`.
- Send folder is a setting; `python3` in all docs.

## Next

1. **`/setup` with a real CV**: the skill and its tools (`doctor`, `new_profile`,
   `import_cv`, `import_linkedin`, `careerdata add`) are built and tested end to end with a
   fictional CV; it needs a run with a real person's CV and their feedback.
2. **Other CV languages** ([#5](https://github.com/ProsePixie/evidence-bound-job-application-system/issues/5)).
3. **More job sources.** Greenhouse, Lever, Ashby, SmartRecruiters, Workable and the
   Bundesagentur are supported; national boards elsewhere are not.

## Portfolio presentation

- Done: screenshots, sample CV, CI badge, MIT license. Still: a short screen recording.
- Done: [How it works](docs/HOW-IT-WORKS.md), the design and security write-up.
- How much of the original story the README tells. Owner's decision.
