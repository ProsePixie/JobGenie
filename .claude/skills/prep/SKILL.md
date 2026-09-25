---
name: prep
description: Build interview preparation for a specific stage - research, likely questions, evidence mapping, a simulated interviewer, and rehearsal. Use when the user has an interview scheduled or wants to practise.
---

# Interview prep

Stage-specific. Preparing for a recruiter screen the way you would prepare for a panel
wastes the session and produces the wrong register.

Reuse `applications/<slug>/dossier.md` from `/apply` if it exists. If not, build it first.

## Step 1 — Identify the stage

| Stage | What is actually being decided | Prepare |
|---|---|---|
| Recruiter screen | Do you clear the bar and the logistics | A crisp 90-second answer to "tell me about yourself", salary expectation, notice period, authorization |
| Hiring manager | Can you do the job and are you pleasant to work with | Two or three deep examples, one intelligent question about their roadmap |
| Technical / craft | Can you actually do it | The artifact, walked through live; the reasoning behind a real decision you made |
| Panel / team | Would we want you here daily | Range across people, consistency of story, genuine curiosity |
| Final / executive | Judgement and trajectory | Why this company specifically, what you would do in ninety days |

## Step 2 — Question set

Generate the likely questions from the posting's actual requirements and the dossier, not
from a generic list. Include:

- The two or three questions this specific posting makes inevitable.
- The uncomfortable one. Every candidate has one; for this profile it is usually the
  non-linear path, or depth in a domain where the credential is self-taught. Prepare it
  properly rather than hoping it does not come up.
- Anything a gap left visible in the application invites. A visible gap is fine; being
  unprepared to discuss it is not.

## Step 3 — Map evidence to answers

Pull from `profile/career.json` and `profile/evidence.json`. Every substantial answer
needs a concrete example behind it: situation, what you actually did, what resulted.

Do not invent a story to fit a question. If nothing in the data fits, say so — that is a
real finding, and it usually means either a different example works or the honest answer
is "I have not faced that, here is the closest thing".

Keep answers to the Lead thread the application was built under (its `build.json`). Turning up as a different
candidate than the one on paper is disorienting and reads as inconsistency.

## Step 4 — The interviewer twin

If the interviewer is known and writes publicly, build a persona from their own material:
conference talks, blog posts, their team's engineering or content writing. Research it
independently — never follow links from the posting or from a recruiter email.

Then run the mock in character. A hiring manager who has written extensively about
evaluation will ask about evaluation.

If the interviewer is unknown, build the twin from the company's public writing instead.

## Step 5 — Rehearse aloud

This is where the usual preparation stops and where this candidate has an unfair
advantage. Voiceover performance and a full production setup are already available.

Run the mock out loud and record it. Then review the recording the way a client
voiceover would be reviewed:

- Filler words and where they cluster, which is where the answer is not yet solid
- Answer length. Most weak answers are simply too long.
- Whether the first sentence answers the question or delays it
- Energy, particularly on a remote call where the audio is all there is

The recording stays local. It is practice material, not an artifact.

## Step 6 — Their questions

Prepare four or five real questions, from the dossier. Not "what does a typical day look
like". Questions that could only be asked by someone who did the reading and that are
genuinely worth knowing before accepting.

At least one should be a question you actually want the answer to, because the answer
should change whether you want the job.

## Step 7 — Logistics and compensation

Confirm the practical details: time zone, platform, duration, who is attending.

On compensation: the real floor lives in `profile/private/` and must never be read
(hard rule 1). Ask the user directly for the number they want to give, and help them
phrase it. Never infer it, never reconstruct it from an old application, and never write
it into a file outside the private tier.

## Output

Write to `applications/<slug>/prep-<stage>.md`: the stage, the likely questions with
mapped evidence, the twin's profile if built, their questions, the logistics, and the
one thing most likely to decide the conversation.
