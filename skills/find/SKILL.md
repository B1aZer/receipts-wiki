---
name: find
description: Searches every receipts-wiki memory note by topic, whatever directory the session started in, and names the cursor note for that work. Use when a task touches a project, system, person or decision that earlier sessions may have recorded, and before creating a memory note, so the work continues in the existing notes instead of starting new ones.
license: MIT
---

# Find memory notes by topic

Area indexes follow the working directory, but work crosses directories. This search covers every active note.

`<plugin>` is two directories above this skill's base directory. Run the command below directly, without checking first that the file exists; if it fails because `<plugin>/scripts/rw.py` is missing, tell the user to install the receipts-wiki plugin and stop. The setup skill allows the search command in the user's settings; if Claude Code still asks for approval, suggest the user add `Bash(python3 *receipts-wiki*/scripts/rw.py find *)` to `permissions.allow` in `~/.claude/settings.json`.

1. Pick the distinctive words for the topic: product, repository, system, service or person names, error names. Leave out everyday words such as status, check or fix.
2. Run `python3 <plugin>/scripts/rw.py find <words> --limit 8`. Each result shows the note's path, type, area, the words that matched and its description. A `Cursor for this work` line names the note that holds where the work stands.
3. Read the cursor first, then the notes the task needs. Results are ranked by word overlap; a match on an everyday word alone is noise, so judge by the description and the matched words.
4. If nothing useful comes back, try one or two other names for the same thing, then say that memory has nothing on it.
5. Before creating a note, run this search for its subject. If a note on the same subject exists, update that note. Write a new one only for a separate fact, and link the two with `[[name]]`.

Memory is what was true when written. Check files, flags and numbers before relying on them.
