# The unwritten-work gate: measured before it was built

A fleet restart was staged on 2026-10-14. The readiness question asked across every session was
"is anything running", and `ps` answered truthfully: session `gingleisland-05` was idle. The table it
had just finished lived in exactly two places — that session's context, and a session-scoped task
output under `/private/tmp/claude-501/.../tasks/`. `grep -rl` over `docs/` and `tools/` found nothing,
and **the script that produced it was untracked too, so the restart would have taken the result and
the means of re-taking it.** Both are now committed (GingleIsland `ba569f6`).

So a session's work sits in one of four states, and only three are visible from outside:

| state | detector | treatment |
|---|---|---|
| in flight | `ps` | wait |
| modified | `git status` | patch it, and prove the restore into a tree that lacks the change |
| untracked | `git status --porcelain --untracked-files=all` | commit it |
| read but never written | **nothing outside the session** | ask |

The fourth loses most, and ⭐ **it is the state that looks safest from outside** — a session with
nothing running reads as the cheapest one to cut. States three and four travel together (05 had both,
and either alone is recoverable), which is what makes the undetectable state tractable: fire on three,
then ask about four.

Untracked and modified need **separate lines**, because their treatments are opposite. An untracked
file survives `git checkout` and is invisible to every staleness tool; a tracked modification is
visible to everyone and destroyed by one checkout. "You have uncommitted work" conflates them and
prescribes the wrong fix for one.

## The measurement, because the noise is the whole design problem

A gate is kept or removed on what it costs against what it catches, measured — so this was measured
on the three live working trees before anything was written. Counts are files; no file contents were
read.

| rule | GingleIsland | unrekt | receipts-wiki | total |
|---|---|---|---|---|
| A. all untracked (the naive gate) | 949 | 984 | 2 | **1,935** |
| B. under `tools/ scripts/ bin/ evals/` | 0 | 0 | 1 | 1 |
| C. newer than session start | 929 | 6 | 1 | 936 |
| D. source-like extension | 3 | 96 | 2 | 101 |
| **D ∧ mtime ≤ 24h (shipped rule)** | **3** | **2** | **2** | **7** |

**Recall on the only known true positive:** `ba569f6` is `tools/grass_fill_or_cpu.sh` plus
`docs/artstyle/GRASS_PERF_FILL_OR_CPU.md`. Both are source-like and both were created that day, so
the shipped rule names **both** — the instrument and the result beside it.

Three results worth keeping, each of which killed a candidate that looked good:

1. **The naive gate is ~20× louder than anyone estimated.** The guess was ~40 untracked files under
   `docs/artstyle/`; the real count is 949, of which **926 are `.png`/`.webp`** generated sheets. One
   extension test removes 98% of the noise. This is the gate that trains people to dismiss it.
2. ⚠️ **Rule B is quiet because it is blind, not because it is precise.** It fires on 0 of unrekt's 96
   source-like untracked files, because unrekt keeps its scripts in `atlas/` and `atlas/corpus/github/`,
   not in `tools/`. It encodes one repo's layout and reads as clean everywhere else — and a silent gate
   is the one genuine failure this plugin has had. **Rejected despite having the best numbers.**
3. **Rule C's selectivity is not a property of the rule.** It keeps 929 of 929 in one repo and 6 of 984
   in another, because it depends on the repo's churn and the session's age, and the oldest sessions are
   exactly the ones that matter. Unusable alone.

## What it must not do

The rule as measured names, in this very repo, a working note that is deliberately untracked and
**must stay that way** — some files are untracked on purpose, and at least one here would be harmful
to commit. A gate that prescribed committing it would be wrong every single time it fired, which is
the dismissal-training shape again. So the gate **reports state,
it does not prescribe `commit`**, and a path listed in a per-repo silence file is dropped without
comment.

Then, and only then, the line for state four — one line, asking for unwritten numbers rather than
running processes, because nothing outside the session can see them.

## Sequencing

Shipping this now would not take effect. `${CLAUDE_PLUGIN_ROOT}` is resolved once per process, so the
15 sessions started before an install keep executing their old tree; a new gate reaches them only at
restart. The gate is therefore queued behind the refresh, not ahead of it.
