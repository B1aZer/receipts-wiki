# receipts-wiki

Git-versioned memory for AI agents, where every remembered fact carries its receipt.

receipts-wiki builds on Claude Code's built-in auto memory and adds what it lacks: one memory home shared by every agent and directory, a git commit for each agent turn that changed memory, naming the session and the reasons, checks that stop stale or secret-bearing writes, and an archive of past conversations that is searched only when you ask. It extends Andrej Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) idea file from knowledge you collect to the knowledge an agent produces while it works. Unofficial, and not affiliated with Karpathy.

Status: 0.2.0-dev, in daily use by its author since 2026-09-13. First eval results are under [Results so far](#results-so-far).

| File | What it is |
|---|---|
| [IDEA.md](IDEA.md) | The idea file. Paste it into any agent to build your own version. |
| [hooks/hooks.json](hooks/hooks.json), [scripts/rw.py](scripts/rw.py) | The Claude Code plugin: hooks and a small command line |
| [skills/](skills/) | Three manual skills: `setup`, `recall`, `lint-review` |
| [templates/](templates/) | `AGENTS.md` (guardrails for every agent) and `WRITING.md` (how to write a note) |
| [docs/](docs/) | [COMMIT-SPEC.md](docs/COMMIT-SPEC.md), [PLAN.md](docs/PLAN.md), [manual-install.md](docs/manual-install.md) |
| [evals/](evals/) | A no-network functional eval, model-behaviour checks and the update-correctness eval |
| [EXAMPLES.md](EXAMPLES.md) | What the hooks and commands produce |

## What happens in a session

| When | What receipts-wiki does |
|---|---|
| The session starts | Loads `~/.agents/AGENTS.md` into the session, capped at 8 KB, mentions lesson proposals waiting for review, and commits what earlier sessions left uncommitted (see the last row) |
| A memory file is read | Records the file's hash for this session |
| Before a memory write | Blocks the write if the file changed after this session read it, or if the text contains a secret value, injected system text or a relative date. Generated index files cannot be edited. The reason goes back to the agent. |
| Before a git command | Blocks commands that would remove or replace commits in the memory repository (`reset`, `rebase`, `commit --amend`, forced push, `filter-branch`, `update-ref`, `reflog expire`, `gc --prune`, forced branch moves) and points the agent to a forward correction or `git revert`. Other shell commands do not run this check. |
| Before a shell command that mentions the memory home | Blocks commands that write into it (redirects, `tee`, `sed -i`, `rm`, `mv`, `cp`, scripts that open files for writing) and points the agent to Write or Edit. Reading memory with shell commands stays allowed. A path held in a variable is not seen, which is why the end of the turn also records shell writes. |
| After a memory write | Notes the file in this session's log. Nothing is committed and nothing is printed, except a hint when a new note closely matches an existing one. |
| The agent's turn ends | Commits everything this session changed in memory during the turn as one commit, with reasoning lines taken from the notes (`Why:`, `Supersedes`, `Reopen if:`) and trailers for each change, the session, the turn and the receipts. Files changed by a shell command during the turn are included and marked `Shell-write`, and the agent is told at the next prompt to use Write or Edit. The regenerated indexes go into the same commit. Appends the turn's conversation text, redacted, to the session's archive file, and quotes short passages that read like rules or corrections as lesson candidates. Prints nothing, unless a commit fails or has to wait: then it shows you git's error at the end of every turn until the commit goes through. |
| The user sends a prompt | Commits the previous turn if its end hook did not run (an interrupt or an API error). At most every 10 minutes, also commits what other sessions left behind: writes idle for over an hour, credited to their own sessions, and changes made without hooks, as `external.change`. |

A turn that does not touch memory costs one short hook run and no commit. Nothing waits for the session to end, so a session can stay open for days across unrelated tasks.

On request, `python3 scripts/rw.py` gives `history <note>` (every commit of one note), `recall <words>` (search the conversation archive), `lint` (problems, forgetting candidates and pending proposals), `build-index`, `record --agent <name>` (commit changes made outside the hooks, such as an import), and `install-git-hook` (a git pre-commit check in the memory repository that blocks any commit staging a secret value or a note without a name and description, including commits made by other agents or by hand). The `lint-review` skill walks through the lint report with you and changes only what you approve.

There is no network access, telemetry, vector database or background model call. It needs git and Python 3.9 or later.

## Install

In Claude Code:

```
/plugin marketplace add B1aZer/receipts-wiki
/plugin install receipts-wiki@receipts-wiki
```

Then run `/receipts-wiki:setup` once. It shows what it found and what it would change, and writes only what you approve: the memory home, `autoMemoryDirectory` in your settings, transcript retention, and an optional copy of your existing per-project memory. Start a new session afterwards.

To try it without installing: `claude --plugin-dir /path/to/receipts-wiki`.

Other agents read the same rules through `AGENTS.md` (Codex: `ln -s ~/.agents/AGENTS.md ~/.codex/AGENTS.md`) and commit their own memory writes. Anything they leave uncommitted is recorded as `external.change` at the next catch-up in a Claude Code session. To use the hooks without the plugin system, see [docs/manual-install.md](docs/manual-install.md).

## The memory home

```
~/.agents/                  git repository, no remote
  AGENTS.md                 rules for every agent
  memory/                   Claude Code auto memory points here
    MEMORY.md               your text, plus a generated list of every note (of area indexes once memory is large)
    index-<area>.md         generated from note frontmatter
    <note>.md               one fact per file
  sessions/YYYY/MM/*.md     conversation archive, redacted, outside git
  proposals/*.md            lesson candidates waiting for review, outside git
  .state/                   read hashes and last-read dates, outside git
```

The history of a note is `git log -p -- memory/<note>.md`, or `rw.py history <note>`. The commit format is in [docs/COMMIT-SPEC.md](docs/COMMIT-SPEC.md).

## Why

Each rule in this method answers a failure that recent research on agent memory has measured. The papers below are arXiv preprints from 2025 and 2026, found by searching a local index of about 486,000 arXiv papers. In that index, work on memory that changes over time forms a cluster of 58 papers: at most one a month until March 2026, ten a month from May to July, and 18 in August. The numbers quoted are the authors' own; we have not reproduced them.

### Memories go out of date, and model-maintained memory misses it

On STALE, a benchmark of memories later invalidated by new information, the best evaluated model scored 55.2% at noticing and acting on the change ([arXiv:2605.06527](https://arxiv.org/abs/2605.06527)). On LongMemEval's knowledge-update questions, swapping a frontier model's full context for memory it maintains itself dropped accuracy from 92% to 77% ([arXiv:2606.27472](https://arxiv.org/abs/2606.27472)). When an LLM keeps rewriting a memory bank, its usefulness rises and then falls, sometimes below having no memory at all; even when consolidating from ground-truth solutions, GPT-5.4 failed 54% of a set of ARC-AGI problems it had previously solved without memory, while a control that simply kept the raw episodes stayed competitive. The authors conclude that raw episodes should be kept as first-class evidence ([arXiv:2605.12978](https://arxiv.org/abs/2605.12978)).

receipts-wiki leaves raw records where they are and has memory cite them. A correction rewrites one small file and adds a `Supersedes` line with the date and the evidence, and git keeps the previous version. No model merges new material into existing pages.

### Wrong memories spread

Agents tend to repeat the output of a retrieved memory whose input resembles the current task, so errors in stored experience propagate into later work ([arXiv:2505.16067](https://arxiv.org/abs/2505.16067)). In a study of permissions held in memory, memory writers recorded false authority for up to 50.2% of unauthorized requests, and executors acted on it in 98.6% of trials. Requiring stored permissions to be backed by valid source events reduced this, at the cost of rejecting more legitimate actions ([arXiv:2609.01836](https://arxiv.org/abs/2609.01836)).

receipts-wiki requires project and decision facts to cite their source (a commit, run, query or file), and tells agents to check files, flags and numbers before relying on a memory.

### Memory is an attack and leak surface

A single adversarial memory write can influence an agent long afterwards, and existing prompt-injection defenses do not cover memory poisoning ([arXiv:2606.04329](https://arxiv.org/abs/2606.04329)). Attackers can plant such records through ordinary queries ([arXiv:2503.03704](https://arxiv.org/abs/2503.03704)). Once a poisoned document's provenance was lost, attribution systems blamed the model in all 64 documented failures ([arXiv:2605.22842](https://arxiv.org/abs/2605.22842)). Extraction attacks on agent memory reach up to 100% success ([arXiv:2604.09747](https://arxiv.org/abs/2604.09747)). A survey of the area concludes that memory security has to be anchored in storage-time provenance, versioning and retention policy ([arXiv:2604.16548](https://arxiv.org/abs/2604.16548)).

receipts-wiki blocks common secret formats before they reach memory, and every change is a commit that names the session which wrote it, so a bad entry can be traced after the fact. It does not detect poisoning.

### More context is not better

Even when models retrieved all the relevant information, performance fell by 13.9% to 85% as input length grew, while staying well within the models' claimed context limits ([arXiv:2510.05381](https://arxiv.org/abs/2510.05381)).

receipts-wiki keeps the generated note list in `MEMORY.md`, which Claude Code loads at session start, within a budget of 150 lines and 17 KB. When the list would not fit, it lists one index per area instead. Topic files are opened only when a task needs them.

### Shared memory needs scope, supersession and provenance

A study of a production multi-agent memory service names four failure modes: unauthorized leakage, stale propagation, contradiction persistence and provenance collapse. Its answers are scoped retrieval, temporal supersession, provenance tracking and policy-governed propagation ([arXiv:2606.24535](https://arxiv.org/abs/2606.24535)).

receipts-wiki gives every agent one home, scopes reading through the generated note list and area indexes, records supersession explicitly, and gets provenance from git. It has no access control: every agent you point at the home can read all of it.

### Memory quality has no agreed measure yet

Agents that nearly saturate the LoCoMo memory benchmark perform poorly on interdependent multi-session tasks ([arXiv:2602.16313](https://arxiv.org/abs/2602.16313)), and higher final accuracy does not imply better memory, since many methods gain accuracy while forgetting substantially ([arXiv:2605.15384](https://arxiv.org/abs/2605.15384)).

receipts-wiki makes no general accuracy claim. It ships an update-correctness eval ([evals/update_correctness](evals/update_correctness/run.py)) that compares plain auto memory with receipts-wiki on corrections, stale premises and history questions, and it keeps what a deeper evaluation would need: the conversation archive, versioned memory and the receipts behind each claim.

## Results so far

The update-correctness eval ran once on 2026-09-14: 6 scenarios, each with three `claude -p` sessions (teach, correct, ask), the same model and prompts in both arms, and answers graded by fixed strings. One run per scenario is a small sample, so read the timings as rough.

| | Plain auto memory | receipts-wiki |
|---|---|---|
| Correct answers | 16/16 | 16/16 |
| Old value and evidence still in memory | 6/6 | 6/6 |
| Time, 18 sessions | 336 s | 365 s |
| Output tokens | 17,196 | 18,915 |
| Cost | $1.91 | $2.02 |
| Model turns | 78 | 52 |
| Superseded notes deleted with `rm` | 2 | 0 |
| Commits recording the changes | none | 12, each naming its session and turn |

These scenarios are too easy to separate the two on correctness. Plain auto memory answered every question too, and when it deleted a superseded note, it restated the old value in the new one. What receipts-wiki adds in this run is the record: a dated `Supersedes` line in the note, a commit for each change that names the session and turn, and no deleted notes. The eval does not yet test chains of corrections, where that record would matter more.

An earlier run of the same eval took 58% more time than plain auto memory. Its transcripts showed agents searching the memory folder with shell commands that Claude Code blocked, and deleting notes outside the hooks. The fixes are in [CHANGELOG.md](CHANGELOG.md).

## How it relates to other approaches

The LLM Wiki pattern and its implementations, such as [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) and [astro-han/karpathy-llm-wiki](https://github.com/astro-han/karpathy-llm-wiki), build knowledge from sources you ingest. receipts-wiki keeps that loop for work memory and adds receipts per claim, recorded corrections, one home for all agents, generated index budgets and write-time checks. It avoids having a model merge new material into existing pages, the approach behind two problems in llm_wiki's own tracker: an ingest prompt of 1,723,391 tokens against a 524,288-token context ([#706](https://github.com/nashsu/llm_wiki/issues/706)) and duplicate pages for the same entity ([dedup.ts](https://github.com/nashsu/llm_wiki/blob/main/src/lib/dedup.ts)).

Claude Code's auto memory stays the loader. receipts-wiki points it at a shared folder, versions that folder, checks writes, and gives other agents the same rules through `AGENTS.md`.

## Limitations

- The gate matches patterns. It catches common secret formats, injected system tags and relative dates, not every secret or every stale claim. Nothing detects memory poisoning.
- Claude Code already refuses a Write to a file that changed since the session read it. In a test where another session edited a note right after the agent's read, that built-in check caught the stale write before the receipts-wiki gate did. The gate's stale-read check is a second line, not the first.
- The history guard reads the git commands an agent types. A script or another program that rewrites history is not caught, and a user can always rewrite history outside the agent. The guard also refuses when the user asks for a reset: in a test session, an agent asked to run `git reset --hard HEAD~1` on memory ran it despite the rule in AGENTS.md, so the rule is enforced by the hook instead.
- Related-note hints use word overlap, appear only when a new note closely matches an existing one, and only suggest. They cannot tell "use X" from "do not use X".
- Lesson candidates are picked by phrases such as "from now on" or "never". They miss rules phrased other ways and include false alarms.
- There is no access control: every agent pointed at the home can read all of it.
- Search is plain text matching over notes and the archive, without embeddings.
- Hooks run in Claude Code only. Other agents follow the rules by instruction, and their changes are recorded with less detail.
- Claude Code's own memory instructions may still add pointer lines to `MEMORY.md`, which can duplicate the generated block.
- Session titles and conversation text come from Claude Code's transcript format, which is not a documented interface.
- When a turn's end hook does not run, for example because the process was killed, its changes are committed at the session's next prompt, or by another session after an hour without activity, and marked `Recovered: true`. Until then they are only on disk.
- The conversation archive can lag one turn behind, because Claude Code may still be writing the last message when the end-of-turn hook reads the transcript.
- One person has used it since 2026-09-13. There are no long-term results yet.

## Security

- Keep secret values out of every layer: memory, indexes and `AGENTS.md`. Names and locations of secrets are fine.
- The memory repository has no remote. If you add one, scan the full history for secrets before the first push. Notes written before you adopted receipts-wiki may contain them; ours did.
- Commits are local, and nothing is sent anywhere.
- The conversation archive and lesson proposals stay outside git, so a secret that slips through redaction can be removed by deleting one file.
- Check what your tools save when you approve commands. Claude Code stored approved commands, including passwords typed inline, in `settings.json`.

## Prior work and credits

- Andrej Karpathy, [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): the pattern this extends.
- [letta-code](https://github.com/letta-ai/letta-code): git-backed memory with a `MEMORY.md` index, frontmatter and pre-commit limits.
- [total-recall](https://github.com/davegoldblatt/total-recall): superseded markers and a write gate.
- [Graphiti](https://github.com/getzep/graphiti): invalidating facts instead of deleting them.
- [episodic-memory](https://github.com/obra/episodic-memory): conversation archives with line-level provenance.
- [agentmemory](https://github.com/rohitg00/agentmemory): the first fourteen secret patterns in `scripts/rwlib/secrets.py` (Apache-2.0).
- [Contextual Commits](https://github.com/berserkdisruptors/contextual-commits): reasoning lines in commit bodies.
- ChronoMem ([arXiv:2607.27773](https://arxiv.org/abs/2607.27773)) and Git Context Controller ([arXiv:2508.00031](https://arxiv.org/abs/2508.00031)): versioned agent memory.
- [AGENTS.md](https://agents.md) and GitHub's [agents.md guide](https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/): the shared instructions format and the Always, Ask first and Never structure.
- Claude Code [memory](https://code.claude.com/docs/en/memory) and [hooks](https://code.claude.com/docs/en/hooks) documentation.

## License

Code, hooks, skills and templates are MIT, see [LICENSE](LICENSE). The prose (`README.md`, `IDEA.md`, `EXAMPLES.md`, `CHANGELOG.md` and `docs/`) is CC BY 4.0, see [LICENSE-docs](LICENSE-docs). `scripts/rwlib/secrets.py` includes patterns from agentmemory under the Apache License 2.0.
