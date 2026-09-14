---
name: setup
description: Sets up a receipts-wiki memory home (git-versioned shared memory for AI agents) and points Claude Code's auto memory at it. Use once per machine when the user asks to set up, install or migrate receipts-wiki memory.
disable-model-invocation: true
license: MIT
---

# Set up receipts-wiki

Work in three passes: look, show, then write only what the user approved. Never move or delete existing memory; copy it. Never print a secret value.

Paths used below:

- `<home>` is `$RECEIPTS_WIKI_HOME` if set, otherwise `~/.agents`.
- `<plugin>` is two directories above this skill's base directory. The command line is `python3 <plugin>/scripts/rw.py`. If that file does not exist, this skill was installed without the plugin: tell the user to install the receipts-wiki plugin, because the hooks do the recording, and stop.

## 1. Look (read only)

- Does `<home>` exist, and is it the root of a git repository (`git -C <home> rev-parse --show-toplevel` equals `<home>`)? What does it contain?
- In `~/.claude/settings.json`: the current `autoMemoryDirectory` and `cleanupPeriodDays`, and any `hooks.SessionEnd` or `hooks.Stop` entry that already commits memory, which would run twice alongside the plugin.
- In `~/.claude/CLAUDE.md`: an import of `<home>/AGENTS.md`, which would load the rules twice because the plugin injects them.
- Existing per-project memory under `~/.claude/projects/*/memory/`: file counts per project, and file names that appear in more than one project (ignore `MEMORY.md`).
- Whether Codex is installed (`~/.codex` exists) and whether `~/.codex/AGENTS.md` already exists.

## 2. Show

Summarise the findings, then list each proposed change on one line and ask the user to confirm. Ask separately about:

- transcript retention (`cleanupPeriodDays`): keep the current value, 90 days, or another number. Claude Code deletes transcripts older than this; receipts-wiki keeps its own redacted archive of the conversation text.
- copying existing per-project memory, and the area name for each project;
- removing a duplicate memory-commit hook or CLAUDE.md import, if you found one;
- installing the git pre-commit check in `<home>`, which blocks commits that stage a secret value or a note without a name and description, including commits made by other agents or by hand.

## 3. Write (only what was approved)

1. `mkdir -p <home>/memory`. If `<home>` is not a git repository root, run `git -C <home> init -b main`.
2. Make sure `<home>/.gitignore` contains `sessions/`, `proposals/` and `.state/`.
3. If `<home>/AGENTS.md` is missing, copy `<plugin>/templates/AGENTS.md` there and ask the user to replace the example rules. If it exists, show how its memory rules differ from the template's `## Memory` section and apply only the changes the user approves.
4. Merge into `~/.claude/settings.json`, keeping every other key: `"autoMemoryDirectory": "<home>/memory"` and the approved `cleanupPeriodDays`. Check the result with `python3 -m json.tool ~/.claude/settings.json`; a malformed settings file disables all of its settings.
5. If migration was approved, copy each project's notes into `<home>/memory/`, skipping each project's `MEMORY.md`, and set `metadata.area` in every copied note to the approved area name. Leave the originals where they are. Do not commit yet.
6. Run `python3 <plugin>/scripts/rw.py lint`. If it reports a secret value in any note, show the file names, propose replacing each value with the secret's name or location, and apply only approved edits. Nothing is committed until no secret remains.
7. Run `python3 <plugin>/scripts/rw.py record --agent receipts-wiki-setup`. It commits the copied notes, `AGENTS.md`, `.gitignore` and the generated indexes in one commit. If the pre-commit check was approved, install it afterwards with `python3 <plugin>/scripts/rw.py install-git-hook`; it never replaces a hook it did not write.
8. If Codex is installed and the user approved, create `~/.codex/AGENTS.md` as a symlink to `<home>/AGENTS.md`. If a file already exists there, show it and ask first.
9. Remove the duplicate memory-commit hook or CLAUDE.md import if the user approved it.
10. Run lint again and report the result. Tell the user to start a new session, because settings and hooks load at session start.
