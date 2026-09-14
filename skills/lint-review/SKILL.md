---
name: lint-review
description: Reviews receipts-wiki memory with the user, covering problems, forgetting candidates and lesson proposals, and applies only the changes the user approves. Use when the user asks to check, clean up or review memory, or after a session start mentions pending lesson proposals.
disable-model-invocation: true
license: MIT
---

# Review memory with the user

Change nothing before the user approves that specific change. Never print a secret value. Make every edit with the normal Write and Edit tools so the receipts-wiki hooks record it.

`<plugin>` is two directories above this skill's base directory. If `<plugin>/scripts/rw.py` does not exist, tell the user to install the receipts-wiki plugin and stop.

1. Run `python3 <plugin>/scripts/rw.py lint` and show the report.
2. Problems first. For each one, propose the smallest fix and wait for an answer.
   - A secret value in a note: propose replacing it with the secret's name or location. After the edit, tell the user the value is still in git history and that removing it there needs a history rewrite, which they must approve separately.
   - Missing `.gitignore` entries, broken links, missing frontmatter: propose the exact edit.
3. Forgetting candidates. For each note, read it and say why it is listed, then offer three choices: keep it (re-check the fact, then set `last_verified` to the date of the check), retire it (`status: retired`), or leave it for later.
4. Lesson proposals. For each quoted message, read the surrounding conversation in the archive if needed. Then either draft a `feedback` note following `<plugin>/templates/WRITING.md`, with the rule, a `Why:` line, a `How to apply:` line, `source: proposal` under `metadata`, and the receipt `session:<id>#L<line>`, or propose discarding the proposal. Write the note only after approval. When every candidate in a proposal file is handled, ask before deleting that file.
5. Warnings: summarise them, and propose fixes only for the ones the user wants to address.
6. Run lint again and report what changed.
