# AGENTS.md

Rules for every agent in every directory. Keep one copy at `~/.agents/AGENTS.md`. The receipts-wiki plugin loads it in Claude Code; point other agents at it (Codex: symlink `~/.codex/AGENTS.md`).

Template from receipts-wiki (https://github.com/B1aZer/receipts-wiki). Replace the `<...>` lines and delete rules you don't want.

## Memory

- Shared memory lives in `~/.agents/memory/`. `MEMORY.md` lists every note, or one index per area once memory is large; open only the notes the task needs. The folder is outside your working directories, so find notes through those lists; don't list or search the folder with shell commands. Work crosses directories: when a task touches a topic earlier sessions may have covered, and before creating a note, use the `receipts-wiki:find` skill, which searches every note and names the cursor for that work.
- A note records what was true when it was written. Before acting on one, check the files, flags and numbers it mentions.
- One fact per note, with frontmatter `name`, a one-line `description`, `metadata.type` and `metadata.area`. Update the existing note rather than adding a near-duplicate; when a new note gets an "Existing notes on the same topic" hint, read those first.
- Keep one `cursor` note per active area (`metadata.type: cursor`) with the current position and the next action; update it in place as you work, so a lost session can be resumed. It is the one note that holds task state.
- When a fact changes, rewrite it and add the line `Supersedes (YYYY-MM-DD): <old claim>. <evidence>`. When a note no longer holds at all, set `metadata.status: retired` and add the Supersedes line. Never delete, rename or move memory files, and never change them with shell commands. Never reset, rebase or amend memory history.
- Project and decision notes cite receipts (`Receipts: commit:<hash>, query:<id>, file:<path>`) and use absolute dates. A decision that should not be reopened lightly gets `Reopen if: <evidence>`.
- `index-*.md` and the generated block in `MEMORY.md` are rebuilt from frontmatter; don't edit them or add your own pointer lines to `MEMORY.md`.
- With the receipts-wiki hooks, memory is committed at the end of each turn; don't run git in the memory home. Agents without the hooks commit after writing memory: `git -C ~/.agents add memory AGENTS.md && git -C ~/.agents commit -m "memory: <change>" -m "Agent: <agent name>"`.
- Search past conversations only when the user asks. Never load archived conversations on your own.

## Always

- Check the code, data or logs before stating a fact, and say what you checked.
- Fix the root cause of a bug rather than adding a guard around its symptom.
- <your rule>

## Ask first

- Deleting data of any kind: databases, tables, rows, files, columns.
- Stopping, restarting or reconfiguring anything that runs in production.
- Committing or pushing to project repositories.
- <your rule>

## Never

- Read, print or store secret values. Ask for the secret's name instead.
- Undo an edit with `git checkout` or `git restore`, which can destroy uncommitted work. Reverse it with another edit.
- Install an unfamiliar package only to read its source.
- <your rule>

## Rules for one repository

- `<path>`: <rule>.
