#!/usr/bin/env python3
"""One screen for every posting that enters the system (CLAUDE.md hard rule 3).

A posting arrives four ways: fetched from its link, pasted into Prepare or the
Screen tab, captured by the bookmarklet, or attached from the capture inbox.
Only the fetch path was screened, and its pattern refused any posting that
mentioned ChatGPT, Claude or an "AI assistant" - which is most of the AI
enablement roles this search exists to find - while pasted and captured text
reached the letter drafter unscreened.

What is flagged is text addressed to an AI, not text about AI:

    "Ignore all previous instructions ..."        flagged
    "If you are an AI, include the word ..."       flagged
    "Train teams to use ChatGPT and Claude"        not flagged

Invisible characters are handled too. Unicode tag characters (U+E0000-E007F)
render as nothing but spell out ASCII to a model, so they are decoded and
flagged; zero-width and bidi control characters are removed.

    python3 tools/posting_screen.py saved-posting.txt
"""

import re
import sys

TAG_CHARS = re.compile("[\U000e0000-\U000e007f]+")
INVISIBLE = re.compile("[​‌‍⁠﻿‪-‮⁦-⁩]")

ADDRESSED = re.compile("|".join("(?:%s)" % p for p in [
    r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|"
    r"preceding|your)\s+(?:instructions|prompts?|directions|rules)",
    r"\b(?:if|when)\s+you\s+are\s+an?\s+(?:ai|a\.i\.|llm|language\s+model|large\s+language\s+model|"
    r"chat\s?bot|assistant|automated\s+(?:system|agent|tool))\b",
    r"\b(?:dear|attention|note\s+to|message\s+(?:for|to)|instructions?\s+(?:for|to))\s+"
    r"(?:the\s+)?(?:ai|llm|language\s+models?|chatgpt|claude|gpt|assistants?|automated\s+\w+)\b",
    r"\b(?:ai|llm|language\s+model)s?\s+(?:reading|processing|parsing|reviewing|screening)\s+this\b",
    r"\bsystem\s+prompt\b",
    r"\bhidden\s+instructions?\b",
    r"\b(?:include|mention|use|insert|add)\s+the\s+(?:word|phrase|term|code\s*word|keyword)\s+[\"'“]",
    r"\byou\s+(?:must|should)\s+(?:now\s+)?(?:respond|reply|answer|output)\b",
    r"\bprompt\s+injection\b",
    # German, since half the postings are.
    r"\bignorier(?:e|en)?\s+(?:alle\s+)?(?:vorherigen|bisherigen)\s+(?:anweisungen|instruktionen)",
    r"\bwenn\s+du\s+eine?\s+(?:ki|künstliche\s+intelligenz|sprachmodell)\s+bist\b",
]), re.I)


def screen(text):
    """(clean_text, flagged_passage_or_None).

    clean_text has invisible characters removed. The flagged passage is the
    first text addressed to an AI, with some context, for a person to read;
    None when the posting is clean.
    """
    text = text or ""
    smuggled = [
        "".join(chr(ord(c) - 0xE0000) for c in m.group(0) if 0x20 <= ord(c) - 0xE0000 < 0x7F)
        for m in TAG_CHARS.finditer(text)]
    clean = INVISIBLE.sub("", TAG_CHARS.sub("", text))
    if smuggled:
        return clean, "invisible characters spelling: %r" % " ".join(smuggled)[:200]
    m = ADDRESSED.search(clean)
    if m:
        return clean, " ".join(clean[max(0, m.start() - 80):m.end() + 80].split())
    return clean, None


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: posting_screen.py <file>")
    with open(sys.argv[1], encoding="utf-8-sig", errors="replace") as fh:
        _, flagged = screen(fh.read())
    if flagged:
        print("FLAGGED: text addressed to an AI. Read it before using this posting:\n\n    %s"
              % flagged)
        return 2
    print("clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
