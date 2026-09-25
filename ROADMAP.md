# Roadmap

Scaffolded 2026-09-25 from a private, working job-search system. The engine is copied
whole and runs on the fictional `profile.example/`: `render --check`, a full CV build, the
ATS check and all regression tests pass. What remains, in order:

## 1. Remove the original user from the code (small)

The name and home town were replaced. Remaining references to the original user's
employers and history, mostly in comments and examples, by file (count):

- `render/cv_builder.py` (5), `tools/careerdata.py` (5), `tools/claim_check.py` (5)
- `.claude/skills/fit` (4), `warm` (3), `scout` (1)
- `tools/cv_suggest.py`, `fit_and_select.py`, `package.py`, `prescreen.py`, `watch_ats.py` (1 each)
- `profile.example/de-glossary.json` (2), `evaluation.md` (1), `threads.json` (1)

Find them with:
`grep -rniE "mimecast|symantec|keepit|pingus|blaueszimmer|prosepixie|fuerstenfeldbruck" --exclude-dir=.git .`

Also review `profile.example/evaluation.md` and `writing-style.md` for the original user's
situation, and `tests/test_regressions.py` for cases that assume their data.

## 2. Configuration instead of constants (medium)

- `tools/prescreen.py` `HOME` and the relocation gate, `tools/watch_ats.py` location
  classes (DACH-first) -> read from `profile/availability.json`.
- German-market features (German CV, DIN 5008 letter, glossary, gender-tag detection)
  -> an optional "German market pack", off by default.
- Threads in `profile.example/threads.json` are the original user's seven; replace with a
  small, clearly-example set, and make `/setup` generate the real ones.
- `py` vs `python3` in docs and in `web/server.py`'s `PY`.

## 3. `/setup` (large, the main new feature)

`.claude/skills/setup/SKILL.md` is the specification. Build and test it end to end with a
real CV, including DOCX extraction and `tools/import_linkedin.py`.

## 4. Portfolio presentation

- Screenshots of Jane Doe's pipeline, Build panel, score breakdown and log.
- An architecture page and a security-model write-up (posting screen, `claude_run.SAFE_ARGS`,
  private tier, leak check).
- LICENSE (MIT suggested; the credited upstream is MIT). Owner's decision.
- How much of the original story the README tells. Owner's decision.

## Not copied, on purpose

The original user's `profile/`, `applications/`, `data/`, `documents/`, `STATUS.md`,
`plans/` and git history.
