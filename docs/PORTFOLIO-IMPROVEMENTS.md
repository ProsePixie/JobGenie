# Portfolio Improvements — Claude Code Implementation Specification

> **Purpose:** This document is an implementation brief for Claude Code. Read it from top to bottom, inspect the repository before editing, then implement the changes in the order specified below.
>
> **Repository:** `ProsePixie/JobGenie`
>
> **Important:** This is a portfolio-documentation and onboarding improvement project. Do not change JobGenie's core privacy, sourcing, scoring, rendering, or Claude-safety rules unless a task below explicitly requires it. Do not add third-party Python dependencies.

---

## 0. Operating rules

Before making changes:

1. Read `CLAUDE.md` and `.github/copilot-instructions.md`.
2. Inspect the current repository tree and the existing files referenced below.
3. Read `docs/HOW-IT-WORKS.md`, `docs/SETUP.md`, `tests/test_regressions.py`, `tools/doctor.py`, and the relevant web/server and rendering modules before writing documentation about them.
4. Treat the current implementation as the source of truth. Do not claim that a feature exists unless the code confirms it.
5. Use the repository's terminology consistently: `profile/` is the source of truth; `applications/` contains generated application artifacts; postings are untrusted data; exactly one thread is `Lead`.
6. Never read, quote, or use anything under `profile/private/`, except through the already-approved leak-check mechanism. Do not include personal data in examples.
7. Use neutral, generic example data only: Jane Doe, Acme, Globex, and fictional paths.
8. Standard library only for Python. No pip packages, no LaTeX, and no new runtime dependency.
9. Add or update tests only where a behavioral script change is introduced. Documentation-only changes do not need artificial tests.
10. Do not create a live demo, external service, analytics, telemetry, or hosted deployment as part of this task.

If any requested documentation conflicts with the code, document the actual behavior and add a short `Implementation note` identifying the discrepancy. Do not silently invent behavior.

---

## 1. Deliverables

Create or modify exactly these files unless an existing file must be adjusted to keep the instructions accurate:

### Create

- `docs/ARCHITECTURE.md`
- `CONTRIBUTING.md`
- `setup.sh`
- `setup.bat`

### Modify

- `README.md`

### Optional

Do **not** create a GIF-generation tool in this task. A GIF cannot be reliably generated from the standard library alone, and adding a media pipeline would distract from the portfolio goal. Use the existing screenshots and sample PDF. If a future contributor wants a GIF, document it as a manual recording task in `docs/ARCHITECTURE.md` or the README rather than pretending it is automated.

---

## 2. Create `docs/ARCHITECTURE.md`

Write a concise but technically meaningful architecture document aimed at a hiring manager, contributor, or engineer who has not read the entire repository.

### Required title and opening

Use this title:

```markdown
# JobGenie Architecture
```

Open with a short paragraph explaining that JobGenie is a local, data-first job-search system. State that it renders application artifacts from structured career data instead of allowing an AI model to rewrite a person without traceability.

### Required sections

Include these sections, in this order:

1. `## Design goals`
2. `## System overview`
3. `## Repository layers`
4. `## Data flow for an application`
5. `## Privacy and safety boundaries`
6. `## Rendering and document verification`
7. `## Positioning with bases and threads`
8. `## Local web UI`
9. `## Testing and reliability`
10. `## Trade-offs and known limits`
11. `## Extension guidelines`

### Content requirements

#### Design goals

Explain these goals:

- factual traceability and no fabricated claims;
- local-first handling of sensitive career information;
- useful artifacts even when AI features are unavailable;
- one source of truth for command-line and web workflows;
- checks that validate the output a recruiter or ATS actually receives.

#### System overview

Include a Mermaid diagram only if the repository's Markdown conventions support it. Otherwise use an ASCII diagram. The diagram must show this conceptual flow:

```text
profile/*.json + profile/*.md
              |
              v
       posting screen / qualify
              |
              v
       base + thread selection
              |
              v
      CV and letter renderers
              |
              v
       ATS and leak checks
              |
              v
       package / send artifacts
```

