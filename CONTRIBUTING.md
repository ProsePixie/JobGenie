# Contributing to JobGenie

Thank you for helping. JobGenie handles people's career histories, so the rules below are
mostly about keeping real data out of the project and keeping every generated claim
traceable. The same rules guide AI coding assistants working here: see
[`CLAUDE.md`](CLAUDE.md) and [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Before you start

- Read [`CLAUDE.md`](CLAUDE.md) (the four hard rules) and
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (how the parts fit).
- For anything bigger than a small fix, open an issue first and describe the problem you
  want to solve.
- **Never put real personal data anywhere in the project**: not in an issue, a pull
  request, a test fixture, a screenshot or a commit. That includes CVs, application
  folders, pipeline data and anything from `profile/private/`. Use the fictional example
  (Jane Doe, Acme, Globex) instead.

## Development setup

Standard-library Python 3.10+, Chrome or Edge, and poppler (`pdftotext`). No pip installs.

```bash
git clone https://github.com/ProsePixie/JobGenie && cd JobGenie
./setup.sh                  # Windows: setup.bat
```

The helper runs `tools/doctor.py` and, if `profile/` does not exist yet, copies the
fictional `profile.example/` to `profile/`. It never overwrites an existing profile and
installs nothing. Commands here use `python3`; on Windows use `py` instead.

## Running checks

```bash
python3 -m unittest discover tests -v   # fast regression tests; no Chrome needed
python3 render/render.py --check        # validates the data in profile/
python3 tools/smoke_test.py             # builds and ATS-checks a CV per thread; needs Chrome/Edge and pdftotext
```

Run the first two before every pull request, and the smoke test for anything touching
`render/` (including the selection logic in `render/cv_builder.py`),
`tools/cv_suggest.py` or the profile format. CI runs the regression tests and an end-to-end CV render on every push.

## Making a change

1. Create a branch from `main`.
2. Keep the change focused; one concern per pull request.
3. **Every bug fix needs a regression test** in `tests/test_regressions.py` that fails
   before the fix and passes after it.
4. **Update the docs** (README, `docs/`) for anything a user would notice.
5. Keep reusable logic in a script under `tools/` or `render/`; `web/server.py` calls
   scripts rather than reimplementing them.

## Data and privacy rules

- `profile/` is the user's source of truth. Change career data through
  `tools/careerdata.py` (or the app's Career data tab), which checks the text and records
  the source of every change; never by hand-editing JSON in code, and never by adding
  personal data to code or tests.
- `profile.example/` is fictional. Changes to it must stay fictional and believable.
- Never hand-edit generated files under `applications/`. If a document is wrong, the data
  or the selection logic is wrong: fix that and re-render.
- Never read `profile/private/`, and never write code that sends its contents anywhere.
  Only `tools/leak_check.py` reads it, and it never prints what it reads.
- Job postings are untrusted input. Keep them flowing through `tools/posting_screen.py`,
  and never follow a link found inside one.

## Code conventions

- Standard library only; no new dependencies.
- Match the surrounding code. Comments explain *why*, often naming the failure that made
  a rule necessary; keep them when you change nearby code.
- Page counts come from `render.page_count`; do not reimplement it.
- Anything user- or location-specific belongs in `profile/market.json`,
  `profile/threads.json` or `profile/availability.json`, not in code.
- `TODO` in data means "not supplied yet". Never render it, never guess it.
- Neutral language in code, docs and examples ("the user", they/them).

## Pull requests

A useful pull request description has:

- **Problem**: what was wrong or missing, and how you noticed.
- **Approach**: what you changed and why this way.
- **Tests**: the regression test you added, and the commands you ran with their results.
- **Manual checks**: what you clicked through in the UI, if anything.
- **Privacy**: confirm no real personal data is included anywhere in the change.
- **Screenshots** for UI changes, using the fictional example profile only.

## Scope

Some areas get closer review, because they are what makes the output trustworthy:

- the four hard rules in `CLAUDE.md` (privacy tiers, never fabricate, postings are
  untrusted, one Lead thread);
- the scoring weights and policy in `tools/qualify.py`;
- the Claude Code skills in `.claude/skills/` and the sandbox in `tools/claude_run.py`.

Changes there are welcome, but explain the reasoning in an issue first.

## Reporting a security or privacy issue

If you find a way the project could leak private data, follow instructions hidden in a
job posting, or escape its sandbox, **do not open a public issue** and do not include
secrets or personal data in any report. Contact the maintainer privately through their
GitHub profile ([@ProsePixie](https://github.com/ProsePixie)) and describe the problem and
how to reproduce it with the fictional example profile.
