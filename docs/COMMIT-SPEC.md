# Commit format for memory changes

Version 0.2, 2026-09-14.

Every agent turn that changes the memory home becomes one git commit. The history is the log; this format makes it queryable by people, agents and scripts. It extends [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for the subject and [Contextual Commits v0.1.0](https://github.com/berserkdisruptors/contextual-commits) for the reasoning, and uses standard [git trailers](https://git-scm.com/docs/git-interpret-trailers) for metadata.

## Turns

A turn is Claude Code's unit, not one defined here: a submitted prompt and everything the agent does until it stops and hands control back, including every model call, tool call and sub-agent. Claude Code gives each turn a `prompt_id` in the hook payload and marks its end with `Stop` (or `StopFailure` on an API error). Observed in a logged `claude -p` session on 2026-09-14:

- `UserPromptSubmit`, `PostToolUse`, `SubagentStop`, `Stop` and `SessionEnd` all carry the same `prompt_id` for one turn.
- A sub-agent's writes carry the parent's `session_id` and `prompt_id` plus an `agent_id`; they belong to the parent's turn. A sub-agent ends with `SubagentStop`, not `Stop`.
- When a background task finished, Claude Code delivered it as another `UserPromptSubmit` with the same `prompt_id`, and `Stop` fired once, at the end. That turn's writes stay pending until then.

Per the hooks documentation, `Stop` does not fire when the user interrupts; this was not tested here. A turn that model APIs call a "turn" (one model response) is a different, smaller unit.

## Layout

```
<subject>

<action lines, optional>

<trailers>
```

## Subject

`<type>(<scope>): <verb> <name>[, <verb> <name>...]`

| Part | Value |
|---|---|
| type | `rules` when every change is to `AGENTS.md`, otherwise `memory` |
| scope | the `metadata.area` shared by every changed note, otherwise `general` |
| verb | `add`, `update`, `supersede`, `verify`, `retire`, `remove`, `record`, `accept`, `rebuild` |
| name | the note's frontmatter `name`, otherwise the file name without `.md`; `MEMORY.md` and `AGENTS.md` by file name, after the notes |

Subjects are kept under 72 characters. Names that do not fit are replaced by `and N more`; the trailers still list every file. A commit that only regenerates indexes has the subject `memory(general): rebuild indexes`.

## Action lines

Derived from lines that are new in this change. Nothing is invented and nothing is copied from outside the note.

| New line in the note | Action line |
|---|---|
| `Supersedes (YYYY-MM-DD): <old claim>. <evidence>` | `rejected(<name>): <old claim>; <evidence>` |
| `Why: <text>` | `intent(<name>): <text>` |
| `Reopen if: <text>` | `constraint(<name>): reopen if <text>` |

Each action line is capped at 200 characters.

## Trailers

| Trailer | Required | Value |
|---|---|---|
| `Change` | yes, one per file | `<event> <path relative to the memory home>` |
| `Agent` | yes | `claude-code`, the name given to `rw.py record --agent`, or `unknown` |
| `Session` | when known | the session id from the hook payload |
| `Turn` | when known | the prompt id of the turn; several, comma-separated, when a recovered commit covers more than one turn |
| `Cwd` | when known | the session's working directory |
| `Transcript` | when known | transcript path; the file may be gone after the retention period |
| `Receipts` | when present | comma-separated values from frontmatter `receipts` or `Receipts:` lines of the changed notes |
| `Recovered` | when true | `true` when the commit was made after the turn had ended, because its end hook did not run |

## Events

| Event | Detected when |
|---|---|
| `fact.added` | the file is not in `HEAD` |
| `proposal.accepted` | the file is not in `HEAD` and its frontmatter has `source: proposal` |
| `fact.superseded` | the number of `Supersedes (` lines increased |
| `fact.retired` | frontmatter `status` changed to `retired` |
| `fact.verified` | only `last_verified` changed |
| `fact.updated` | any other content change |
| `fact.removed` | the file was deleted |
| `rules.changed` | `AGENTS.md` changed |
| `external.change` | the change was not written through the hooks: found by a catch-up, or committed by `rw.py record` |
| `index.rebuilt` | a generated file (`index-<area>.md`, the block in `MEMORY.md`) was regenerated for this commit |

Each file gets one event, the net change of the whole turn against `HEAD`: a note written three times in one turn is one change. When several events apply, the first in the order of the table wins.

## When commits are made

| Moment | What is committed | Credited to |
|---|---|---|
| End of a turn (`Stop`, `StopFailure`; `SessionEnd` for the last turn) | files this session wrote during the turn, and the indexes regenerated from them | the session and turn |
| The session's next prompt, or its next start | a turn whose end hook did not run | that session and turn, `Recovered: true` |
| Session start, and a prompt at most every 10 minutes | the logs of other sessions with uncommitted writes and no activity for 60 minutes | those sessions, `Recovered: true` |
| Same | memory changes that no session's log claims | `Agent: unknown`, `external.change` |
| `rw.py record --agent <name>` | every uncommitted change to `memory/`, `AGENTS.md` and `.gitignore` | the named agent, `external.change` |

## Rules

- One commit per turn that changed memory. No change, no commit.
- A commit contains only the files this session wrote, plus the generated indexes. Files written by other sessions that are still active stay uncommitted until their own turns end. Indexes are built from committed notes and this turn's notes, so another session's unfinished note never appears in them.
- The end-of-turn hook prints nothing and never asks the agent to continue. It does nothing when `stop_hook_active` is set.
- Commits wait while a merge, rebase, cherry-pick or revert is in progress in the memory repository.
- History is never amended, rebased, reset or force-pushed. A correction is a new commit. In Claude Code a hook refuses git commands that would rewrite the memory repository's history; `git revert` stays allowed because it adds a commit.
- Commits are local. The plugin never pushes.

## Example

```
memory(api): add quotes-cdn-cache, supersede quotes-cache-ttl

rejected(quotes-cache-ttl): the 60-minute API cache TTL caused stale quotes; 12 of 200 quotes still stale at 5 minutes (query q_8840)
intent(quotes-cdn-cache): /quotes responses carried max-age 3600 at the CDN edge

Change: fact.added memory/project_quotes_cdn_cache.md
Change: fact.superseded memory/project_quotes_cache_ttl.md
Change: index.rebuilt memory/index-api.md
Change: index.rebuilt memory/MEMORY.md
Agent: claude-code
Session: 00000000-0000-0000-0000-000000000000
Turn: 11111111-1111-1111-1111-111111111111
Cwd: /home/you/src/api
Receipts: query:q_8840, commit:9f8e7d6
```

## Queries

```bash
# every commit that touched one note, oldest first, with its changes
git log --reverse --date=short --format='%h %ad %s%n  %(trailers:key=Change,valueonly,separator=%x3B )' -- memory/project_quotes_cache_ttl.md

# every rejected approach recorded for a note
git log --grep='rejected(quotes-cache-ttl' --format='%h %ad %s' --date=short

# everything one session wrote
git log --format='%h %s' --grep='^Session: 00000000-0000-0000-0000-000000000000$'

# changes that bypassed the write hooks, and commits recovered after a missed turn end
git log --format='%h %ad %s' --date=short --grep='^Change: external.change'
git log --format='%h %ad %s' --date=short --grep='^Recovered: true$'
```
