# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - unreleased

### Added

- Claude Code plugin (`.claude-plugin/`, `hooks/hooks.json`) with hooks at session start (rules injection within an 8 KB budget), prompt submit, read, before and after writes, turn end and session end.
- Write gate: refuses memory writes when the file changed after the session read it, or when the text contains a secret value, injected system text or a relative date; refuses edits to generated index files.
- Turn commits: one git commit per agent turn that changed memory, in the format of `docs/COMMIT-SPEC.md` v0.2 (Contextual Commits reasoning lines, one `Change` trailer per file, `Session` and `Turn`), with the regenerated area indexes in the same commit. Only the session's own files are committed. The hook never blocks the stop, and prints nothing unless a commit fails or has to wait.
- History guard: a hook on git commands (filtered with `if: "Bash(git *)"`, so other shell commands do not start it) refuses `reset`, `rebase`, `commit --amend`, forced push, `filter-branch`, `filter-repo`, `update-ref`, `reflog expire`, `gc --prune` and forced branch changes in the memory repository. Added after a behaviour check in which an agent ran a requested `git reset --hard` despite the AGENTS.md rule.
- Unattended sessions: with the plugin installed for the user, every `claude -p` or SDK run also received the rules, the area index (about 11,000 characters) and conversation archiving; on the author's machine such runs outnumber interactive sessions about six to one. When Claude Code marks a session unattended (`CLAUDE_CODE_SESSION_ATTENDED=0`, or an `sdk` entrypoint), receipts-wiki now skips context and archiving, and keeps the write gate, guards and commits. `RECEIPTS_WIKI_ATTENDED` overrides; the eval runners set it to 1.
- Area index at session start: a second SessionStart hook loads the memory index matching the working directory (the nearest folder, walking up, whose name matches `index-<name>.md`), capped at 9,000 characters and cut at a line with a pointer to the rest. Reading an area index had been left to the agent; on the author's machine one session never opened its index in two days.
- Shell writes to memory: on the author's machine, a session with the plugin loaded and the rule "never change memory files with shell commands" in its context still edited `MEMORY.md` with a Python snippet five minutes later, which skipped the write gate and was committed later as an unattributed external change. Now a PreToolUse hook on shell commands that mention the memory home refuses obvious writes (redirects, `tee`, `sed -i`, `rm`, `mv`, `cp`, scripts opening files for writing) and points to Write or Edit; a small shell pre-filter keeps its cost at about 9 ms per ordinary command, because Claude Code's `if` filter does not see redirect targets or heredoc bodies. Memory files changed during a turn without Write or Edit are credited to that turn's commit with a `Shell-write` trailer, unless another session is mid-turn, and the agent is told at its next prompt what the write gate would have flagged. Any commit that would include a secret value is refused, however the file was written.
- Catch-up: a turn whose end hook did not run is committed at the next prompt; stale logs of other sessions and changes made without hooks are committed at session start and at most every 10 minutes.
- Conversation archive outside git, redacted and appended after each turn.
- Related-note hints only for a new note that closely matches an existing one.
- Commands: `rw.py history`, `recall`, `lint` (including forgetting candidates), `build-index`, `record` and `install-git-hook`.
- Git pre-commit check (`rw.py install-git-hook`): blocks any commit to the memory repository that stages a secret value or a note without a name and description, including commits made by other agents or by hand, and warns about files over budget. The write hooks only run inside Claude Code; letta-code checks its memory the same way at commit time.
- Manual skills: `setup`, `recall`, `lint-review`.
- `templates/WRITING.md`, `docs/COMMIT-SPEC.md`, `docs/PLAN.md`, `docs/manual-install.md`.
- Tests (Python 3.9 and later), a no-network functional eval, model-behaviour checks (reset request, stale write), and the update-correctness eval with six scenarios. The eval runs sessions in a separate project directory without the user's own settings, checks that each taught fact was saved, and records time, model turns, output tokens and cost per session.

### Fixed

