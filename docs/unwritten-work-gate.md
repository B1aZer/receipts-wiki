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

## Why it reports state and does not say what to do, for a second reason

The rule names an untracked `.patch` file. The obvious refinement is to test it — `git apply --check
--reverse`, and if it reverses, the change already landed, so say "already in HEAD" instead. **It does
not discriminate.** Measured on two real patches in one tree on 2026-10-14: one whose change had just
been committed, and one serialising live uncommitted work. **Both reverse cleanly**, because
`--reverse --check` tests the *working tree*, not `HEAD` — so "it reverses" means only "this content is
present somewhere", the identical signal for landed-and-therefore-stale and for
serialized-from-an-uncommitted-modification. Those are opposite hazards: the first wants deleting, the
second is the only copy of unlanded work.

What separates them is the pair, not the patch: are the patch's target files clean? The stale one
targeted a file with no modification; the live one targeted exactly the two files `git status` reported
modified. Which is the four-state table's own point — **states two and three travel together, and here
that is the only thing that tells them apart.**

So the one claim that survives about an untracked patch is the plain one: *this is a serialized change
living outside git.* A gate that said "commit it" would have been wrong on the stale patch, and a gate
that said "you have unlanded work" would have been wrong too, because that work had landed twenty
minutes earlier. State reporting was right for a reason this design did not have to anticipate, which
is a better argument for it than the deliberately-untracked case it was written for — that one can be
silenced once, while this one **changes under the gate.**

## Sequencing — ⚠️ SUPERSEDED 2026-10-16, and the correction matters more than the plan did

This section said: shipping now would not take effect, because `${CLAUDE_PLUGIN_ROOT}` is resolved once
per process, so sessions started before an install keep their old tree and a new gate reaches them only
at restart — therefore queue the gate behind the refresh.

⭐ **The premise is right and the conclusion was wrong. A hook would have arrived exactly too late,
every time: the restart is the moment the gate exists for.** So the gate is not a hook. It is a section
of `tools/refresh-stale-sessions.py`, the pre-flight that stages the restart, which runs fresh and is
therefore never stale — and nothing is queued behind anything.

**Third independent arrival at the same boundary this week.** The in-place patch applier cannot live in
a session because a session is denied the write; `rw.py trees` cannot be a hook because a staleness
check shipped with its own fix is absent from every tree it must judge; and this gate cannot be a hook
because it must speak before the restart that would install it. **A check that has to answer for a
session cannot live inside it.**

## 2026-10-16 — the modified half, measured after it had already shipped loud

⚠️ **This document measured four rules for the UNTRACKED state and nothing for the MODIFIED one**, where
it said only "git status, patch it". So the untracked half was built from a measurement and the modified
half from nothing, and the first real run printed **608 modified files for one tree** — the exact
dismissal-training failure this document exists to prevent, in the half it did not cover. A measured
rule beside an unmeasured one reads as measured.

| rule | GingleIsland | unrekt | receipts-wiki | total |
|---|---|---|---|---|
| all modified | 0 | 608 | 1 | **609** |
| source-like extension | 0 | 489 | 1 | 490 |
| **source-like ∧ mtime ≤ 24h (shipped)** | 0 | 2 | 1 | **3** |
| source-like ∧ mtime ≤ 2h | 0 | 0 | 1 | 1 |

⭐ **The inverse of the untracked finding, and that is why the conjunction is right.** There the
extension test removed 98% of 1,935 and mtime added nothing; here mtime does all the work and the
extension almost none — 489 of one tree's 608 dirty files *are* source. **The two states need the same
conjunction for opposite reasons**, which is a stronger argument for it than either state could make
alone. Two hours was rejected as too tight: it drops work from earlier the same day.
