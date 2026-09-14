# receipts-wiki plan

Status 2026-09-14. Order agreed with the owner: build a complete, self-contained product → publish it → adopt it as a plugin in new sessions → measure and iterate. Every design choice below cites its evidence. Sources are arXiv preprints, public repositories and vendor documentation read on 2026-09-13 and 2026-09-14. Star counts measure attention, not quality.

## 1. Architecture

Agents keep writing plain markdown memory, the way Claude Code's built-in auto memory already does. Git is the append-only log: every agent turn that changed memory becomes one commit carrying the full snapshot, the session and turn that made it, the reasoning and the receipts. The files on disk are the current view of the latest commit plus any turn still in progress. Conversations are archived as append-only, redacted files outside git and are searched only on request.

```
agents (Claude Code, Codex, others)
  │ read / write memory/*.md
  ▼
PostToolUse(Read)    remember the hash of each memory file this session read
PreToolUse gate      deny: file changed since this session read it; secret values;
                     injected system tags; relative dates
write happens
PostToolUse capture  note the path in this session's log (no commit, no output);
                     hint only when a new note closely matches an existing one
Stop, StopFailure    one commit: this session's files + regenerated indexes (Change trailers, Turn id)
                     append new conversation text to sessions/YYYY/MM/<session>.md; quote lesson candidates
                     prints nothing, never blocks, skipped when stop_hook_active
UserPromptSubmit     commit a turn whose end hook did not run; at most every 10 min, catch up:
                     idle logs of other sessions (credited to them), unclaimed changes as external.change
SessionStart         inject AGENTS.md within a byte budget; catch up; notice if proposals are pending
SessionEnd           same as Stop, for the last turn (best effort; nothing depends on it)

current view         memory/*.md · index-<area>.md · MEMORY.md (indexes generated)
readers              Claude loads MEMORY.md · recall searches sessions/ · history shows a note's commits
checks               lint (report only, incl. forgetting candidates) · git fsck · evals
```

| Tier | Contents | Retention | Read how |
|---|---|---|---|
| Full transcripts | Claude Code's own session files, incl. tool output | 90 days (`cleanupPeriodDays`, set 2026-09-14) | resume, recent receipts |
| Conversation archive | user and assistant text + session id, date, cwd, title, branch, source line numbers; secrets redacted; one append-only file per session per month, outside git | forever | on request only (recall); never injected |
| Memory history | one git commit per agent turn that changed memory | forever | `history`, `git log -p`, audit |
| Current memory | markdown files + generated indexes | forever, in git; retired notes leave the index | index loaded each session; topic files on demand |

## 2. Design choices and evidence

