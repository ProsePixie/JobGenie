# Changelog

## Ported from the working system, 20/10/2026

Changes made while using the app for a real job search, with their tests.

**Safety**
- Letters may not say the candidate lacks something unless it is listed under `confirmed_gaps` in `career.json`. `claim_check` fails any other statement of a lack, the drafting prompt says to leave unknowns unsaid, and requirements the data merely does not mention show as "not in your data" instead of "gap".

**Windows**
- Every program the app starts runs without a console window. Before, each child process opened a command window, and checking the sign-in on window focus made each window take focus and trigger the next check.
- When the Claude sign-in has lapsed, summaries, translations, letter drafts and fit analyses say so in plain words. The app checks `claude auth status` on load and every ten minutes and shows a banner.

**Build panel**
- The **Add** button pins bullets, skill groups and certifications, ranks candidates by how rare the matched words are in your data, and leaves out what the CV already shows.
- Fixed a duplicate element id (`bflash`) that sent every Build panel message to a hidden element.
- Package builds a CV that was saved but never finalized instead of refusing.

**CV builder**
- A role's optional `context` line prints under its title on English CVs, behind a Build panel switch.
- A role can belong to one CV base (`only_base`), set its own bullet count (`bullet_cap`), and is skipped by the chronology check when it is base-specific.

**Dashboard and watcher**
- New card "Where your applications go": a Sankey of sent applications and what came back, counted from your pipeline each time, with a whole-pipeline view. Every flow out of a box adds up to the box.
- A place named right after "remote" ("Remote-Jakarta") counts as where the role sits and is rejected for non-US markets.
- "Nothing new that fits" now says nothing is new since the last check and offers the latest recorded roles that have no card.

`profile.example` documents the new optional fields. The committed `JobGenie.zip` was removed: it went out of date with every change; clone the repository instead.