- Commits that failed or had to wait were retried every turn without any message: a rejecting git pre-commit hook, a commit-signing key that is not available, or a leftover merge or rebase state left memory uncommitted with no sign except `git status`. claude-obsidian removed its hook-driven commits in 2.0.0 after the same kind of silent deferral ([#98](https://github.com/AgriciDaniel/claude-obsidian/issues/98)). The end-of-turn hook now shows the user git's error at the end of every turn until the commit succeeds, session start reports failed catch-up commits and files uncommitted for more than 30 minutes, and lint lists both as problems.

- Index files written by hand before installation were regenerated as empty generated indexes by the first catch-up commit, because every `index-*.md` was treated as generated. Found on the author's machine, where four hand-written area indexes (130, 77, 11 and 3 lines) were emptied; they were restored from git history in a new commit. Only index files that carry the "Generated by receipts-wiki" mark are regenerated or protected by the write gate now; hand-written ones are committed like any other memory file.

- Lint counted a project note as having no receipts unless it had a `Receipts:` line or frontmatter field, which flagged 141 of 198 pre-existing notes on the author's machine, most of which cite commits, files, transactions or query ids in their text. Lint now accepts receipts cited in the text.

- Compaction summaries and background-agent reports are stored in Claude Code transcripts under the user role. The archive labelled them as the user's messages. Records marked `isCompactSummary`, `isVisibleInTranscriptOnly`, `promptSource: system` or `origin.kind: task-notification` are now skipped.

### Removed

- Lesson candidates: user paragraphs picked by phrases such as "never", "always" or "don't" and quoted into proposal files for approval. In the first day of real use, 5 of 6 were false positives: a compaction summary, a background-agent report, a pasted AI answer, a generated `claude -p` prompt, a casual remark and the user's own "discard these" instruction. The keyword-based claude-reflect tracks the same failures in its issues. No study reports precision for detecting corrections, remembered corrections are often not followed ([arXiv:2607.29433](https://arxiv.org/abs/2607.29433), [2606.13174](https://arxiv.org/abs/2606.13174)), and Claude Code's auto memory already saves corrections and anything the user asks it to remember. The proposals folder and the `proposal.accepted` commit event are gone with it.

### Changed

- Git is the memory log: one commit per agent turn that changed memory, instead of one per session. A session can stay open for days, and a session-end commit credited one session with other sessions' writes. Commits per write were tried during development and dropped: in a smoke run, two writing sessions produced 10 commits and roughly doubled the agent's turns.
- `templates/AGENTS.md` is reduced to guardrails and a memory section that holds the short writing rules, including the exact `Supersedes (YYYY-MM-DD)` syntax. `templates/WRITING.md` is the long form for people; agents are not sent to it, because the plugin folder is outside a session's directories and reading it needs approval.
- Setup creates `memory/MEMORY.md` with an empty generated block, so an agent can see an empty memory with one read.
- The generated block in `MEMORY.md` lists every active note while `MEMORY.md` stays within 150 lines and 17 KB, and lists area indexes only past that. In the first full eval run, agents whose `MEMORY.md` listed only areas opened an index in every session and tried to list and search the memory folder, which Claude Code blocked 13 times.
- AGENTS.md memory rules: find notes through `MEMORY.md` and the indexes instead of shell commands; retire a note with `metadata.status: retired` instead of deleting it; never change memory files with shell commands. In the same run both arms deleted superseded notes with `rm`.
- The update-correctness eval reports a trail score: whether the old value and the evidence for the change are still in memory notes, or in git history.
- README "Why" cites research on agent memory instead of one user's setup; IDEA.md and EXAMPLES.md describe the plugin's behaviour.

## [0.1.0] - 2026-09-13

### Added

- `IDEA.md`, the idea file.
- `templates/AGENTS.md`, the rules template with the memory method.
- `claude-code/`: settings snippet, `CLAUDE.md` import, and the `commit-memory.sh` SessionEnd hook.
- `EXAMPLES.md`, six worked examples.
