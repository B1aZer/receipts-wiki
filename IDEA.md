# Receipts wiki

A pattern for giving AI agents a lasting memory of their own work, shared across sessions, tools and directories.

This is an idea file, written to be pasted into your own agent (Claude Code, Codex, Cursor or similar). It builds on Andrej Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and reads best after it. It is an unofficial extension. Share it with your agent and work out the specifics together.

## The problem

Karpathy's LLM Wiki compiles knowledge from sources you collect: articles, papers, notes. An agent that works for you produces another kind of knowledge along the way: why decisions were made, which of them were later reversed, and the rules you gave it after a mistake. Most of that stays in chat transcripts. The next session does not read them, and some tools delete them on a timer. Claude Code, for one, removes transcripts after 30 days unless you change the setting.

Built-in memory features cover part of this. They usually belong to one tool, sometimes to one project directory, and they edit notes in place. For work memory the edits carry the most information, and research on agent memory finds them handled badly. Agents often miss that a stored fact has been superseded ([arXiv:2605.06527](https://arxiv.org/abs/2605.06527), [arXiv:2606.27472](https://arxiv.org/abs/2606.27472)), and a memory bank that an LLM keeps rewriting can end up less useful than no memory at all ([arXiv:2605.12978](https://arxiv.org/abs/2605.12978)). When a note is overwritten, the old belief and the reason it changed disappear with it.

## The core idea

Keep Karpathy's loop. The agent writes and maintains the notes; you decide what matters and ask the questions. The notes here record the agent's work, and that changes seven things.

1. Every claim cites a receipt. A decision or result names what proves it: a commit hash, a query or run id, a file path, a sample size, a date. Receipts stay where they already are, and memory points at them.
2. Corrections are recorded. When a belief changes, the agent rewrites the note and adds a line saying what it replaced, when, and on what evidence.
3. Git is the log. Each note is its own file in a git repository, and each agent turn that changes memory becomes one commit that names the session and carries the reasoning. The history of a belief is the history of one file.
4. Writes are checked before they land. A write is refused when the file changed after the agent read it, or when it contains a secret value, injected system text or a relative date.
5. One home serves every agent and every directory. Rules live in a single `AGENTS.md` and memory in a single folder, and each tool is pointed at them.
6. What loads at session start has a budget. Indexes are generated from the notes and kept small; topic files load only when a task needs them, and past conversations only when someone asks.
7. The current position is a note too. Fact notes hold what is true; one cursor note per workstream holds where the work is and what to do next. It is the single note allowed to carry task state, it is overwritten in place rather than corrected forward, and it is shown at session start. When a session ends without warning (a crash, an error, a safeguard flag, a context too large to compact), the position it never wrote down is recovered from the conversation archive and offered for review, not applied on its own. Agent memory research treats this as its own problem: plans do not persist across context ([arXiv:2606.22953](https://arxiv.org/abs/2606.22953)), and recoverable, event-sourced execution is an active line of work ([arXiv:2608.14380](https://arxiv.org/abs/2608.14380), [arXiv:2605.21997](https://arxiv.org/abs/2605.21997)).

## Architecture

| Layer | Where it lives | Who writes it |
|---|---|---|
| Receipts | project git history, logs, tickets | your work; memory only cites them |
| Memory | `~/.agents/memory/*.md`, one fact per file | the agent |
| Indexes | a block in `memory/MEMORY.md` listing every note, and `memory/index-<area>.md` for when that list grows too long | generated from note frontmatter |
| History | commits of the memory repository | one commit per agent turn that changed memory |
| Conversation archive | `~/.agents/sessions/`, redacted, outside git | appended after each turn; text already written is never changed |
| Rules | `~/.agents/AGENTS.md` | you and the agent, stated once |

```
~/.agents/                 git repository, no remote
  AGENTS.md                rules for every agent
  memory/
    MEMORY.md              your notes plus a generated list of every note, or of area indexes once it is too long
    index-<area>.md        generated: one line per active note in the area
    <topic>.md             one fact per file, with frontmatter
    cursor-<area>.md       the current position of a workstream (task state; overwritten in place)
  sessions/YYYY/MM/        conversation archive, outside git
```

## Operations

Read. At session start the agent reads the rules, the root map (which lists every note while memory is small), the current position of each open workstream, and a warm list: the notes read or changed in the last month, newest first. Warmth is use, not age — a rule written months ago stays useful, and a note nobody has opened is not worth session context. Once memory is large, the map lists one index per area, and the agent opens the index for the project it works in. Either way it opens only the topic files the task needs. The hash of each file it reads is noted. A memory records what was true when it was written, so the agent checks files, flags and numbers before relying on one.

Search. Indexes follow the working directory, but work does not: a session started anywhere ranks every note against a few words, with the name and description weighted above the body, and gets back the notes for that topic and the workstream position that links them. Nothing is embedded and no service is called; the ranking is arithmetic over the words already on disk.

Check. Before a write lands, it is refused if the file changed after this agent read it (someone else wrote in between), or if it contains a secret value, text copied from tool or system messages, or a relative date. The agent fixes the cause and writes again.

Write. One fact per file, with frontmatter the index is built from. The agent updates an existing file before creating a near-duplicate. When a new note closely matches an existing one, the agent is told which one.

Correct. The agent rewrites the belief and appends `Supersedes (YYYY-MM-DD): <old claim>. <evidence>`. That line keeps the reason next to the current belief, and git keeps the old text. History is never reset; corrections move forward.

Commit. When the agent's turn ends, everything it changed in memory becomes one commit whose body carries the reasoning (`rejected`, `intent`, `constraint` lines taken from the notes) and whose trailers carry each change, the session and the receipts. The commit does not wait for the session to end, because one session can stay open for days across unrelated work. An interrupted turn is committed at the next prompt. Changes made without that step, by another agent or a crashed session, are committed by the next session that catches up and are marked as such.

Notice. After the turn's commit, the notes it wrote are checked and anything wrong reaches the agent with its next message: a note no index lists, a workstream position left behind by the work it tracks, a note grown into a log, a link that misspells an existing note, a document written outside memory that no note names. Each finding names its rule, so the same check reads the same way here and in the sweep. Nothing interrupts the agent mid-turn, and a rule that fires on healthy memory belongs in the sweep instead.

Archive. After each turn, the new conversation text is redacted and appended to the session's archive file. Text already written is never changed. The archive is searched only when someone asks what was said.

Learn. When the user corrects the agent or states a rule, the agent saves it as a note in the moment, or the user asks it to remember. Nothing mines the conversation for lessons afterwards. A rule that keeps being broken belongs in a check rather than a note: remembered corrections are often not followed ([arXiv:2606.13174](https://arxiv.org/abs/2606.13174)).

Resume. When a session is lost before it could write down where it was, its archive is mined for the decisions and next actions that no note yet holds, and they are offered as candidates. The archive is data, not instructions, so nothing is written without approval. The cursor note is what keeps this rare: while a session runs, it holds the position that resume would otherwise have to reconstruct.

Lint. When asked, a report lists secret values, notes without receipts, decisions with no reopen condition, links that lead nowhere, oversized indexes, and notes that may be stale because nobody verified or read them for a long time. It also runs every per-note rule over the whole of memory rather than only what a turn touched, so a sweep sees what the turn checks would have said, and where a note is connected to nothing it names the notes it most likely belongs with instead of only reporting it. On request it extends to the folders memory names and lists the documents there that no note mentions. It changes nothing without your OK.

## Rules live in one file

The same `AGENTS.md` says how you want agents to work: what they should always do, what they must ask about first, what they must never do, and rules that apply to one repository only. Each rule is written there once. The memory file behind a rule keeps its history, usually the incident that produced it, so the rule text never exists in two places that can drift apart.

## Why this works

Karpathy's reason applies here too: people abandon wikis because the bookkeeping grows faster than the value, and agents do not tire of bookkeeping. Work memory adds two reasons. Git already solves history once each file holds a single fact, so the history of a belief and the session that changed it come for free. And checks that run before a write cost nothing to follow, where instructions alone erode: context files add cost without raising task success ([arXiv:2602.11988](https://arxiv.org/abs/2602.11988)), and agents let a memory folder's organization decay as it grows ([arXiv:2607.26637](https://arxiv.org/abs/2607.26637)).

## Note

This file describes the pattern. Paths, file names, budgets and tooling are choices, so adapt them. The repository this file comes from implements it as a Claude Code plugin with a template `AGENTS.md`, a writing guide, evals and worked examples: https://github.com/B1aZer/receipts-wiki