Make clear that `web/server.py` is a thin local driver over the same scripts and is not a second implementation of the business logic.

#### Repository layers

Describe the actual responsibilities of:

- `profile/` and `profile.example/`;
- `applications/`;
- `data/`;
- `render/`;
- `tools/`;
- `web/`;
- `.claude/skills/`;
- `tests/`;
- `docs/`.

Use links to files that actually exist. Verify every link before committing.

#### Data flow for an application

Describe the normal funnel:

```text
fit -> warm -> apply (dossier -> evidence -> draft -> review -> verify) -> prep -> outcome
```

Explain the role of a saved posting, qualification, evidence selection, CV rendering, letter rendering, ATS checking, leak checking, packaging, and pipeline updates. Do not claim that every stage is automatic if it is not.

#### Privacy and safety boundaries

Accurately document:

- the public, working, and private data tiers;
- why `profile/private/` is gitignored and is not a backup;
- the role of `tools/leak_check.py`;
- that postings and company pages are untrusted data;
- `tools/posting_screen.py`;
- `tools/claude_run.SAFE_ARGS`;
- the fact that headless AI sessions return text while the calling code decides what is written;
- the local server binding to `127.0.0.1` and path containment checks.

Do not imply that privacy protection is absolute. State that users must still protect their machine, backups, terminal history, and external files.

#### Rendering and document verification

Explain the chain from structured data to HTML, PDF, text, and form fields. Mention that Chrome/Edge and `pdftotext` are required for relevant operations. Explain the page-fitting retry behavior and why page count must come from `render.page_count`.

Describe what ATS checks validate, but only list checks verified in the source code.

#### Positioning with bases and threads

Explain:

- professional and service bases, if both exist in the current data model;
- thread dials: `Lead`, `Strong`, `Light`, and `Off`;
- exactly one `Lead` thread;
- why the rule prevents unfocused applications;
- why a bullet without a thread is not rendered.

#### Local web UI

Describe how to start the UI, what it delegates to, its local-only boundary, and the fact that it is not a hosted SaaS application. Mention that the UI should not bypass validation by writing generated documents directly.

#### Testing and reliability

Document the actual test commands from the repository. Distinguish:

- fast unit/regression tests that do not require Chrome;
- smoke or rendering checks that require external executables;
- manual UI verification;
- AI-assisted workflows that require Claude Code.

Do not state a coverage percentage unless the repository already measures one.

#### Trade-offs and known limits

Include only verified limitations, including as applicable:

- keyword matching is not semantic understanding;
- PDF generation requires local browser and poppler tooling;
- AI steps require Claude Code;
- local-only operation improves control but reduces convenience;
- the sample profile is fictional and must not be mistaken for a user's data.

#### Extension guidelines

Explain how a future contributor should add functionality without violating the design:

- keep structured data as the source of truth;
- put reusable logic in a script rather than duplicating it in the web UI;
- preserve privacy and untrusted-input boundaries;
- add a regression test for bug fixes;
- update README and architecture documentation when user-visible behavior changes;
- avoid dependencies unless the project deliberately changes its dependency policy.

End with a short “Further reading” list linking to `CLAUDE.md`, `.github/copilot-instructions.md`, `docs/HOW-IT-WORKS.md`, and `docs/SETUP.md` if those files exist.

---

## 3. Create `CONTRIBUTING.md`

Write a welcoming, practical contribution guide. It must be safe for both a person using JobGenie privately and a developer submitting a public change.

### Required sections

Use these sections:

1. `# Contributing to JobGenie`
2. `## Before you start`
3. `## Development setup`
4. `## Running checks`
5. `## Making a change`
6. `## Data and privacy rules`
7. `## Code conventions`
8. `## Pull requests`
9. `## Scope`
10. `## Reporting a security or privacy issue`

### Requirements

- Link to `CLAUDE.md` and `.github/copilot-instructions.md`.
- State clearly that no real personal data, application data, or `profile/private/` content belongs in an issue, pull request, test fixture, screenshot, or commit.
- Include commands that are verified in the repository. At minimum, inspect and use the correct form of:

