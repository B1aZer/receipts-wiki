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

## 7. What a session is handed at its start

```
Rules from /home/you/.agents/AGENTS.md, loaded by receipts-wiki:
...

Where things stand (open the cursor note for the area you're working in):
- cursor-api: quotes TTL shipped; NEXT = watch the stale-quote sample for a week

Worked on lately (read or changed in the last 30 days; everything else is reached
through the area index or `receipts-wiki find <words>`):
- [quotes-cache-ttl](memory/project_quotes_cache_ttl.md) (today): /quotes cache TTL is 5 minutes; stale-price sample 2026-09-02
- [partner-rate-limit](memory/project_rate_limit.md) (3d ago): partner API allows 500 requests per minute
```

The area index for the working directory is loaded alongside these. Warmth is use, not age: a note nobody has opened is not listed, and is still reached by its index or by search.

## 8. Finding notes from another directory

```console
$ receipts-wiki find quotes cache stale --limit 2
 24.1  /home/you/.agents/memory/project_quotes_cache_ttl.md
       project, area api, matched: cache, quotes, stale
       /quotes cache TTL is 5 minutes; stale-price sample 2026-09-02
 11.6  /home/you/.agents/memory/project_cdn_maxage.md
       project, area api, matched: cache, stale
       CDN max-age on /quotes was the real source of stale prices (2026-09-05)

Cursor for this work: /home/you/.agents/memory/cursor_api.md: quotes TTL shipped; NEXT = watch the stale-quote sample for a week
```

`--json` returns the same ranking as data, for an agent to parse rather than read.

## 9. What the checks say after a turn

The agent is told at its next prompt, never mid-turn, and each finding names its rule:

```
receipts-wiki: cursor-not-updated: you changed memory/project_quotes_cache_ttl.md, which cursor note
memory/cursor_api.md points to, but not the cursor. It still says: "TTL change not shipped; NEXT = ship it".
If that is no longer where the work stands, rewrite the cursor in place.

receipts-wiki: doc-unnamed: your last turn created /home/you/src/api/docs/cache-design.md, and no memory
note names it. If a later session should find one, add a line naming the file and what it holds to the note
for that work (`receipts-wiki find <topic>` shows which note); skip scratch files.
```

## 10. The lint report

```console
$ receipts-wiki lint --docs
# receipts-wiki lint: /home/you/.agents

Report only; nothing was changed.

## Problems (1)

- memory/vendor_keys.md contains a secret value (key or token assignment)

## Warnings (2)

- memory/project_old_pricing.md is a project note without receipts
- memory/project_sniping.md says not to revisit a decision but has no 'Reopen if:' line

## Rules over every note (3)

**doc-unnamed** — document in a folder memory names that no note names (1 in 1 folders)
- /home/you/src/api/docs: cache-design.md

**note-too-big** — note over the size budget, so it reads as a log rather than a fact (1)
- memory/project_incidents.md is 19 KB, over the 12 KB note budget, so it reads as a log. Keep the current belief at the top and move finished or separate facts into their own notes.

**orphan-note** — note with no [[link]] in or out: nothing in memory connects it to anything (sweep only) (1)
- memory/project_cdn_maxage.md has no [[link]] in or out, so nothing in memory connects it to related work. Link it from the notes it belongs with, or link them from it. Closest notes by wording: [[quotes-cache-ttl]].

## Forgetting candidates (1), retire only with the owner's approval

- memory/project_old_pricing.md: last verified 2026-03-02 (196 days ago)
```

The rules section applies the end-of-turn checks to every note, not just the ones a turn wrote, so a sweep catches what predates the check. `--docs` adds the folders memory names; without it, lint stays inside the memory home. The report never prints a secret value, and `lint-review` goes through it item by item and applies only the changes you approve.
