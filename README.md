# Evidence-Bound Job Application System

[![tests](https://github.com/ProsePixie/evidence-bound-job-application-system/actions/workflows/tests.yml/badge.svg)](https://github.com/ProsePixie/evidence-bound-job-application-system/actions/workflows/tests.yml)

A local job-search system run with [Claude Code](https://claude.com/claude-code). You keep
your career as structured data. This project finds and screens postings, says how qualified you
are for each one, builds a tailored CV and cover letter, checks them the way an applicant
tracking system reads them, and packages what you send. It will not invent a single claim.

Built during a real job search, for one: every feature exists because an application
went wrong without it.

> Status: complete and tested, and runs for anyone, anywhere: guided onboarding from your
> own CV (`/setup`), scoring, building, checking and packaging. See the [ROADMAP](ROADMAP.md).

![Pipeline board](docs/img/pipeline.png)

## Why it exists

Most "AI CV" tools rewrite you until you sound like the posting. That gets interviews you
cannot survive. This project is built the other way round:

1. **Nothing is invented.** Every line on a CV or letter traces to your own data or to
   something you confirmed. A requirement you do not meet is left out or stated plainly,
   never papered over. Every change to your data is recorded with its source.
2. **One angle per application.** A CV is built from a base (professional or service) and
   *threads* - your positioning tracks, such as enablement or AI - dialed Lead, Strong,
   Light or Off. Exactly one leads.
3. **Postings are untrusted.** Every posting is screened for hidden text aimed at AI
   ("ignore previous instructions...") before anything reads it. AI sessions run with no
   file-write, web or private-data access; the calling script decides what is saved.
4. **Private stays private.** `profile/private/` (salary history, references) never enters
   a prompt. A leak check scans every package before it can be sent.

## Who this is for

Built for people in the EU or the Americas applying to roles in English. Output - CV,
letter, form answers - always stays in the language(s) you set in `profile/market.json`
(English by default); this project does not translate your CV into the employer's language,
and does not assume you need it to.

If you run into a posting in a language you don't read, you have two options: ask your
own Claude Code session to translate it before you run `/fit` on the result, or use the
"Translate to English" button on the app's Screen tab, which screens the original text
for anything addressed to an AI before translating it (see `CLAUDE.md` hard rule 3).
Either way, nothing here was built to localize your *application* - only to help you
read a posting that isn't in your language before deciding what to do about it.

## What it does

| | |
|---|---|
| **Pipeline board** | Every opportunity as a card, found to interviewing, all on one screen; finished CVs move to Drafted on their own; closed ones go to a one-line Archive kept for learning; a readable log of what the app did |
| **Qualification score** | 0-100 per posting, computed in the background for every card (postings are fetched from each card's link), every point explained: requirements covered, in your data, or a gap |
| **Build panel** | Suggested base and threads with reasons, every bullet tickable, live preview, requirement coverage |
| **Checks** | Text layer, page count, chronology, substance, banned phrases, unsupported claims |
| **Letters** | Drafted by Claude from what your data supports, then checked the same way |
| **Package** | Separate named files (`Jane_Doe_CV.pdf`, `Jane_Doe_Cover_Letter.pdf`), refused if any check fails; one merged PDF on request for single-upload portals |
| **Scout** | Polls company job boards (Greenhouse, Lever, Ashby and others) for matching roles |
| **Skills** | `/fit`, `/apply`, `/scout`, `/warm`, `/prep`, `/outcome`, `/evidence` inside Claude Code |

## See it

Every posting gets a score with its reasons, including the gaps:

![Score breakdown](docs/img/score.png)

The Build panel: threads dialed Lead to Off, each requirement marked covered or a gap, every bullet tickable, a live preview.

![Build panel](docs/img/build.png)

A sample output, built from the fictional example profile: [Jane_Doe_CV.pdf](docs/sample/Jane_Doe_CV.pdf)

<img src="docs/img/sample-cv-1.png" width="420" alt="Sample CV, page 1">

And a readable log of everything the app did:

![Log](docs/img/log.png)

## Quick start

Needs Python 3.10+, Chrome or Edge, and poppler (`pdftotext`; `pdfunite` only for a merged PDF). No pip installs.

```bash
git clone https://github.com/ProsePixie/evidence-bound-job-application-system && cd evidence-bound-job-application-system
python3 tools/doctor.py                # checks Chrome, poppler and Python, says how to fix
cp -r profile.example profile          # the fictional Jane Doe, to try it
python3 web/server.py                  # opens the app at http://127.0.0.1:8777
```

Then make it yours: put your CV (PDF or DOCX) in `inbox/`, open the folder in Claude Code
and run **`/setup`**. It proposes each fact from your CV and writes only what you confirm.
(On Windows, use `py` instead of `python3`.) Full guide:
[docs/SETUP.md](docs/SETUP.md).

## How it fits together

```
profile/career.json  ─┐                         ┌─> cv.pdf / cv.txt / cv.fields.json
profile/threads.json ─┼─> render/cv_builder.py ─┤
posting.txt ──screen──┘      (base + dials)     └─> render/ats_check.py ──> tools/package.py
     │
     └─> tools/qualify.py (score)   tools/draft_letter.py (Claude, sandboxed) ─> render/letter.py
web/server.py: local UI over all of it (127.0.0.1 only, stdlib only)
```

`CLAUDE.md` holds the rules every Claude Code session follows in this repo.
**[How it works, and why it is built this way](docs/HOW-IT-WORKS.md)** explains the design decisions.

## Limits, stated plainly

- The AI steps (letter drafting, fit analysis, `/setup`) need Claude Code on your machine.
  Building, checking, scoring and packaging do not.
- PDFs need Chrome or Edge and poppler.
- The score matches words, not meaning: it is reliable for spotting gaps and what a CV
  leaves out, less so on short or generic postings. Every line of it is shown so you can judge.
- Output is in English (or whichever languages you set in `cv_languages`) - see "Who this
  is for" above. A second output language is possible; German is the worked example.

## License

MIT, see [LICENSE](LICENSE).

## Credits

The drafter/reviewer split, grounding audit, backtrack test and ATS text-layer check borrow
from [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) (MIT).
