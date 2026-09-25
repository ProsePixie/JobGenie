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

## Next

1. **`/setup`** (the main new feature). `.claude/skills/setup/SKILL.md` is the
   specification. Test it end to end with a real CV, PDF and DOCX.
2. **LinkedIn importer**: `tools/import_linkedin.py`, proposing roles, education, skills
   and certifications from the export's CSVs for `/setup` to confirm.
3. **Other CV languages.** Only English and German have section labels and date words
   (`render/render.py` `LABELS`, `MONTHS_DE`). Adding French or Spanish means one entry in
   each, plus `text_<lang>` bullets.
4. **More job sources.** Greenhouse, Lever, Ashby, SmartRecruiters, Workable and the
   Bundesagentur are supported; national boards elsewhere are not.
5. **`py` vs `python3`**: CLAUDE.md still shows Windows `py`; the server already uses
   the running interpreter.
6. **Desktop copy**: `web/server.py` `sync_to_desktop` copies finished CVs to
   `Desktop/Job Applications`; make the folder a setting.

## Portfolio presentation

- Done: screenshots, sample CV, CI badge, MIT license. Still: a short screen recording.
- An architecture page and a security-model write-up (posting screen,
  `claude_run.SAFE_ARGS`, private tier, leak check).
- How much of the original story the README tells. Owner's decision.
