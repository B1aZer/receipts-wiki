# Patch record for the plugin cache

⚠️ **This file is written and committed BEFORE any file under the plugin cache is copied, never after.**
A patched tree's content no longer matches the `gitCommitSha` the host records for it, so without this
file the install record claims a session is running a commit whose files it does not have. Every receipt
this project issues rests on that field, which is the whole reason the order is fixed: the record first,
then the copy, then the verification against the record.

**Status: nothing has been patched.** The table below is the *before* state and the *intended* result. No
tree under `~/.claude/plugins/cache/` has been modified. Awaiting the owner's decision.

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
