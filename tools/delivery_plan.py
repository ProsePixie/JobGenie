#!/usr/bin/env python3
"""Build a timed run sheet for a live training session, with the audience
responsiveness scripted into it rather than left to improvisation.

Written after a live training casting where the feedback was
"great trainer, excellent knowledge, perfect presentation, did not respond to
the audience enough". That is a delivery mechanic, not a knowledge gap, and the
fix is not to hope to improvise better on the day. It is to prepare the
interaction the same way the content is prepared.

What reads to an audience as responsiveness is almost entirely mechanical:

    ask early, then use the answer out loud by name
    say what you can see happening in the room
    stop at planned moments and invite the objection
    visibly drop something you had prepared, because of what someone said
    close by returning to the first thing anyone told you

All five can be written down in advance. That is the whole idea.

Standard library only.

    python3 tools/delivery_plan.py --minutes 14 --intro 30
    python3 tools/delivery_plan.py --minutes 90 --topic "Prompting for ops teams"
    python3 tools/delivery_plan.py --minutes 45 --virtual
    python3 tools/delivery_plan.py --rehearse
"""

import argparse
import sys


def clock(seconds):
    return "%d:%02d" % (seconds // 60, seconds % 60)


def checkpoint_count(minutes):
    """How many scheduled stops a session of this length can carry.

    Below roughly seven minutes there is no room for one without wrecking the
    content. Above that, one per eight minutes is frequent enough to feel
    responsive and rare enough not to feel like a survey.
    """
    if minutes < 7:
        return 0
    return max(1, min(6, int(minutes // 8)))


def build(minutes, intro_seconds, virtual, topic):
    total = int(minutes * 60)
    beats = []

    subject = topic or "the subject"
    hands = "type one word in the chat" if virtual else "show of hands"
    seen = ("watch the gallery and name what you see, even if it is only two people"
            if virtual else "name what you can see in the room")

    beats.append((0, "Open", [
        "%d seconds. Who you are, why you are the person to hear this from, what they"
        " will be able to do at the end." % intro_seconds,
        "No agenda slide. Nobody has ever been glad of an agenda slide.",
    ], "The intro is the only part where talking at them is correct."))

    # The opening question is the load-bearing beat. Everything later refers back.
    ask_at = min(intro_seconds + 20, int(total * 0.12))
    beats.append((ask_at, "Ask", [
        "One question with a cheap answer, %s." % hands,
        "Cheap means answerable in one word without thinking. \"Who has already tried"
        " %s and given up?\" beats \"What are your goals today?\"" % subject,
        "Get two or three names as they answer. Write them down. You will need them.",
    ], "Asking inside the first fifth is what separates a session from a broadcast."))

    use_at = min(ask_at + 90, int(total * 0.25))
    beats.append((use_at, "Use it", [
        "Refer to an answer out loud, by name. \"Sabine said onboarding, so let me"
        " start there rather than where I was going to.\"",
        "This is the single highest-value line in the whole session.",
    ], "Collecting answers and not using them reads as worse than never asking."))

    n = checkpoint_count(minutes)
    stops = []
    if n:
        # Spread across the working middle. Anchoring the first one at a third
        # of the way in left a ninety minute session with a silent half hour at
        # the start, which is exactly the stretch where a room decides whether
        # it is being talked at.
        lo, hi = 0.18, 0.88
        for i in range(n):
            frac = lo + (hi - lo) * (i / (n - 1) if n > 1 else 0.5)
            at = int(total * frac)
            stops.append(at)
            beats.append((at, "Checkpoint %d" % (i + 1), [
                "Stop. \"What is the objection forming right now?\"",
                "Then count to five in your head before saying anything else.",
                seen + ".",
            ], "The silence is the technique. Filling it is what reads as not listening."))

    # One prepared segment, marked droppable, abandoned in view of the audience.
    # Kept clear of the checkpoints: in a fourteen minute session the two landed
    # seventeen seconds apart, which is one interruption, not two techniques.
    drop_at = int(total * 0.55)
    gap = max(60, int(total * 0.08))
    while any(abs(drop_at - s) < gap for s in stops) and drop_at < total * 0.75:
        drop_at += gap
    beats.append((drop_at, "Drop something", [
        "Abandon a prepared segment out loud, because of something that was said.",
        "\"I had a section on governance. Nobody here owns governance, so I am"
        " skipping it and giving you the time back.\"",
        "Mark the droppable segment in your notes before you start. You cannot"
        " improvise this convincingly; you can only prepare it.",
    ], "Visibly changing plan is the strongest available proof of listening."))

    close_at = max(0, total - min(90, int(total * 0.1)))
    beats.append((close_at, "Callback and close", [
        "Return to the first answer anyone gave you. Use the name again.",
        "\"Sabine, you said onboarding. Here is the one thing to try on Monday.\"",
        "One action, not a summary. Then stop talking.",
    ], "The loop closing is what people remember as engagement."))

    beats.append((total, "End", ["Finish early rather than late. Always."],
                  "Overrunning a timed casting is the one unrecoverable error."))
    # Built in logical order, delivered in clock order. Without this the drop
    # printed after the last checkpoint it precedes.
    beats.sort(key=lambda b: b[0])
    return beats


REHEARSAL = [
    ("Before", "Is the droppable segment marked in the notes?"),
    ("Before", "Is the opening question answerable in one word?"),
    ("Before", "Is there somewhere to write down two or three names?"),
    ("Before", "Has the whole thing been run once against a clock, out loud?"),
    ("During", "Did a name get used out loud in the first quarter?"),
    ("During", "Did the count of five happen after at least one question?"),
    ("During", "Was something visibly dropped?"),
    ("During", "Was anything observed out loud about the room?"),
    ("After", "Did the close return to the first answer given?"),
    ("After", "Did it end early?"),
]


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=14,
                    help="session length in minutes (default 14, the casting length)")
    ap.add_argument("--intro", type=int, default=30,
                    help="seconds allowed for the intro (default 30)")
    ap.add_argument("--topic", default="", help="subject, used in the example lines")
    ap.add_argument("--virtual", action="store_true",
                    help="remote delivery: adapts the cues to a gallery and a chat box")
    ap.add_argument("--rehearse", action="store_true",
                    help="print only the rehearsal checklist")
    args = ap.parse_args()

    if args.rehearse:
        print("Rehearsal checklist\n")
        for when, item in REHEARSAL:
            print("  %-7s %s" % (when, item))
        return 0

    head = "%.0f minute session" % args.minutes
    if args.topic:
        head += ": %s" % args.topic
    if args.virtual:
        head += "  (virtual)"
    print(head)
    print("=" * len(head))
    print()

    for at, label, lines, why in build(args.minutes, args.intro, args.virtual, args.topic):
        print("%-6s %s" % (clock(at), label.upper()))
        for line in lines:
            print("       %s" % line)
        print("       why: %s" % why)
        print()

    n = checkpoint_count(args.minutes)
    if not n:
        print("No checkpoints: under seven minutes there is no room for one without")
        print("costing more content than the responsiveness is worth. The opening")
        print("question and the callback carry it instead.")
        print()
    print("Rehearse against: python3 tools/delivery_plan.py --rehearse")
    return 0


if __name__ == "__main__":
    sys.exit(main())
