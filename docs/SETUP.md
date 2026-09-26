# Setting up JobGenie

## 1. Install the tools

Commands below use `python3`; on Windows type `py` instead. Then run
`python3 tools/doctor.py`: it checks everything in this table and says how to fix what is missing.

| Tool | Windows | macOS | Linux |
|---|---|---|---|
| Python 3.10+ | python.org (use `py`) | `brew install python` | distro package |
| Chrome or Edge | usually present | usually present | `chromium` |
| poppler (`pdftotext`, `pdfunite`) | ships with Git for Windows | `brew install poppler` | `poppler-utils` |
| Claude Code | [claude.com/claude-code](https://claude.com/claude-code) | same | same |

Set `CHROME_PATH` if Chrome is somewhere unusual. `python3 render/render.py --check` reports
what it found.

## 2. Try it with the example candidate

```bash
cp -r profile.example profile
python3 web/server.py
```

## 3. Make it yours: `/setup`

Open the folder in Claude Code and type `/setup`. It will:

1. Ask you to put your CV (PDF or DOCX) and, if you have it, your LinkedIn data export
   into `inbox/`.
2. Propose each role, date and achievement it finds, **one at a time, for you to confirm
   or correct**. Nothing enters your data unconfirmed. Confirmed facts are written with
   `tools/careerdata.py`, which records where each came from in `profile/sources.jsonl`.
3. Suggest 3-5 threads (positioning tracks) from your history, with target titles and
   vocabulary, for you to edit.
4. Ask where and how you can work, and write `profile/market.json`: home places and
   country, regions that include you (for example "north america" or "emea"), the
   languages you write CVs in, and any language you hold only partly. The job-board
   watcher, the screen and the CV builder all read it, so the app works wherever you are.
5. Create `profile/private/` and a `leak-terms.txt` for anything that must never appear in
   a sent document.

## 4. Daily use

- **Pipeline** tab: add a job (paste the posting), see its score, **Build CV**, draft the
  letter, **Package**, mark it sent.
- **Log** tab: what the app did, and why anything failed.
- In Claude Code: `/fit` for a judgement on a posting, `/apply` for a full package,
  `/prep` before an interview, `/outcome` when you hear back.

## Your data stays local

`profile/`, `applications/`, `data/` and `documents/` are gitignored in this repository.
If you keep your own fork, keep it private, or leave them ignored.