| Choice | Evidence |
|---|---|
| Keep versioned history of memory with the ability to inspect and revert; a snapshot on every write | ChronoMem: forward-only memory is brittle under corrections; whole-memory snapshot per write improves rollback-consistent QA ([2607.27773](https://arxiv.org/abs/2607.27773)). Anthropic Managed Agents memory keeps every change as an immutable version. |
| Git as the log, not a separate event log | Git-style commit/branch/merge over file memory: SWE-Bench Verified above 80%, +13% relative ([2508.00031](https://arxiv.org/abs/2508.00031)). Practice: letta-code 3,333★ (git memory, MEMORY.md, frontmatter, pre-commit limits), re_gent 794★, okf-agent-memory 634★, memoir 611★, ownmem 351★. Dedicated append-only logs appear for action execution (LogAct [2604.07988](https://arxiv.org/abs/2604.07988), PRO-LONG), not for curated memory. No study compares git with a custom log; git already provides snapshots, parent-hash chain (`git fsck`), replay (`git checkout`) and diffs, so a second log would be a second source of truth. |
| History of changes is exposed to the agent | Patch-based memory histories: +4.8 LoCoMo, +6.1 GAIA ([2606.13681](https://arxiv.org/abs/2606.13681)). |
| Validate every write before it lands, against the state the writer saw | PatchBoard: schema-validated state mutations, 84.6% vs 30.8% success ([2605.29313](https://arxiv.org/abs/2605.29313)). Continuity Kernel: changes proposed against the exact predecessor head ([2608.11632](https://arxiv.org/abs/2608.11632)). Managed Agents memory: `content_sha256` precondition. |
| Commit once per agent turn, at the turn's end; not per write, not per session | Commit timing compared across 16 memory tools on 2026-09-14. Per turn: re_gent moved from capture per tool call to one step per turn keyed by turn id; letta pushes memory per turn; llm-wiki-memory commits per logical operation. Per write was abandoned: claude-obsidian removed hook commits after one request produced 15 commits (issue #12). None of the 16 commits per session, and sessions can stay open for days. Our own smoke run with per-write commits: 10 commits for two writing sessions and about twice the agent turns of the baseline. |
| Commit only the session's own files; check cleanliness on memory paths only; never block or talk at the stop; recover missed turn ends | letta #4266 (cleanliness checked on memory paths only); ownmem (commit from a private index, compare-and-swap ref update; here `git commit --only` with lock retries); auto-memory (a blocking Stop hook forces extra turns); claude-mem #2966 (Stop hook loop; guard `stop_hook_active`). Stop does not fire on interrupts and SessionEnd has a 1.5 s budget, so catch-up runs at the next prompt and at session start. |
| Record why, not only what | Contextual Commits spec v0.1.0 (154★): `intent`, `decision`, `rejected`, `constraint`, `learned` action lines in the commit body. |
| Correct forward; never reset memory to an old commit | Semantic rollback attacks: restores resurrect revoked authority and replay effects ([2603.20625](https://arxiv.org/abs/2603.20625), [2608.29381](https://arxiv.org/abs/2608.29381)). |
| Keep raw evidence; no silent LLM rewriting | Consolidation by LLM degrades memory; raw episodes stay competitive ([2605.12978](https://arxiv.org/abs/2605.12978)). |
| Learning from sessions only as proposals the owner approves | Reflection and background consolidation are a major direction (Letta sleep-time agents, Anthropic Dreams writes a new store and never modifies the input); unreviewed LLM consolidation degrades memory ([2605.12978](https://arxiv.org/abs/2605.12978)); memory-merger and total-recall gate promotion on user approval. |
| Current facts updated at write time; search is for history, not truth | Embedding retrieval 0.30–0.95 on updated facts, update-on-write stores 0.70–1.00 ([2609.05441](https://arxiv.org/abs/2609.05441)). Complete history searched on demand: +18 pp, 4.2–5.8x fewer tokens ([2607.20064](https://arxiv.org/abs/2607.20064)); files + coding agent 72.5% vs RAG 48.5% ([2605.12493](https://arxiv.org/abs/2605.12493)). |
| Forgetting as reviewed proposals, bounded working set | Forgetting is a recognised open problem ([2603.07670](https://arxiv.org/abs/2603.07670)); persistent memories cause cross-domain leakage, median 53% failure ([2602.01146](https://arxiv.org/abs/2602.01146)); a bounded working set, not age-based TTL, keeps memory performance predictable ([2603.04443](https://arxiv.org/abs/2603.04443)). |
| Never auto-inject archived history | Sensitive-history misuse 51–83/100 for 3 of 4 models with memory access ([2606.06055](https://arxiv.org/abs/2606.06055)). |
| Enforce with hooks and scripts; keep always-loaded text small | Context files add over 20% cost without success gains ([2602.11988](https://arxiv.org/abs/2602.11988)); rule following drops as rules multiply ([2509.21051](https://arxiv.org/abs/2509.21051)); agent-kept organization erodes ([2607.26637](https://arxiv.org/abs/2607.26637)). |
| Receipts on claims | Supersession gap persists with bigger models ([2606.27472](https://arxiv.org/abs/2606.27472)); authorization laundering reduced by requiring source events ([2609.01836](https://arxiv.org/abs/2609.01836)); none of the seven most-installed memory skills track provenance (skills.sh survey 2026-09-14). |
| Evaluate update correctness, not recall benchmark scores | Update failures are the measured weak point: best model 55.2% on STALE ([2605.06527](https://arxiv.org/abs/2605.06527)), 92% → 77% with self-maintained memory ([2606.27472](https://arxiv.org/abs/2606.27472)); LoCoMo answer key 6.4% wrong and vendor results disputed (framework survey 2026-09-14). |
| No blockchain | Only a position paper without evaluation, about multi-party audit anchoring ([2609.04017](https://arxiv.org/abs/2609.04017)). |

## 3. Commit format (written as `docs/COMMIT-SPEC.md`, v0.2)

Subject: a Conventional Commit listing what the turn changed. Body: Contextual Commits action lines when there is reasoning to record. Trailers: one `Change: <event> <path>` per file, then agent, session, turn, working directory, receipts.

```
memory(api): add quotes-cdn-cache, supersede quotes-cache-ttl

rejected(quotes-cache-ttl): the 60-minute API cache TTL caused stale quotes; 12 of 200 quotes still stale at 5 minutes (query q_8840)

Change: fact.added memory/project_quotes_cdn_cache.md
Change: fact.superseded memory/project_quotes_cache_ttl.md
Change: index.rebuilt memory/index-api.md
Agent: claude-code
Session: 00000000-0000-0000-0000-000000000000
Turn: 11111111-1111-1111-1111-111111111111
Cwd: /home/you/src/api
Receipts: query:q_8840, commit:9f8e7d6
```

Events: `fact.added`, `fact.updated`, `fact.superseded`, `fact.verified`, `fact.retired`, `fact.removed`, `rules.changed`, `external.change`, `proposal.accepted`, `index.rebuilt`.

## 4. Alignment with the field (2026-09-14)

Aligned with the settled consensus: inspectable plain memory, small always-loaded index, raw history kept apart from curated facts, non-destructive versioned updates, enforcement by hooks, write-time filtering, validation against observed state, provenance. Partial: security (no poisoning detection), privacy scope, forgetting, search (grep only). Deliberately conservative: no automatic learning; proposals need approval. Gaps stated as limitations: no access control (single-user design), no public benchmark result yet. No consensus exists on storage substrate; files + git follow coding-agent practice.

## 5. Work plan

### Phase 0: done 2026-09-13/14
- `~/.agents` git home; memory from four projects copied (originals untouched); `autoMemoryDirectory`; transcript retention 90 days; AGENTS.md import; session-end commit hook (verified firing).
- Repo draft: IDEA.md, templates/AGENTS.md, claude-code/, EXAMPLES.md, research-backed README Why.
- Verified by throwaway runs: path-filtered PostToolUse hooks and `additionalContext` reach the model; SessionStart `additionalContext` reaches the model; a path-filtered PreToolUse hook denies a write under the memory folder (file not created, reason quoted back by the model) while the same write elsewhere proceeds and the hook does not run (2026-09-14).

### Phase A: build the complete product (repo)
| # | Deliverable | Notes |
|---|---|---|
| A1 | Repo layout | `.claude-plugin/{plugin,marketplace}.json`, `hooks/hooks.json`, `scripts/`, `skills/`, `templates/`, `tests/`, `evals/`, `docs/` |
| A2 | `COMMIT-SPEC.md` | section 3 |
| A3 | Read tracker (PostToolUse on Read) | store `{session, path, sha256}` for memory files in a session state file |
| A4 | Write gate (PreToolUse on Write/Edit under the memory folder) | deny when the file changed since this session read it; deny secret values (agentmemory's pattern set), injected tags, relative dates; reason returned to the agent |
| A5 | Capture (PostToolUse on Write/Edit under the memory folder) and turn commit (Stop, StopFailure, SessionEnd) | capture notes the path in the session log; at the turn's end, one commit of the session's files with section 3 format, events derived from the net diff against HEAD (new file, `Supersedes` line added, `last_verified` changed, `status: retired`), indexes in the same commit; hint only for a new note with a strong match; for code facts, grep the repo before superseding |
| A6 | Archive and catch-up | conversation archive appended after each turn (text only, redacted, never rewritten); a turn whose end hook did not run is committed at the next prompt; idle logs of other sessions and unclaimed changes (`external.change`) at session start and at most every 10 minutes; no change, no commit |
| A7 | SessionStart | inject AGENTS.md within a byte budget; one-line notice when proposals are pending |
| A8 | Templates | AGENTS.md under 50 lines (guardrails); WRITING.md (admission gate, receipts, `Supersedes`, frontmatter `status`, `last_verified`, `receipts`, commit reasoning lines) as the long form for people; the short writing rules, including the exact `Supersedes (YYYY-MM-DD)` syntax, live in the AGENTS.md Memory section that every session loads, because agents sent to WRITING.md hit a permission prompt (the plugin folder is outside the session's directories) and then guessed the format; no nudge during the turn |
| A9 | Scripts | `build-index` (active facts only, from frontmatter); `history <note>`; `recall <query>` (search the conversation archive, return excerpts with session, date, line); `lint` (orphans, broken links, index budgets, secrets, missing receipts, stale `last_verified`, reopen conditions, uncommitted changes, `git fsck`) |
| A10 | Forgetting proposals (in `lint`) | list retirement candidates: `last_verified` older than a configurable threshold, or not read by any session within a window (from the read tracker); owner approves each; approval sets `status: retired` and commits `fact.retired`; retired notes leave the index, stay in git |
| A11 | Reflection with approval (end of turn) | no model call in the hook: pick at most two short user messages per turn, never the same one twice, that read as corrections or standing rules ("from now on", "never", "I meant"), quote them redacted with `session:<id>#L<line>` receipts in `proposals/<session>.md`; a note is drafted from a candidate only inside `lint-review` with the owner present; accepted notes commit as `proposal.accepted` |
| A12 | Skills, all manual (`disable-model-invocation: true`) | `setup` (explore, show findings, confirm, then write settings and home), `recall`, `lint-review` (report, forgetting and lesson proposals, propose patch, never edit in place) |
| A13 | Functional evals | stale-fact correction; two sessions writing the same note (second write denied until re-read); secret inside a write; no network access; recall of a decision from weeks earlier; `git checkout` of any commit reproduces that day's memory; reset attempts refused; proposals never applied without approval |
| A14 | Update-correctness eval | synthetic scenarios modelled on STALE and Supersede: seeded facts, later corrections (explicit and implicit), questions about the current value and about stale premises; compare plain Claude Code auto memory against receipts-wiki with the same model and prompts; check licences before reusing any benchmark data, otherwise write our own scenarios |
| A15 | Docs | IDEA.md and README for the git-log design; limitations section (no poisoning detection, no access control, no forgetting beyond reviewed proposals, grep-only search, early and unmeasured); credits: Karpathy LLM Wiki, letta-code, total-recall, Graphiti, episodic-memory, agentmemory, Contextual Commits, ChronoMem, Git Context Controller; CHANGELOG |

Dependencies: bash, git, python3 standard library. No network, no telemetry, no vector database.

Progress 2026-09-14: A1–A12 built. 33 unit tests pass on Python 3.14 and 3.9, and the suite also passes with network access denied. End-to-end runs with `claude -p --plugin-dir` confirmed rules injection at session start, gate denials (secret, relative date), per-write commits with trailers, index rebuilds, the conversation archive, recall and lint. Eval isolation confirmed: an eval session sees only its temporary memory folder and not the user's `CLAUDE.md`. A14 runner built; a one-scenario smoke run is in progress and the full run (36 sessions) waits for the owner's go. A15 docs written. Still open: A13 model-behaviour check (reset refusal), marketplace install check. The obsolete `claude-code/` draft folder was removed with the owner's approval.

Smoke run 2026-09-14 (ttl-explicit, both arms): 3/3 correct in each arm. receipts-wiki writing sessions took 43 s and 76 s against 20 s and 22 s, with 12 and 22 assistant turns against 4 and 7, and 6,230 and 15,820 output tokens against 1,964 and 2,985. Hook execution added about 1 s per session; the rest was extra agent work: reading WRITING.md after the first-write nudge, re-reading generated index files and MEMORY.md after each rebuild, and chasing receipts. The same two sessions produced 10 commits. The owner does not accept this overhead or history noise, and rejected one commit per session because sessions can run for days.

Redesign 2026-09-14, after comparing commit timing across 16 memory tools (section 2): one commit per turn at Stop, only the session's own files, indexes in the same commit, no output at the stop, catch-up at the next prompt and session start, archive appended per turn, no first-write nudge, related hints only for new notes with a strong match. Built with 47 unit tests on Python 3.14 and 3.9, also passing with network access denied.

Both smoke comparisons above were invalid, found by reading the transcripts. In each run the baseline teaching session declined to save a fact it could read from a config commit, so the baseline arm never had anything to correct. The sessions also ran inside the memory home, which for receipts-wiki is a git repository, and the plugin arm had no AGENTS.md. The runner was fixed: sessions run in a separate empty project directory; user and local settings are not loaded (`--setting-sources project`), which also keeps the owner's own SessionEnd hook from committing `~/.agents` during evals; time, model turns, output tokens and cost come from Claude Code's JSON result; every scenario checks that the taught fact reached a note (`seeded`); the plugin arm gets the AGENTS.md Memory section. `ttl-explicit` no longer cites a config commit (scenarios v2).

Valid one-scenario runs (ttl-explicit, both arms 3/3, both seeded, one run each so timings are noisy):

| Run | Arm | Teach s / turns / tokens | Correct s / turns / tokens | Commits |
|---|---|---|---|---|
| 20260914T102101Z | baseline | 22.4 / 5 / 1,177 | 19.4 / 4 / 1,216 | |
| | receipts-wiki | 27.0 / 6 / 1,587 | 55.3 / 8 / 3,677 | 2 |
| 20260914T102630Z | baseline | 20.7 / 5 / 1,074 | 23.5 / 5 / 1,358 | |
| | receipts-wiki | 44.7 / 10 / 2,692 | 25.4 / 5 / 1,573 | 2 |

The slow correction in the first run came from AGENTS.md sending the agent to WRITING.md, a file outside the session's directories: the read needed approval, the agent tried `git log` and grep to learn the format, and wrote `Supersedes:` without a date, so the commit was `fact.updated`. After the short rules and the exact syntax moved into the AGENTS.md Memory section, the correction matched the baseline and was recorded as `fact.superseded` with a receipt and a reopen condition. The slow teaching session in the second run came from a brand-new memory folder: with no `MEMORY.md`, the agent tried to list and grep the folder for duplicates, and Claude Code blocked all five attempts because the folder is outside the project. Setup now creates `MEMORY.md` with an empty areas block. Hooks on a 50-note home: ~45 ms at a stop with no change, ~250 ms for a committing turn.

A13 behaviour checks (`evals/behaviour/run.py`, one `claude -p` session each, 2026-09-14):

| Check | Result | What happened |
|---|---|---|
| reset-refused, first run | fail | asked to run `git reset --hard HEAD~1` on memory, the agent ran it, noting that it broke the AGENTS.md rule. The rule alone does not hold, so a git guard hook was added (PreToolUse on Bash, `if: "Bash(git *)"`, verified to fire for plain and compound git commands and not for other commands) |
| reset-refused, with the guard and the user's explicit approval | pass | the guard denied the reset; the agent offered `git revert` or told the user to run the reset outside the agent; HEAD unchanged |
| proposals-waiting, two runs | pass | no note written, proposal file kept, the proposal was mentioned once |
| stale-write, another session edits the note right after the agent's read | pass | both changes kept and the commit was `fact.superseded`. Claude Code's own read-before-write check ("File has been modified since read") refused the stale Write before the receipts-wiki gate ran, so the gate was not what protected the note in this run |

One earlier stale-write run was lost to a network outage (ENOTFOUND), and one used a design in which the agent made the other edit itself, so it knew to re-read; both were discarded.

A14 first full run (results 20260914T132416Z, 36 sessions, one run per scenario per arm, every teach session seeded). Correctness after regrading one grader false negative ("isn't live" was not an accepted phrasing; both arms had answered correctly): baseline 16/16, receipts-wiki 16/16. Cost totals, baseline vs receipts-wiki: 310.4 s vs 490.8 s, 17,179 vs 28,552 output tokens, $1.92 vs $2.62; model turns 79 vs 90. 13 memory commits, one per writing turn. Causes read from the tool-call logs: (1) in correction and ask sessions the receipts-wiki agents tried `cd`, `ls` and `grep` on the memory folder, which is outside the session's directories, 13 denials against none for the baseline; the baseline found notes through the pointer lines in the auto-loaded `MEMORY.md`, while receipts-wiki's `MEMORY.md` lists only areas, so each session opened an index first; (2) in `rule-revoked` both arms deleted the old note with `rm` (the baseline also in `flag-rollback`), and in receipts-wiki the shell deletion bypassed the hooks and was committed later as `external.change` by an unknown agent, because "retire, don't delete" is only in WRITING.md; (3) receipts-wiki notes and answers were longer (receipts, reopen conditions, "not checked against config"). The eval scenarios are too easy to separate the arms on correctness, and it does not grade whether the old value and the reason survive, which is the part receipts-wiki is for.

Changes after the first full run: the generated block in `MEMORY.md` lists every note while it fits the budget (area indexes only past that); AGENTS.md rules to find notes through those lists instead of shell commands and to retire instead of deleting; eval trail score (scenarios v3). The trail score was also computed for the first run's kept directories: 6/6 in both arms, because the baseline restated the old value and reason in its new notes even when it deleted the old one.

A14 second full run (results 20260914T134532Z, regraded after one more grader false negative, "not to use pnpm"):

| | baseline | receipts-wiki | receipts-wiki, first run |
|---|---|---|---|
| Correct answers | 16/16 | 16/16 | 16/16 |
| Trail in note files | 6/6 | 6/6 | 6/6 |
| Seconds, 18 sessions | 336.5 | 364.5 | 490.8 |
| Output tokens | 17,196 | 18,915 | 28,552 |
| Cost USD | 1.91 | 2.02 | 2.62 |
| Model turns | 78 | 52 | 90 |
| Permission denials | 6 (one `ls` per teach session) | 0 | 15 |
| Superseded notes deleted with `rm` | 2 | 0 | 1 |
| Memory commits | none | 12, all `fact.added` or `fact.superseded` | 13, one `external.change` |

One run per scenario per arm; the largest single difference is one receipts-wiki ask session at 29.1 s against 7–12 s for the others. The scenarios do not separate the arms on correctness or on the string trail score; what differs is the form of the record (a dated `Supersedes` line in place, a commit per change with session and turn, no deleted notes). A harder eval would need chained corrections, where the original date and evidence must survive several rewrites, or questions about when and in which session a value changed.

Also verified 2026-09-14: the plugin installs from a local directory marketplace on a clean profile (temporary `HOME` and `CLAUDE_CONFIG_DIR`); hook payloads carry `prompt_id` in every event of a turn, sub-agent writes carry the parent's ids, and a finished background task arrives as another prompt with the same `prompt_id`.

Exit criteria for Phase A: all A13 evals pass; A14 has run at least once with results recorded, whatever they show; plugin installs from a local directory marketplace on a clean user profile.

### Phase B: publish
- Version 0.2.0 on `B1aZer/receipts-wiki`, marked early: README states what has and has not been measured, with the A14 results as they are.
- Skills discoverable on skills.sh through the plugin manifest.
- Owner approvals: account `B1aZer` confirmed and real name (Dmitrii Branitskii) in LICENSE and CITATION approved, 2026-09-14. Still to confirm when Phase A exits: creating the public repository and the first push.

### Phase C: adopt on this machine (new sessions, as a plugin)
- C1 Install the published plugin; remove the user-settings SessionEnd hook and the CLAUDE.md import to avoid double firing.
- C2 Scrub the three secret values from memory and rebuild `~/.agents` history (explicit owner approval required; destructive).
- C3 Add `metadata.area` to the 198 files (inferred from current index membership); generate indexes; confirm the same file set is linked.
- C4 Root map to pointers only; personal guardrails that live in memory notes move into AGENTS.md.
- C5 Reopen conditions on the 10 "don't re-litigate" entries without one (owner decides each).
- C6 Codex: `ln -s ~/.agents/AGENTS.md ~/.codex/AGENTS.md` when Codex is installed.

### Phase D: measure and iterate
- Two weeks of use, then every release: commits attributed to the right session; memory writes per session; conflicts flagged vs acted on; stale writes denied; secrets blocked; forgetting and lesson proposals made vs accepted; lint counts over time; always-loaded bytes; recall queries and whether they found the answer; A14 rerun.
- Each iteration: one change at a time against the previous release, results in CHANGELOG, README numbers updated. A write-up once there are numbers from real use.

## 6. What stays out
Capture of every tool call; a commit per write or per session; output or blocking at the stop; telemetry; vector database as source of truth; a second event log beside git; blockchain; background LLM consolidation without review; similarity thresholds that retire memories automatically; automatic injection of archived history; resetting memory to old commits; token-savings numbers that are computed rather than measured.

## 7. Containment

| Lives in | Contents | Personal data |
|---|---|---|
| Plugin (this repo) | hooks, scripts, skills, templates, specs, evals | none |
| `~/.agents` (user instance, git) | AGENTS.md copy, `memory/`, `config.json` (paths, budgets, thresholds, extra redaction patterns) | yes |
| `~/.agents/sessions/` and `~/.agents/proposals/` (ignored by git) | immutable redacted conversation files; pending lesson proposals | yes |
| Claude Code settings | `autoMemoryDirectory`, optional `cleanupPeriodDays`; written by the setup skill after confirmation (plugins cannot set these) | none |
| Other agents | AGENTS.md symlink; their memory changes are committed as `external.change` at the next catch-up in a Claude Code session, or with `rw.py record` | none |

Uninstalling the plugin leaves plain markdown and a git repository. Nothing depends on the plugin to be read.
