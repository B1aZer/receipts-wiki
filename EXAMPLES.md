# Examples

What receipts-wiki produces at each step. The project, numbers and ids are made up; the formats are the ones the plugin writes.

## 1. Saving a decision

You say: "Remember that we cut the quotes cache to 5 minutes, and why."

The agent writes `~/.agents/memory/project_quotes_cache_ttl.md`:

```markdown
---
name: quotes-cache-ttl
description: /quotes cache TTL is 5 minutes; stale-price sample 2026-09-02
metadata:
  type: project
  area: api
  last_verified: 2026-09-02
  receipts: [query:q_8812, commit:a1b2c3d]
---

The /quotes response cache TTL is 5 minutes.

Why: at 60 minutes, 14 of 200 quotes sampled on 2026-09-02 used a price older than the last trade.
How to apply: re-run the stale-price sample before raising the TTL.
```

When the agent's turn ends, the hook commits the note together with the indexes it changed:

```
memory(api): add quotes-cache-ttl

intent(quotes-cache-ttl): at 60 minutes, 14 of 200 quotes sampled on 2026-09-02 used a price older than the last trade.

Change: fact.added memory/project_quotes_cache_ttl.md
Change: index.rebuilt memory/index-api.md
Change: index.rebuilt memory/MEMORY.md
Agent: claude-code
Session: 00000000-0000-0000-0000-000000000001
Turn: 11111111-1111-1111-1111-111111111111
Cwd: /home/you/src/api
Transcript: /home/you/.claude/projects/-home-you-src-api/00000000-0000-0000-0000-000000000001.jsonl
Receipts: query:q_8812, commit:a1b2c3d
```

If the agent had written three notes in that turn, the commit would list three `Change` lines. Both `memory/index-api.md` and the generated block in `memory/MEMORY.md`, which Claude Code loads at session start, now contain:

```markdown
- [quotes-cache-ttl](project_quotes_cache_ttl.md): /quotes cache TTL is 5 minutes; stale-price sample 2026-09-02
```

## 2. Correcting it

Three days later you say: "The TTL change didn't fix it. The stale quotes come from the CDN."

The agent rewrites the belief:

```markdown
Stale quotes came from the CDN edge cache (max-age 3600 on /quotes). The API cache TTL stays at 5 minutes.

Supersedes (2026-09-05): the 60-minute API cache TTL caused stale quotes. 12 of 200 quotes were still stale at a 5-minute TTL (query q_8840)
```

The commit records what was rejected and why:

```
memory(api): supersede quotes-cache-ttl

rejected(quotes-cache-ttl): the 60-minute API cache TTL caused stale quotes; 12 of 200 quotes were still stale at a 5-minute TTL (query q_8840)

Change: fact.superseded memory/project_quotes_cache_ttl.md
...
```

## 3. Blocked writes

The gate refuses a write and tells the agent why. Three of the messages it returns:

```
receipts-wiki blocked this write to memory/db.md: it contains a secret value (inline password); store the secret's name or location, never its value.

receipts-wiki blocked this write to memory/deploy.md: it uses a relative date ('yesterday'); write an absolute date such as 2026-09-14.

receipts-wiki blocked this write to memory/project_quotes_cache_ttl.md: the file changed after this session read it; read it again and decide whether your change still applies.
```

The third happens when two sessions work on the same note: the second writer has to read the first writer's change before it can write.

## 4. The history of a belief

```console
$ python3 scripts/rw.py history quotes-cache-ttl
# History of memory/project_quotes_cache_ttl.md

3f1c2aa 2026-09-02 memory(api): add quotes-cache-ttl
intent(quotes-cache-ttl): at 60 minutes, 14 of 200 quotes sampled on 2026-09-02 used a price older than the last trade.
Change: fact.added memory/project_quotes_cache_ttl.md
...
9b7e410 2026-09-05 memory(api): supersede quotes-cache-ttl
rejected(quotes-cache-ttl): the 60-minute API cache TTL caused stale quotes; 12 of 200 quotes were still stale at a 5-minute TTL (query q_8840)
Change: fact.superseded memory/project_quotes_cache_ttl.md
...
```

Add `--patch` for the diffs. Plain git works too: `git -C ~/.agents log -p -- memory/project_quotes_cache_ttl.md`.

## 5. What was said in an earlier session

You ask: "What exactly did I say about the CDN?" The `recall` skill runs:

```console
$ python3 scripts/rw.py recall cdn stale quotes
## sessions/2026/09/00000000-0000-0000-0000-000000000002.md (Stale quotes root cause, session 00000000-0000-0000-0000-000000000002)
2026-09-05T10:12:03Z user (line 41)
The TTL change didn't fix it. The stale quotes come from the CDN, check the max-age header on /quotes.
```

The archive holds only the conversation text, with secrets redacted and tool output left out. It is never loaded into a session unless someone asks.

## 6. A change made by another agent

Codex edits a note. It has no hooks, so nothing is committed at that moment. The next Claude Code session to catch up, at its start or at a prompt (at most every 10 minutes), records it:

```
memory(api): record quotes-cache-ttl

Change: external.change memory/project_quotes_cache_ttl.md
Agent: unknown
```

A Claude Code turn whose end hook did not run, for example after an interrupt, is committed at that session's next prompt with its own `Session` and `Turn` trailers and `Recovered: true`.

## 7. A lesson candidate

During a session you wrote: "From now on never raise a cache TTL without re-running the stale-price sample." When that turn ends, `~/.agents/proposals/<session>.md` contains:

```markdown
## 2026-09-05T10:20:44Z (line 57)

> From now on never raise a cache TTL without re-running the stale-price sample.

Receipt: session:00000000-0000-0000-0000-000000000002#L57
```

The next session mentions it at start; a session that stays open mentions it at most once a day. `lint-review` drafts a feedback note from it with `source: proposal` and the session receipt, shows it to you, and writes it only after you approve. Its commit event is `proposal.accepted`.

## 8. The lint report

```console
$ python3 scripts/rw.py lint
# receipts-wiki lint: /home/you/.agents

Report only; nothing was changed.

## Problems (1)

- memory/vendor_keys.md contains a secret value (key or token assignment)

## Warnings (2)

- memory/project_old_pricing.md is a project note without receipts
- memory/project_sniping.md says not to revisit a decision but has no 'Reopen if:' line

## Forgetting candidates (1), retire only with the owner's approval

- memory/project_old_pricing.md: last verified 2026-03-02 (196 days ago)

## Lesson proposals waiting (1)

- proposals/00000000-0000-0000-0000-000000000002.md
```

The report never prints a secret value. `lint-review` goes through it item by item and applies only the changes you approve.
