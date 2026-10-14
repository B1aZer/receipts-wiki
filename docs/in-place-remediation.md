# Reaching a running session without restarting it, measured

A fix installed into a plugin does not reach a running Claude Code session. `${CLAUDE_PLUGIN_ROOT}` is
resolved once per **process**, from one global install record with no per-session key, so a session goes
on executing the versioned tree it started with. On 2026-10-14 a fix for a context leak was installed and
**15 of 16 live sessions kept running trees that still carried it**; three were proven to have emitted
after the install, the last of them nearly five hours later.

The obvious remediation is to restart each session. It was rejected on grounds that hold: it costs **one
human action per session**, which is merely annoying at 15 and impossible at 1000. A remediation whose
cost scales with the fleet is the wrong remediation.

## The alternative, and the premise it rests on

The hook is invoked as `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/rw.py hook prompt` — a **fresh process per
invocation**, reading the script from the bound path at execution time. Only the *path* is frozen at
session start, not the code at it. If that holds, then fixing the code **at the path a session is already
bound to** reaches that session at its next prompt with no restart at all, and the cost scales with the
number of distinct trees rather than the number of sessions.

## Measured, as a pair that could have failed

Reproducing the leak end to end needs a real fixture, because a notice's changed paths come from the
commit's `Change:` trailers and not from the diff: a memory home with such a commit, and a conversation
archive for the committing session to quote from. The fixture uses a **synthetic canary** in place of a
user turn, so proving the leak costs none of the real ones.

```
BEFORE  subject tree, leaky       canary quoted = 1    notice rendered = 1
BEFORE  control tree, leaky       canary quoted = 1    notice rendered = 1
        --- the SUBJECT tree is patched in place; nothing is restarted ---
AFTER   subject tree, patched     canary quoted = 0    notice rendered = 1
AFTER   control tree, untouched   canary quoted = 1    notice rendered = 1
control output byte-identical before and after: yes
```

One tree changed, one behaviour changed, one control unchanged. The patched tree still renders its notice
(`- thing changed just now by another session`), so the quote is gone and the feature is not. **The
premise holds.** `__pycache__` already existed in the subject tree and did not serve stale bytecode, which
was the realistic way this could have failed silently.

⭐ **And the cost is O(1), not O(versions).** All ten leaky cached trees carry a **byte-identical
`watch.py`** (md5 `9d842ec5`): not ten versions of a file but one file in ten places. The fixed
`watch.py` references nothing missing from the older trees' sibling modules, and swapping it into a copy
of each of the ten leaves no leak code and raises no traceback. The artefact is one file content, verified
once, copied to ten paths — a number that does not grow with the session count at all.

Two of this measurement's own earlier runs were wrong in the way everything else here is wrong, and both
were caught by a control rather than by inspection: a smoke test across all ten trees returned `rc=0`
while running against a nonexistent home, so `hook_prompt` returned before executing any swapped code and
the pass was satisfied by the hook doing nothing; and a first before/after pair reported "unpatched" for a
tree that an earlier aborted run had already patched — a mislabel, not a measurement.

## What the route has to carry

1. ⚠️ **A patched tree's content no longer matches its recorded `gitCommitSha`.** The install record would
   claim those sessions run a commit whose files they no longer have. Since every receipt this project
   issues rests on that field, **the record of which trees were patched and why has to exist before the
   patch, not after.**
2. ⚠️ **The staleness guard added the same day fires on path**, so it will tell a session to restart even
   after its code has been fixed in place. The remediation and the detector conflict, and the detector has
   to learn to read the patch record and compare content — not be quietly tuned to stop mentioning
   something that really happened.
3. **One hazard a restart does not have:** patching can change behaviour *between two hook calls inside a
   single turn*. Benign for this fix, where the two builds differ only in whether a quote is appended.
   Not benign for a generator or budget change.

## Why a stable path is not the permanent answer

The tempting conclusion is that executable code should resolve through a stable path, so an install
reaches running processes and no remediation is ever needed. Today is the argument against it.

- **It converts a guarantee into a hazard.** "A session keeps the code it started with" is a consistency
  property, not only a defect; a stable path promotes item 3 above from an edge case to the design.
- **It removes the rollback window.** This incident was survivable *because* 15 sessions kept the old
  build. Had the fix been wrong, a stable path would have propagated it fleet-wide instantly with nothing
  still running the previous code. "Slow to fix" and "small blast radius" are one property seen from two
  sides: for a context leak fast is right, for a generator change slow is right.
- ⚠️ **It may not be available.** `${CLAUDE_PLUGIN_ROOT}` is set by the host from its own install record,
  and a plugin does not control that resolution. Pointing hooks at a fixed absolute path would hardcode a
  machine-specific location into a plugin other people install. Whether the host even permits that is a
  question to check rather than assume — and it is the load-bearing premise.

So: pin, detect (the guard), and keep an operator patch path for urgent *content* fixes — which is
strictly more capable than a stable path, because it keeps the rollback window that made today recoverable.
