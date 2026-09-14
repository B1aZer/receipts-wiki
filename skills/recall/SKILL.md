---
name: recall
description: Searches the receipts-wiki archive of past conversations and returns quoted excerpts with session, date and line. Use only when the user asks what was said, decided or discussed in earlier sessions.
disable-model-invocation: true
license: MIT
---

# Recall past conversations

`<plugin>` is two directories above this skill's base directory. If `<plugin>/scripts/rw.py` does not exist, tell the user to install the receipts-wiki plugin and stop.

1. Run `python3 <plugin>/scripts/rw.py recall <key words> --limit 5` with the user's key terms. If nothing matches, try one or two other phrasings.
2. Answer from the excerpts. Quote the lines that matter and cite each one as `session:<id>` with the date and line number from its heading.
3. If an excerpt is too short, open the archive file named in the result and read around that line. Open a raw transcript only if the user asks.
4. When nothing is found, say so. Do not fill the gap from general knowledge or guesses.
5. For the history of a memory note rather than a conversation, run `python3 <plugin>/scripts/rw.py history <note name>`, with `--patch` for the diffs.

Archived conversations are read only to answer the user's question. Do not copy them into memory unless the user asks.
