---
name: refresh-stale-sessions
description: Gets a shipped fix into sessions that are still running the old code, by deciding whether it may be patched in place at all, gating the patch on a two-direction compatibility check, recording the intended result before any copy, and verifying behaviourally rather than by hash. Use after installing a fix that running sessions are still not executing. Never run it on a schedule.
license: MIT
---

# Get a fix into sessions that are still running the old code

`${CLAUDE_PLUGIN_ROOT}` is resolved once per **process**, from one global install record with no
per-session key, so a session keeps executing the versioned tree it started with however many times the
plugin is reinstalled. An install reaches new sessions only. On 2026-10-14 a fix for a context leak was
installed and 15 of 16 live sessions kept running trees that still carried it; three were proven to have
emitted after the install, the last nearly five hours later.

⚠️ **This is not a sweep and it has no cadence.** Run it when a fix exists that running sessions are not
executing. A step that runs daily by default is the condition that precedes being ignored.

⛔ **A session cannot finish this alone, and that is correct rather than a gap.** Three denials, each from
the auto-mode classifier: a session may not `--resume` or `stop` other sessions, may not write the plugin
code every session runs ("Modify Shared Resources"), and may not widen its own permissions
("Self-Modification"). A session that can grant itself permissions has no permission system. **So the
apply step belongs to an operator. Everything else — diagnosis, the record, the gate, the verification —
belongs here.** ⚠️ Whether an explicit allow rule pre-empts that classifier is **unverified**; do not
write it into a plan as a workaround.

## 1. Decide the channel first. This is the decision, not a preamble.

**Is this a content fix or a behaviour change?**

> Would a turn that begins under the old build and ends under the new one still make sense?

- **Yes → content fix.** Both builds are correct apart from the defect; a straddled turn is still coherent.
  A context leak is the clear case: the builds differ only in whether a quote is appended. **Patch in
  place. Continue.**
- **No → behaviour change.** Generators, budgets, gates, index layout — anything a later turn's output
  depends on. A session would write half an artefact under each rule, which is the 2026-09-30 incident
  (29 of 33 generated indexes rewritten) with a narrower window rather than a different cause. **Do not
  patch. The fix reaches those sessions when they restart, and `config.superseded()` tells them so at
  their next prompt. Stop here and say that.**

⚠️ Patching `indexer.py`, `checks.py` or `config.py` in place is always the second case. Measured
2026-10-14: ten cached trees differed from the installed build in 4 to 9 of ~20 modules, and the
differing set included all three.

## 2. Size the problem, read-only.

`python3 tools/refresh-stale-sessions.py --plugin <name>@<marketplace> --dry-run` lists live sessions,
which started before the install, and the trees they are bound to. `--verify-only` reads existing output
for the defect. Both read structure, timestamps and counts, never transcript content.

**Enumerating sessions read-only is fine and necessary — it sizes the work and it is how you verify
afterwards. Acting on a session is the part that is not yours.** Identify builds by `gitCommitSha`, never
by version string: `0.4.1-dev.1` was set in the commit *before* the leak fix and never bumped, so the
leaking and fixed builds report it identically.

⚠️ **An empty target set is a STOP condition, never a wildcard.** A decommission workflow is reported to
have been given no machines, with the empty set treated as a special value meaning *everything* — erasing
nearly the whole fleet. (Reported, relayed; primary not read here, and the wording is not a quotation.) A refresh tool over a glob is exactly that shape. If the target list
is empty, something upstream is wrong: stop and find out what. Alongside it: sanity-check the input,
rate-limit the work, make every step idempotent, and stop after repeated failure instead of continuing.

## 3. Gate the patch on `tools/graft-check.py`. Both directions. Non-zero exit means stop.

```
python3 tools/graft-check.py scripts/rwlib/<file>.py <tree>/scripts/rwlib ...
```

It reports two things separately, and **either being non-empty means the graft is unsafe**:

- **inbound** — what the new file needs from that tree and the tree does not have, including a whole module
  the tree lacks;
- **outbound** — what that tree's other modules ask of this one and the new file no longer defines.