```bash
python -m unittest discover tests -v
python render/render.py --check
python tools/smoke_test.py
```

Do not require Chrome for the fast test command if the repository does not require it.

- Explain that Windows users can replace `python3` with `py`, but prefer the command style already used by the repository.
- Explain that `profile/*.json` should be changed through the appropriate project tools where applicable, not by adding personal data to code.
- Require a regression test for every bug fix.
- Require documentation updates for user-visible behavior.
- Describe a useful PR body: problem, approach, tests, manual checks, privacy considerations, and screenshots for UI changes.
- State that generated files under `applications/` should not be hand-edited.
- Keep the scope section aligned with `.github/copilot-instructions.md`: hard rules, scoring policy, and Claude skills are not to be changed casually. Phrase this as review scope, not as an impossible prohibition.
- Security/privacy reports should not include secrets or personal data. Point users toward a private maintainer contact or GitHub's private vulnerability reporting only if that capability is actually enabled; otherwise say to contact the maintainer privately through the repository's available channel.

Do not include a fake contributor covenant, fake support SLA, or invented contact address.

---

## 4. Create `setup.sh`

Create a small, safe onboarding helper for macOS/Linux/WSL.

### Behavioral specification

- Start with `#!/usr/bin/env bash`.
- Use `set -euo pipefail`.
- Resolve the repository directory from the script location, so the script works when invoked from another directory.
- Run the existing doctor command from the repository directory.
- If `profile/` already exists, do not overwrite it. Print a clear message that the existing profile was preserved.
- If `profile/` does not exist, copy `profile.example` to `profile` while preserving directory contents.
- Do not copy or inspect `profile/private/` from a user's existing profile.
- Finish with the exact next steps appropriate to the repository: how to place a CV in `inbox/`, how to run the app, and where to find setup documentation.
- Do not install packages automatically.
- Quote paths safely and fail with a useful error if `profile.example` is missing.
- Use `python3` for commands on Unix-like systems.

### Acceptance checks

The script must:

- be shell-syntax valid;
- be idempotent with respect to an existing `profile/`;
- not delete user files;
- not claim that Claude Code, Chrome, or poppler were installed;
- not launch the server automatically.

After creating it, make it executable in the repository if the available GitHub write operation supports file mode changes. If it does not, mention that the maintainer must run `chmod +x setup.sh` locally.

---

## 5. Create `setup.bat`

Create the Windows equivalent for Command Prompt.

### Behavioral specification

- Use standard batch syntax compatible with modern Windows Command Prompt.
- Resolve and switch to the directory containing the batch file.
- Run `py tools/doctor.py`.
- If `profile` exists, preserve it and print a message.
- Otherwise copy `profile.example` recursively to `profile`.
- Do not delete user files or install packages.
- Print the next steps, including `py web/server.py`, the CV location, and `docs/SETUP.md`.
- Return a nonzero exit code when the doctor command or profile copy fails.
- Avoid Unicode characters that commonly render incorrectly in legacy Windows terminals.

### Acceptance checks

The file must be readable as a batch script, use correct quoting, and accurately describe what it does. Do not claim that the script can configure Claude Code automatically.

---

## 6. Modify `README.md`

Preserve the README's current strengths, screenshots, sample CV, safety claims, and stated limits. Improve discoverability rather than replacing the existing content wholesale.

### Required changes

#### 6.1 Improve the opening

Keep the project title and test badge. Immediately after the opening description, add a short section titled `## Why this is different` or equivalent. It should make the portfolio value obvious in three or four sentences:

- this is not a generic prompt wrapper;
- career facts remain structured and traceable;
- AI-generated output is constrained by the user's data;
- documents are checked before packaging.

Do not duplicate the entire existing “Why it exists” section. Link to it or retain it as the deeper explanation.

#### 6.2 Add a portfolio navigation block

Near the top, add links to:

- the architecture document;
- the setup guide;
- the contributing guide;
- the sample output.

Verify each target exists.

#### 6.3 Improve quick start

Keep the existing dependency statement, but make the two onboarding paths explicit:

