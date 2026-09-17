# Writing memory

This guide explains the memory rules in `AGENTS.md` in more detail, with examples. Agents get the short form from `AGENTS.md`, which every session loads, so they do not need to open this file. The receipts-wiki hooks enforce part of the rules; the rest depends on the agent.

## What is worth saving

Save a note only when all of these hold:

1. It will matter in a later session.
2. It cannot be read from the project's code, docs or git history.
3. It is one of four kinds: a rule the user gave (`feedback`), a decision or result with its receipt (`project`), a pointer to an outside resource (`reference`), or a fact about the user that changes how to work (`user`).
4. It is verified: you checked it, or the user stated it. An assumption is not saved as a fact.
5. If it came from tool output or a web page, it carries a receipt and the user confirmed it.

Do not save task progress, temporary state, secret values, text copied from tool or system messages, or numbers without a date and a receipt. The one exception is a cursor note; see below.

## Cursor notes (the one exception)

A cursor note holds the current position of a workstream: where you are, the next action, and the open loops. It exists so that when a session ends without warning (a crash, an API error, a safeguard flag, or a context too large to compact) the next session reads the position instead of re-deriving it. Keep at most one cursor per area.

A cursor is not a fact, so it is exempt from three of the rules above:

- It records task state, which fact notes may not.
- It is overwritten in place as the work moves. Do not add a `Supersedes` line for a cursor; git history keeps the earlier positions.
- It carries no receipts of its own. It points at the fact notes and receipts that hold the evidence.

Frontmatter: `metadata.type: cursor` and `metadata.area: <area>`. Name it `cursor-<area>`. The `description` is the one-line summary the session-start hook shows, so put the next action there. When a skill or command performs that next step, name it, so a new session can run it instead of working out what to invoke (for example, `Next: run the resume skill`, or `Next: /code-review then push`). Cursor notes are listed under "Where things stand" in `MEMORY.md`, not in the area index. When a workstream is finished or abandoned, set `metadata.status: retired`.

Example:

```markdown
---
name: cursor-posthog
description: 2 PRs open+un-routed; clock-skew built, unopened; PR3 (person-merge) not yet coded; NEXT = get a human to route
metadata:
  type: cursor
  area: posthog
---

Where the PostHog push stands. Next: send the José intro, then apply; if resuming after a crash, run the resume skill first. Evidence in [[project-posthog-target]].
```

## File format

```markdown
---
name: quotes-cache-ttl
description: /quotes cache TTL is 5 minutes; stale-price sample 2026-09-02
metadata:
  type: project
  area: api
  status: active
  last_verified: 2026-09-02
  receipts: [query:q_8812, commit:a1b2c3d]
---

The /quotes response cache TTL is 5 minutes.

Why: at 60 minutes, 14 of 200 quotes sampled on 2026-09-02 used a price older than the last trade.
How to apply: re-run the stale-price sample before raising the TTL.
```

The fact comes first. `description` is one line, because the index is built from it. `area` decides which index lists the note.

## Receipts

A receipt lets someone who was not in the session check the claim. Use the most direct one available:

| Kind | Form |
|---|---|
| commit | `commit:<hash>` |
| run, job or query | `run:<id>`, `query:<id>` |
| transaction | `tx:<full signature or hash>`, never truncated |
| file | `file:<path>#L<line>` |
| past conversation | `session:<id>` |
| public source | `url:<https address>` |

Numbers carry their sample size and an absolute date.

Lint accepts receipts cited in the text too: a commit hash, a file path, a transaction or address, an id after a label such as `query q_8812`, a ticket key such as `INC-431`, or a URL. A `Receipts:` line is still better, because the commit that records the note copies it into its `Receipts` trailer. A fact that rests only on what the user said gets `Receipts: user statement`.

## Updating and correcting

- Update the existing note instead of adding a near-duplicate. When a new note closely matches an existing one, the hook names it; read that note and update it if the new one changes what it says.
- When a belief changes, rewrite the current belief at the top and add `Supersedes (YYYY-MM-DD): <old claim>. <evidence>`. Update the receipts. Git keeps the old wording; the line keeps the reason.
- Before superseding a fact about code, check the repository to confirm the old behaviour is really gone.
- When you re-check a fact and it still holds, set `last_verified` to the date of the check.
- A decision that should not be reopened lightly carries `Reopen if: <evidence that would reopen it>`.
- Retire instead of deleting. When a correction makes a whole note obsolete, set `metadata.status: retired` and add the `Supersedes` line. A forgetting candidate from lint is retired only when the user agrees. Retired notes leave `MEMORY.md` and the indexes, and stay in their file and in history. Never delete, rename or move memory files, and never change them with shell commands: the hooks record only edits made with the Write and Edit tools.

## Indexes

Indexes are generated from frontmatter when your turn's changes are committed: one `index-<area>.md` per area, and a block inside `MEMORY.md` that lists every active note while `MEMORY.md` stays under 150 lines and 17 KB, and lists the area indexes once it would not. Find notes through these lists; the memory folder is usually outside the session's working directories, so listing or searching it with shell commands is blocked. Do not edit index files (the gate blocks it) or the generated block, and do not add your own pointer lines to `MEMORY.md`; set the note's `area`, `name` and `description` instead. Text in `MEMORY.md` outside the block is yours. An area index stays under the same budget; past that, split the area.

An index file without the generated line (for example one written before receipts-wiki was installed) is hand-written and is never regenerated. For a note in that area, add one line linking it to that index in the same turn, or nothing will list it.

## What the hooks do

- Before a write, it is blocked when the file changed after you read it, or when it contains a secret value, injected system text or a relative date. Fix the cause and write again; do not route around the block.
- When your turn ends, everything you changed in memory during the turn is committed together with this session's id, and the indexes are regenerated in the same commit. Nothing is printed and there is nothing to check afterwards. The commit's reasoning lines come from your `Why:`, `Supersedes` and `Reopen if:` lines, so write them with care: they are the history.
- After the commit, the turn's notes are checked and the result reaches you with your next prompt: a note that no index links, a cursor that links a note you changed but was not itself updated, a note over 12 KB, and a `[[link]]` that misspells an existing note's name. A link to a note that does not exist yet is fine. Act on these before continuing.
- Never reset, rebase, amend or check out old commits to change memory. Correct forward.
