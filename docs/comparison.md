# How receipts-wiki compares

Three things get called agent memory. They fail differently, so it is worth separating them.

1. **Snippet capture with retrieval.** Session transcripts are cut into snippets, embedded, and the nearest few injected on every prompt, usually with a search tool for more. Most installed memory plugins are this.
2. **A document brain.** The agent writes Markdown as it works — specs, decisions, research, indexes — consults it before working and updates it afterwards. No embeddings, no retrieval.
3. **This.** A document brain where every remembered fact must cite the evidence behind it, the rules are enforced by hooks rather than asked for, and git is the log.

receipts-wiki argues with the first and builds on the second.

## The field has started agreeing about the second

This is not a lone position any more, and the agreement arrived from several directions at once. Andrej Karpathy's [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) is the pattern receipts-wiki extends. [letta-code](https://github.com/letta-ai/letta-code) keeps git-backed memory with a `MEMORY.md` index. [operator-memory](https://github.com/aerovato/operator-memory) (BSD-3, public since 2026-08-16) reaches the same conclusion independently and states it well in [*Agents Don't Need Memory. They Need Documentation.*](https://liao.gg/blog/agents-dont-need-memory) (2026-10-03): a brain of Markdown, deterministic loading, maps instead of rankings, `prompt → consult → build → update`. Where it disagrees with retrieval-based memory, read it as a second opinion on this page.

## Why retrieval-based memory fails, with the measurements

The arguments against snippet-and-retrieve memory are usually made from first principles. They also happen to be measured, and the numbers are the authors' own; we have not reproduced them.

- **Similarity does not know what is current.** Embedding retrieval scored 0.30–0.95 on facts that had been updated, against 0.70–1.00 for stores that update the fact at write time ([2609.05441](https://arxiv.org/abs/2609.05441)). An obsolete decision and its replacement rank side by side.
- **Supersession is the measured weak point.** On STALE, a benchmark of memories later invalidated, the best evaluated model scored 55.2% at noticing and acting on the change ([2605.06527](https://arxiv.org/abs/2605.06527)). Swapping a frontier model's full context for memory it maintained itself dropped knowledge-update accuracy from 92% to 77% ([2606.27472](https://arxiv.org/abs/2606.27472)).
- **Letting a model rewrite the store makes it worse.** Usefulness rises then falls, sometimes below having no memory at all; even consolidating from ground-truth solutions, one model failed 54% of a set of problems it had previously solved without memory, while a control that simply kept the raw episodes stayed competitive. The authors conclude raw episodes should be kept as first-class evidence ([2605.12978](https://arxiv.org/abs/2605.12978)).
- **Wrong memories spread.** Agents repeat the output of a retrieved memory whose input resembles the current task, so errors in stored experience propagate ([2505.16067](https://arxiv.org/abs/2505.16067)). In a study of permissions held in memory, writers recorded false authority for up to 50.2% of unauthorized requests and executors acted on it in 98.6% of trials; requiring stored permissions to cite valid source events reduced it ([2609.01836](https://arxiv.org/abs/2609.01836)).
- **More retrieved context is not better context.** Even when models were given all the relevant information, performance fell 13.9% to 85% as input length grew, well inside the claimed context limits ([2510.05381](https://arxiv.org/abs/2510.05381)).
- **Files beat retrieval for this job.** Files plus a coding agent scored 72.5% against 48.5% for RAG ([2605.12493](https://arxiv.org/abs/2605.12493)), and searching a complete history on demand gained 18 points while using 4.2–5.8x fewer tokens ([2607.20064](https://arxiv.org/abs/2607.20064)).
- **And where search is wanted, words are enough.** An agent with only keyword search reached over 90% of vector-database RAG ([2602.23368](https://arxiv.org/abs/2602.23368)); lexical retrieval is the strongest scalable default and overtakes agentic file exploration as a corpus grows ([2607.26497](https://arxiv.org/abs/2607.26497)); dense retrieval pays least in exactly the name-heavy regime a work memory is ([2606.04194](https://arxiv.org/abs/2606.04194)). `find` is BM25 over the notes: 0.17 s across 203 of them, no embeddings, no service.

## What receipts-wiki adds to a document brain

A document brain fixes retrieval. It does not, by itself, fix three other things.

**Receipts.** A note states a fact and cites what settles it: a commit, a run, a query, a file and line, a transaction, a URL, or `user statement` when that is genuinely all there is. The lint sweep warns on a project note that cites nothing anywhere in it, and each commit copies the citations into a `Receipts:` trailer. This exists because provenance is the measured gap: requiring stored claims to cite source events is what reduced authorization laundering above ([2609.01836](https://arxiv.org/abs/2609.01836)), and a survey of the seven most-installed memory skills on 2026-09-14 found none of them tracking provenance at all. A document you cannot question is still a document you have to trust.

**Enforcement by hooks, not by instruction.** Every document-brain design asks the agent to consult and update. Rule-following degrades as rules multiply ([2509.21051](https://arxiv.org/abs/2509.21051)) and agent-kept organization erodes over time ([2607.26637](https://arxiv.org/abs/2607.26637)), so here the asking is backed by gates: a write is refused if the file changed after this session read it, if it carries a secret value, an injected system tag or a relative date; commands that would rewrite memory history are refused; shell writes into the memory home are refused and pointed at the editor; and what a turn changed is committed at the end of that turn, with the reasons taken from the note. The one rule we tested by instruction alone did not hold — an agent asked to run `git reset --hard HEAD~1` on memory ran it despite the rule in `AGENTS.md`, which is why the guard is a hook.

**Git as the log, and a position that survives a crash.** Corrections are forward-only: a small file is rewritten, a `Supersedes` line records the date and the evidence, and the previous version stays in git. `history` shows how one note changed; `changes` joins each change to the conversation turn that made it. A `cursor` note holds where a workstream stands and what finishes it, so a session that dies without warning loses a position that is written down rather than one that has to be reconstructed.

**The conversation archive is a recovery log, not a retrieval source.** This needs saying plainly, because an archive of past sessions is the thing snippet-and-retrieve memory is built on. Nothing in it is ever injected into a prompt. It is read only when a person asks, by `recall` (search it) or `resume` (recover a lost session's decisions and next actions, which are then drafted with you, never applied automatically), it is treated as untrusted data when read, it lives outside git so a file can be deleted outright, it is redacted on write, and unattended runs (`claude -p`, SDK) archive nothing at all. Automatic injection of archived history has been on the refused list since the first commit, and the reason is measured: with memory access, three of four models misused sensitive history at 51–83 out of 100 ([2606.06055](https://arxiv.org/abs/2606.06055)). Keeping the record and keeping it out of the context window are two different decisions, and this makes them separately.

## Side by side

| | Snippet capture + RAG | Document brain | receipts-wiki |
|---|---|---|---|
| What is stored | extracted snippets | documents | documents, one fact per file |
| How it reaches the model | top-k by similarity, every prompt | maps, read on demand | maps, read on demand |
| Embeddings, background daemons | yes | no | no |
| Evidence behind a claim | — | — | required, cited, in the commit |
| Who enforces the rules | — | the agent, asked | hooks, which refuse |
| Correcting a fact | a competing record | edit in place | edit in place, `Supersedes`, kept in git |
| Who changed it and why | — | your repo's history | a commit per turn, naming session, turn and reasons |
| Past conversations | the retrieval corpus | not kept | kept, never injected, read on request |
| Position after a crash | — | gone unless documented | `cursor` note, plus `resume` from the archive |

## What this does not do

- **It does not map your code.** A document brain can carry a codebase index; this one carries knowledge and rules. The nearest thing here is `lint --docs`, which lists documents in the folders memory names that no note mentions.
- **No team partitions.** One home, no remote, no access control: every agent pointed at it reads all of it. A brain committed alongside a repository for a team is an open design question, not a feature.
- **Enforcement is Claude Code only.** Other agents read the same rules through `AGENTS.md` and commit nothing of their own; their changes are recorded as `external.change` at the next catch-up.
- **No poisoning detection.** Write-time filtering catches common secret formats and injected system tags. A plausible, well-formed, wrong note passes, and the defence is that it is one small file with a commit naming who wrote it.
- **One person, since 2026-09-13.** The evals are in [`evals/`](../evals/) and what they show, including where they show no difference, is in the README and `CHANGELOG.md`. There is no long-term or multi-user result.

## Choosing

If you want an agent that understands a codebase and documents it as it works, operator-memory is a complete answer to that and supports six harnesses. If what you need is a record you can audit — every fact citing its evidence, every change a commit naming the session that made it, corrections that keep what they replaced, and rules that hold because a hook refuses rather than because the agent remembered — that is what this is for. The two disagree about very little.
