---
name: lint-review
description: Reviews receipts-wiki memory with the user, covering problems, warnings and forgetting candidates, and applies only the changes the user approves. Use when the user asks to check, clean up or review memory.
disable-model-invocation: true
license: MIT
---

# Review memory with the user

Change nothing before the user approves that specific change. Never print a secret value. Make every edit with the normal Write and Edit tools so the receipts-wiki hooks check and record it.

`<plugin>` is two directories above this skill's base directory. If `<plugin>/scripts/rw.py` does not exist, tell the user to install the receipts-wiki plugin and stop.

1. Run `python3 <plugin>/scripts/rw.py lint` and show the report.
2. Problems first. For each one, propose the smallest fix and wait for an answer.
   - A secret value in a note: propose replacing it with the secret's name or location. After the edit, tell the user the value is still in git history and that removing it there needs a history rewrite, which they must approve separately.
   - A failed commit: show git's error and propose the fix (for example, finishing a merge or making the signing key available).
   - Missing `.gitignore` entries, broken links, missing frontmatter: propose the exact edit.
3. Forgetting candidates. For each note, read it and say why it is listed, then offer three choices: keep it (re-check the fact, then set `last_verified` to the date of the check), retire it (`metadata.status: retired` plus a `Supersedes` line), or leave it for later.
4. Warnings: summarise them, and propose fixes only for the ones the user wants to address.
5. Run lint again and report what changed.