- **Try the fictional example profile** — safe for a demo;
- **Create a personal profile** — requires putting the user's own CV in `inbox/` and using Claude Code with `/setup`.

Add the helper commands:

```bash
./setup.sh
# Windows: setup.bat
```

Do not imply that `setup.sh` works on native Windows or that it installs dependencies.

Retain the manual commands because they are useful when the helper is unavailable.

#### 6.4 Add a testing section

Add `## Testing` after quick start or near the limits section. Include only verified commands. Explain the distinction between:

- fast unit/regression tests;
- validation and smoke tests;
- Chrome/poppler-dependent rendering;
- manual UI checks;
- Claude Code-dependent AI steps.

Link to the `tests/` directory if it exists.

#### 6.5 Add a portfolio-oriented “See it” explanation

Before or after the existing screenshots, add two or three sentences explaining what a visitor should notice:

- the score is explainable rather than a mysterious number;
- the build panel exposes the selected positioning and evidence;
- the sample output demonstrates the final artifact.

Do not invent a before/after comparison or claim that a GIF exists.

#### 6.6 Add an architecture link

Near the existing “How it fits together” section, link to `docs/ARCHITECTURE.md` and explain that it covers the safety boundary, rendering pipeline, and UI delegation.

#### 6.7 Add contribution and support links

Near the license section, link to `CONTRIBUTING.md`. Do not add a fake issue template, support email, hosted demo, or roadmap promise.

#### 6.8 Keep limits honest

Retain and, if useful, clarify that:

- AI steps require Claude Code;
- PDF operations require Chrome/Edge and poppler;
- qualification is primarily keyword-based;
- the example profile is fictional;
- the app is local-first, not a hosted service.

Do not claim “works for anyone, anywhere” without the qualifications already present in the repository.

### README quality checks

Before committing:

- no duplicate headings;
- no broken relative links;
- no references to files that were not created;
- no invented coverage percentage;
- no real personal data;
- no claims that the helper scripts install dependencies;
- Markdown remains readable on GitHub.

---

## 7. Documentation consistency pass

After all files are written:

1. Search the repository for the exact commands and filenames mentioned in the new documents.
2. Correct any command that does not match the actual CLI help or existing README instructions.
3. Confirm that `profile.example` exists before documenting it as a source.
4. Confirm that `tools/doctor.py`, `tools/smoke_test.py`, `render/render.py`, and `render/ats_check.py` exist before linking or naming them.
5. Confirm that any claimed web route, output filename, safety check, or test behavior is present in source code.
6. Do not update documentation to hide a failing test. Report the failure and fix only if it is within scope.

---

## 8. Verification commands

Run the following from the repository root, adapting only the Python executable for the operating system:

```bash
python -m unittest discover tests -v
python render/render.py --check
```

Run the smoke test if its documented prerequisites are available:

```bash
python tools/smoke_test.py
```

Validate the shell script where available:

```bash
bash -n setup.sh
```

For Windows, manually inspect or run:

```bat
setup.bat
```

Do not run setup scripts against a user's real profile during development. Use a temporary clone or temporary directory if behavior testing is needed.

---

## 9. Definition of done

This task is complete when:

- `docs/ARCHITECTURE.md` accurately explains the system, data flow, safety boundaries, and trade-offs;
- `CONTRIBUTING.md` gives a new developer safe setup, test, privacy, and PR guidance;
- `setup.sh` and `setup.bat` provide non-destructive onboarding helpers;
- `README.md` makes the portfolio story, architecture, setup, tests, and contribution path easy to find;
- all documentation claims are grounded in the current implementation;
- no new runtime dependency was introduced;
- no private or real personal data was added;
- existing tests remain passing;
- shell and batch scripts do not overwrite an existing `profile/`;
- no core application behavior was changed merely to improve presentation.

At the end of the implementation, provide a concise summary containing:

1. files created or modified;
2. verification commands run and their results;
3. any checks that could not run because Chrome, Edge, poppler, Claude Code, or a platform shell was unavailable;
4. any discrepancy discovered between existing code and the requested documentation.
