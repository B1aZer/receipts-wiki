# Patch record for the plugin cache

⚠️ **This file is written and committed BEFORE any file under the plugin cache is copied, never after.**
A patched tree's content no longer matches the `gitCommitSha` the host records for it, so without this
file the install record claims a session is running a commit whose files it does not have. Every receipt
this project issues rests on that field, which is the whole reason the order is fixed: the record first,
then the copy, then the verification against the record.

**Status: copy 1 of 2 DONE and verified. Copy 2 outstanding.**

**Copy 1** — the owner ran it on 2026-10-14 after approving it with its three costs stated; the session
that wrote this record is denied the write itself ("Modify Shared Resources" from the auto-mode
classifier) and did not route around it. **Verified independently afterwards, read-only: 10 of 10 targets
hash `864112d320f46bf5a506ae3964a7a4ee`, the value this record committed to BEFORE the copy; 0 mismatched;
0 still carrying the leaky `9d842ec571af8599783392a02f7480bb`.** The live leak is closed in all ten.

⚠️ **Copy 1 also broke SessionStart in all ten trees, and that is a defect introduced by this
remediation.** The fixed `watch.py` renamed `last_reasons` to `last_moved`; the ten trees keep their own
older `hooks.py`, whose `_cursor_pointers` still calls the old name. Reproduced against a patched tree
with the fixed tree as a working control:

```
receipts-wiki session-start hook failed: module 'rwlib.watch' has no attribute 'last_reasons'
```

**Why the pre-flight missed it:** the compatibility check ran *new file → old tree* (can the new
`watch.py` find what it needs?) and never *old tree → new file* (can the old callers find what they ask
for?). One direction of a two-directional question. The smoke test compounded it by exercising only
`hook prompt`, which never reaches the cursor-pointer path.

**Who it reaches, which is why it is urgent rather than cosmetic.** A *restart* is safe: it rebinds to the
installed tree, where both files match. But **SessionStart also re-fires on compaction and on `/clear`**,
against the session's existing bound tree — so any still-running session on a patched tree that compacts
or clears **loses its whole memory orientation** (rules, cursor pointers, area index) and continues
without it, with only a `systemMessage` to say so. Compaction is routine, not a corner case.

**Copy 2 fixes it with an alias, not a revert:** `last_reasons = last_moved` appended to `watch.py`. An
old caller then gets times only, its `last.get("reason")` is falsy, and no quote is rendered — so the
leak stays closed and the hook completes. Verified on a copy of a patched tree: hook failures 0, cursor
line present, quote tails 0. One honest cosmetic loss: the old `hooks.py` prints its `[moved …]` bracket
only when a reason exists, so those ten trees lose the timestamp from that line. A missing timestamp
against a dead session-start hook is not a close call.

| field | value |
|---|---|
| source file for copy 2 | `~/Sites/unrekt/oss/receipts-wiki/scripts/rwlib/watch.py` |
| source commit | `5d93108` — the md5 below is the identity the copy is verified against; a commit cannot name itself and survive an amend |
| intended md5, all ten targets | `8a388570e4eae33c01b909a28518be75` |
| targets | the same ten rows below |
| date recorded | 2026-10-14 |

**Pre-flight for copy 2, to be re-checked at the time:** every target should hash
`864112d320f46bf5a506ae3964a7a4ee` (the copy-1 result). A target still at
`9d842ec571af8599783392a02f7480bb` would mean copy 1 did not reach it and is a stop condition.

## Why

`${CLAUDE_PLUGIN_ROOT}` is resolved once per process, so a running session keeps executing the versioned
tree it started with. On 2026-10-14 a fix for a context leak was installed and 15 of 16 live sessions kept
running trees that still carried it; three were proven to have emitted after the install. Restarting each
session costs one human action per session, which does not scale. Patching the bound tree reaches those
sessions at their next prompt with no restart and with context preserved exactly — measured in
`docs/in-place-remediation.md`.

## What would be copied

| field | value |
|---|---|
| source file | `cache/receipts-wiki/receipts-wiki/0.4.1-dev.1/scripts/rwlib/watch.py` |
| source commit | `d2b4ec9c6ac6720f98b2c002e417ec09ae66607b` |
| source md5 | `864112d320f46bf5a506ae3964a7a4ee` |
| what it changes | the per-prompt notice stops appending another session's user turn, quoted out of that session's conversation archive, to each notice line |
| date recorded | 2026-10-14 |

## Targets, before and intended after

All ten carry a **byte-identical** `watch.py`, so this is one file content in ten places, not ten
variants. Each target's intended after-md5 is the source md5 above, which makes the patch verifiable
rather than merely logged: after copying, every row's actual md5 must equal it.

| tree under `cache/receipts-wiki/receipts-wiki/` | md5 before | intended after |
|---|---|---|
| `0.3.0-dev.21` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.22` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.23` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.24` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.25` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.26` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.27` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0-dev.28` | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.3.0`        | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |
| `0.4.0`        | `9d842ec571af8599783392a02f7480bb` | `864112d320f46bf5a506ae3964a7a4ee` |

`0.4.1-dev.1` is the source and is not a target. `marketplaces/receipts-wiki` is the marketplace checkout,
which no hook binds, and is not a target either.

## The one law behind all three conditions

⭐ **What survives an in-place code update is exactly what is re-resolved at use time; what breaks is
everything captured at start.** The two facts this route rests on are the two sides of that sentence: a
fresh `python3` per hook invocation re-resolves the *code* (so a patch lands), and `${CLAUDE_PLUGIN_ROOT}`
is captured once per process (so an install does not). Python's own `importlib.reload` documentation states
the same thing as library behaviour — *"Other references to the old objects are not rebound to refer to the
new objects"*, and instances *"continue to use the old class definition."*

⚠️ **And the production failure that makes the liveness check the load-bearing half, not the belt-and-braces
one.** Unicorn's `USR2` restart kept loading the *old* release because the process had `chdir`-ed at first
start to the path returned by `` /bin/sh -c pwd ``, which resolved to the real release directory rather than
to the `current` symlink. **Every file was correct and a hash check would have matched, while the running
process still executed old code.** So: *a process that resolves a stable path once, at start, is pinned
exactly as if the stable path never existed — therefore verification must read what the running process
RESOLVED, never that the path is correct.* An md5 match proves the file arrived; only a behavioural check
proves the hook executes it. (Surveyed independently by `unrekt-84`; the maintainer's own diagnosis on the
unicorn mailing list.)

Related, for the retention question rather than for today: PM2 raises `ENOENT` from `process.cwd()` once
pruning deletes the release a process started in. **How long old trees are kept is part of the design, not
cleanup** — which is a second reason the ten stale trees here are patched rather than removed.

## Conditions this record exists to satisfy

1. **Order.** This file is committed before the first copy. A record written afterwards documents a
   mismatch instead of authorising one.
2. **The staleness guard is reconciled, not silenced.** `config.superseded()` compares the bound root
   against the recorded install path, so it fires on every patched tree — correctly, because the content
   really does differ from what the host recorded. It must be taught to read this record and compare
   content. ⚠️ Tuning it quiet without this file would make a true alarm disappear.
3. **Announced as it lands.** This changes what running sessions do, and nothing in any session's own
   output records that its code changed underneath it. The sessions cannot notice; the people must be told.
4. **Scope.** Content fixes only, where both builds are correct apart from the defect. A generator or
   budget change does not go down this path — see the next section of `docs/in-place-remediation.md`.