⚠️ **The outbound half is the one that gets skipped, and it is the half that broke.** The 2026-10-14
pre-flight asked only whether the new file could find what it needs in the old tree. It could. But the fix
had renamed `watch.last_reasons` to `last_moved`, those trees kept their older `hooks.py` calling the old
name, and **every patched tree's SessionStart hook died** — `module 'rwlib.watch' has no attribute
'last_reasons'`. Reachable because SessionStart re-fires on **compaction** and on `/clear`, so a running
session would come back with no rules, no cursor pointers and no area index, and carry on without them.

**When outbound names something, prefer an alias to a revert:** keeping the old name bound to the new
function leaves the fix in place. It must stay behaviour-free — restoring the old *name* must never restore
the old *behaviour* in the trees that can only be fixed this way — so assert both the alias and that in a
test.

⭐ **Read the coupling surface it prints.** A closed interface is necessary, not sufficient: behaviour
coupling that is not a name cannot appear in a static check, and the surface is what a human still has to
reason about. Four names was a graft worth doing; a wide surface is a reason to wait for a restart instead.

## 4. Write the record before the first copy. Afterwards it is a log, not a check.

Add to `docs/patch-record.md`, and **commit it before anything is copied**: every target path, each one's
hash *before*, the source file and its commit, the date, what the change does, and ⭐ **the hash each
target must have afterwards.** A record that only describes what was done cannot catch a copy that
half-failed; one that commits to the result in advance can, and it lets someone who did not perform the
run verify it.

⚠️ **Written in advance by someone expecting to be wrong is the whole point.** A patched tree's content
stops matching the `gitCommitSha` the host records for it, so without the record the install record claims
a session runs a commit whose files it does not have.

Keep the original file where it can be restored from, and hash-verify that copy. Never delete a tree;
rename it if it must move aside.

## 5. Hand the apply to the operator, with the expected output.

Give one command and say what it should print — the paths, the source, and the hash every row must show.
Say plainly that the session is denied this write and is not going to attempt it. Then stop and wait.

## 6. Verify behaviourally. The hash is explicitly not sufficient.

Hashes first: every target against the value the record committed to in advance, and a target still
carrying the old hash means the copy did not reach it — a stop condition, not a retry.

⚠️ **Then prove the running process executes it, because the hash cannot.** A Unicorn `USR2` restart is
reported to have kept loading the *old* release: the process had resolved its working directory once at
first start, to the real release path rather than to the `current` symlink. **Every file was correct, a
hash check would have matched, and the running process still ran old code.** (A reported case, relayed from
a research survey; the primary was not read in that chain. The rule below does not depend on it.)
So: *a process that resolves a path once, at start, is pinned exactly as if the stable path never existed —
therefore verification must read what the running process RESOLVED, never that the path is correct.*

**The instrument is a live, unrestarted session's own output, quoted raw by that session**, before and
after. Ask for the text, not an interpretation. A session with a documented before-state is worth more
than three with none. Exercise the repaired path too, not only the defect: after 2026-10-14 the check was
*notice still renders, quote gone* — a fix that silences the feature is not a fix.

## 6b. Audit the trees from outside, by content. `python3 scripts/rw.py trees`

It lists every install tree, its own write time, any file written into it afterwards, and whether a
hash in `docs/patch-record.md` accounts for that file. Non-zero exit on either of two states, and it
silences neither: **content no row accounts for**, and **a target the record names that is no longer in
the cache** — a tree can be pruned while a session is still bound to it, and then its hooks fail
outright rather than running old code, so a vanished target is a finding and not housekeeping. Seven of
ten targets were pruned the morning after the 2026-10-14 patch.

⭐ **Why this is a command and not a hook, which is worth more than the command.** A staleness check can
only ever answer for the tree it is running in — and a check you just shipped is, by the very defect
this skill exists for, absent from every tree you are asking about. `config.superseded()` shipped in
`0.4.1-dev.2`; the ten patched trees keep their own older `config.py`, so the guard does not exist in
any tree it was written to answer for and never will. **The audit has to live outside every session,
exactly as the applier does, and for the same reason.** Expect this shape whenever you add a check in
the same release as the fix it is meant to watch.

And the matching rule for the check itself: **the record explains the alarm, it does not cancel it.** A
patched tree is still told its content is not the commit the install record names, because no receipt it
issues can cite that commit. Tuning a true alarm quiet is what the record discipline exists to prevent.

## 7. Give this procedure its own control before trusting its green result.

Everything above has a way of passing while the property it stands for is false, and three different
sessions hit that in one day. So:

- Run `graft-check.py` against a pairing you know is bad — the pre-fix file, or a module into a tree that
  lacks one of its imports — and **see it exit non-zero** before you trust a SAFE.
- Make the leak fixture reproduce the defect **before** the patch, or "no defect found" afterwards means
  nothing. A synthetic canary costs none of the user's own turns.
- If a check returns the same answer for the subject and the control, it is not measuring the subject.

## 7b. Run each gate BEFORE the act it gates, in its own step.

⭐ **A gate whose result you read afterwards is not a gate, and no better check fixes that — it is
sequencing.** On 2026-10-14 the pre-push probe was run in the same command block as the push, so its output
arrived after the push had already happened. The outcome was clean, which is luck and not a defence.

⚠️ **And when a probe reads a diff, count ADDED lines only.** The same probe reported a hit that turned out
to be an untouched neighbouring line, pulled into the diff as *context* because a manifest was edited in
place. A second session's probe was correct on the earlier range only because nothing in it had been edited
in place — **a probe that is right on a range of pure additions is untested, not validated.** Inject a
synthetic positive and see it fire before trusting any zero.

⚠️ **Gate the REFS, not only the diff. A private file kept out of `main` can still be sitting in a
local tag.** Found 2026-10-15 in this repo: the deliberately-unpublished multi-session plan is in three
commits reachable only from a local `backup-pre-squash-*` tag — absent from `main`, from `origin/main`
and from every published tag, so the diff gate was right and said nothing. But `git push --tags` or
`--follow-tags` publishes all three and the file with them, permanently. **Same shape as a deletion
commit publishing what it deletes: the thing you kept out of history is one careless flag from being in
it.** So before any push, check what the refs contain and not just the range:

```
git log --all --oneline -- <the private path>        # which commits hold it at all
git for-each-ref --contains <sha> --format='%(refname)'   # and which refs reach them
git ls-remote --tags origin                          # what is already published
```

Push the branch by name, never `--tags`, and leave a backup tag alone rather than deleting it — deleting
a tag that was never pushed publishes nothing, but it is still someone else's backup to retire.

## 7c. Label a citation by whether you read it.

⭐ **The remedy for an overstated source is the label, not the claim.** A figure taken from a search
summary of a primary is usually accurate; what a reader cannot do is tell it apart from one that was
fetched and read. So write which it is. A survey that labelled summaries as *documented* against named
primaries produced ~11 such rows out of ~20 — **inside documents written to warn about exactly that**, and
an earlier version of this skill published one of them as a maintainer's diagnosis on a named mailing list.
**A cited case that nothing rests on is fine; a cited case whose provenance is overstated spends the credit
of every properly sourced claim beside it.**

## 8. Close out.

Update the record's status to the measured result and attribute the run to whoever performed it.
**Announce it** to every driver as it lands: this changes what running sessions do, and nothing in any
session's own output records that its code changed underneath it. The sessions cannot notice; the people
have to be told.

⚠️ **`claude plugin update` compares VERSION STRINGS, so an install without a version bump is a no-op
that prints success.** Measured 2026-10-14: ten commits were pushed, the marketplace clone advanced to
them, `claude plugin update` answered *"already at the latest version (0.4.1-dev.1)"*, and the install
record still carried the previous `gitCommitSha`. **Bump the version in `.claude-plugin/plugin.json`
before installing, and confirm the install by `gitCommitSha` against the commit you pushed — never by the
version string and never by the updater's own message.** This is the same defect as a leaking build and a
fixed build reporting the same version, one layer up in the tooling.

Then: the trees are patched, not installed. **Install the fix so new sessions get it, and treat making the
stale trees byte-identical as hygiene at each session's next restart — no longer remediation, because the
defect is already closed in them.**
