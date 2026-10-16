#!/usr/bin/env python3
"""Cursor-notice backtest: is `cursor-not-updated` worth keeping, filtering, or dropping?

Runs over a memory home's own git history. No model calls, no network, nothing written.

    python3 evals/cursor_notice/backtest.py
    python3 evals/cursor_notice/backtest.py --home ~/.agents --window 24 --json

WHAT IS BEING DECIDED. `checks.turn_notices(home, rels)` fires when an edited note is linked by an
active cursor that was not itself edited, asking the session to update that cursor. It receives the home
and the written paths and **nothing about the session**, so it cannot consult ownership — and
`AGENTS.md` says whoever owns a piece of work owns its cursor. It was observed firing repeatedly at a
session about a cursor belonging to a different session, which is a request to break a rule, correctly
ignored every time. Two candidate changes, with different confidence:

  - OWNERSHIP, high confidence: suppress a notice about a cursor this session does not own.
  - A SUBSTANCE TEST, low confidence and the one the plan says to measure first: fire only when the edit
    changed the note's `description` or head paragraph, not on a typo or a body-only tweak.

The bar, from the plan: how many notices would the ownership filter suppress, and **of those, how many
were followed by that same session updating the cursor anyway** — that second number is the cost, the
true positives thrown away. And for the substance test: does it raise the follow-through rate above the
base rate? Below it, the test is noise with extra steps.

METHOD. Ownership is reconstructable because memory commits carry trailers: 1,052 of 1,257 here have
`Session:`. For every commit that changed a non-cursor note, the condition fires for each active cursor
that linked that note and was not itself in the commit. A session OWNS a cursor if it had committed that
cursor before. Follow-through is the cursor being committed inside --window hours afterwards, and the
run reports it two ways: by anyone, and by the same session.

⚠️ The base rate is per cursor and not global, because a cursor that moves every day will appear to
follow through on anything. For each fired condition it asks how often that same cursor was committed in
a window of the same length placed where no condition for it fired — so churn is held constant and only
the condition varies. A rate below its own base rate means the condition carries no information.

⚠️ LIMITS, stated because they bound the answer.
  1. Ownership by prior commit is a PROXY. The live check would use `data["reads"]`, which includes
     cursors a session read and never wrote; history cannot show a read. So the filter measured here is
     stricter than the one that would ship, and its suppression count is an upper bound.
  2. 205 of 1,257 commits carry no `Session:` trailer. They are excluded from the ownership half and
     kept in the follow-through half, which is stated rather than silently averaged.
  3. ⭐ A notice acknowledged and judged not worth acting on looks identical to one never shown. That
     confound is in the plan and it is not removable from history: this measures follow-through, never
     whether the notice was read.
"""
RESULT on the author's home, 2026-10-16 (1,256 memory commits, 13 cursors, 24h window, base rate from
1,330 activity-matched windows):

    conditions fired   266
    follow-through     75.2%   against a 6.0% base rate -> +69.2 points
    owned              176 fired, 85.8% followed, 67.6% by the same session
    NOT owned           55 fired, 60.0% followed, 34.5% by the same session   <- what the filter drops
    no Session trailer  35 (excluded from the ownership half)
    substance test       7 fired with a description or head-paragraph change, 259 body-only

⭐ VERDICT 1: THE CONDITION IS ACCURATE AND LARGELY REDUNDANT, which is not the same as noisy. It
identifies the moment before a cursor update with 75% precision against a 6% base, so it is carrying real
information. But `AGENTS.md` already says *when your turn moves the work, rewrite the cursor that turn* --
so a notice firing where the author acts anyway 3 times in 4 is mostly telling people to do what they
were about to do. ⚠️ Its whole value is in the residual quarter, and history cannot say whether a notice
would have changed those: a notice acknowledged and judged not worth acting on is indistinguishable from
one never shown. **So the honest claim is precision, not benefit.**

⭐ VERDICT 2: DO NOT SHIP THE OWNERSHIP FILTER AS SPECIFIED. The plan asked for its cost and the cost is
large: of the 55 notices it would suppress, 60.0% were followed by a cursor rewrite and 34.5% by the
SAME SESSION that was nudged. Suppressing them discards 33 true positives, 19 of them cases where the
very session being told acted on it. ⚠️ The misdirected-notice complaint that motivated the filter is
real, but prior-commit ownership is the wrong discriminator for it. The live filter would use
`data["reads"]`, which also counts cursors a session only READ -- strictly looser, so it suppresses less
and costs less, and this run puts an upper bound on that cost rather than measuring it.

⚠️ VERDICT 3: THE SUBSTANCE TEST IS UNMEASURABLE HERE, n=7. Only 7 of 266 fired conditions involved a
description or head-paragraph change, so the 42.9% against 76.1% is three cases against two hundred and
licenses nothing at all. **Unmeasurable, not refuted** -- and the direction being unfavourable is exactly
the kind of number it would be tempting to report. It is not reported as a finding.

⚠️ THE CONTROL WAS WRONG FIRST, and the correction is kept because the error is instructive rather than
embarrassing. The base rate originally drew placebo windows from anywhere in the timeline, which drew
mostly QUIET ones: the condition only fires while a workstream is live, and a cursor's own commits
cluster in the same live periods, so the condition and the outcome share a cause. That reported 4.5% and
+70.7. Activity-matching -- every placebo window starts at a real commit that changed some note -- moved
it to 6.0% and +69.2. ⭐ The confound was real and small, which is worth knowing: it would have been just
as wrong to assume it was large and discard the result.

import argparse
import json
import os
import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from rwlib import frontmatter  # noqa: E402

WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def git(home, *args):
    out = subprocess.run(["git", "-C", str(home)] + list(args), capture_output=True, text=True, check=False)
    return out.stdout if out.returncode == 0 else ""


def name_of(rel):
    return Path(rel).name[:-3].replace("_", "-")


def history(home):
    """[(epoch, sha, session, [changed rels])] oldest first."""
    raw = git(home, "log", "--reverse", "--format=C%x01%H%x01%at%x01%B%x02", "--name-only", "--", "memory")
    out = []
    for chunk in raw.split("\x02"):
        if "\x01" not in chunk:
            continue
        head, _, tail = chunk.partition("\n")
        parts = head.split("\x01")
        if len(parts) < 4:
            # the body spans lines, so re-split on the record marker instead
            parts = chunk.split("\x01")
        if len(parts) < 4:
            continue
        sha, at, body = parts[1], parts[2], parts[3]
        session = ""
        for line in body.splitlines():
            if line.startswith("Session:"):
                session = line.split(":", 1)[1].strip()
        rels = [ln.strip() for ln in chunk.splitlines()
                if ln.strip().startswith("memory/") and ln.strip().endswith(".md")]
        if not rels:
            continue
        out.append((int(at), sha, session, sorted(set(rels))))
    return out


def is_cursor(rel):
    return Path(rel).name.startswith("cursor_")


def cursor_timeline(home, commits):
    """{cursor rel: [(epoch, linked names set, description)]}, built only from commits that touch cursors."""
    timeline = defaultdict(list)
    for at, sha, _session, rels in commits:
        for rel in rels:
            if not is_cursor(rel):
                continue
            text = git(home, "show", f"{sha}:{rel}")
            if not text:
                timeline[rel].append((at, None, None))   # deleted or unreadable: inactive from here
                continue
            fm, body = frontmatter.split(text)
            timeline[rel].append((at, set(WIKILINK.findall(text)),
                                  str(frontmatter.get(fm, "description") or "")))
    return timeline


def state_at(timeline, rel, when):
    """The cursor's links and description as of just before `when`, or None if it did not exist."""
    best = None
    for at, links, description in timeline.get(rel, ()):
        if at <= when:
            best = (links, description)
        else:
            break
    return best


def head_paragraph(text):
    _, body = frontmatter.split(text)
    return body.strip().split("\n\n", 1)[0] if body.strip() else ""


def substantive(home, sha, rel):
    """Did this commit change the note's description or its head paragraph?"""
    after = git(home, "show", f"{sha}:{rel}")
    before = git(home, "show", f"{sha}^:{rel}")
    if not after:
        return False
    if not before:
        return True                 # a new note is as substantive as it gets
    fm_a, _ = frontmatter.split(after)
    fm_b, _ = frontmatter.split(before)
    if str(frontmatter.get(fm_a, "description") or "") != str(frontmatter.get(fm_b, "description") or ""):
        return True
    return head_paragraph(after) != head_paragraph(before)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", default=os.environ.get("RECEIPTS_WIKI_HOME") or str(Path.home() / ".agents"))
    p.add_argument("--window", type=float, default=24.0, help="hours for a cursor rewrite to count (default 24)")
    p.add_argument("--draws", type=int, default=5, help="placebo windows per fired condition (default 5)")
    p.add_argument("--seed", type=int, default=20261016)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    home = Path(args.home).expanduser()
    if not (home / ".git").exists():
        print(f"{home} is not a git repository", file=sys.stderr)
        return 2
    commits = history(home)
    timeline = cursor_timeline(home, commits)
    span = args.window * 3600
    rng = random.Random(args.seed)

    # When was each cursor committed, so follow-through and the base rate are lookups.
    touched = defaultdict(list)
    for at, _sha, session, rels in commits:
        for rel in rels:
            if is_cursor(rel):
                touched[rel].append((at, session))

    fired = []
    for at, sha, session, rels in commits:
        notes = [rel for rel in rels if not is_cursor(rel) and not Path(rel).name.startswith("index-")
                 and Path(rel).name != "MEMORY.md"]
        if not notes:
            continue
        for cursor in timeline:
            if cursor in rels:
                continue                      # edited in the same commit: the condition does not fire
            state = state_at(timeline, cursor, at)
            if not state or state[0] is None:
                continue
            links, _description = state
            if not any(name_of(rel) in links for rel in notes):
                continue
            after = [s for t, s in touched[cursor] if at < t <= at + span]
            fired.append({
                "at": at, "cursor": cursor, "session": session,
                "owned": bool(session) and any(t < at and s == session for t, s in touched[cursor]),
                "followed": bool(after),
                "followed_same": bool(session) and session in after,
                "substantive": any(substantive(home, sha, rel) for rel in notes),
            })

    def rate(rows, key="followed"):
        return 100.0 * sum(1 for r in rows if r[key]) / len(rows) if rows else 0.0

    # Per-cursor base rate: the same cursor, a window of the same length, placed where it did not fire.
    fire_times = defaultdict(set)
    for row in fired:
        fire_times[row["cursor"]].add(row["at"])
    # ⚠️ ACTIVITY-MATCHED, and the first version was not. The condition only fires while a workstream is
    # live -- a note linked by the cursor is being edited -- and a cursor's own commits cluster in the
    # same live periods. So the condition and the outcome share a cause, and drawing placebo windows
    # from the whole timeline draws mostly QUIET ones. That reported a 4.5% base rate and a +70.7 point
    # lift, which is the home's activity profile rather than the notice's value. Same family as the
    # exposure confound in evals/dedup/backtest.py: a control has to hold the common cause constant.
    #
    # Each placebo window now starts at the timestamp of a REAL memory commit that changed some note,
    # with no condition for this cursor nearby -- so the home was demonstrably active either way.
    active = sorted({at for at, _sha, _s, rels in commits
                     if any(not is_cursor(r) and r.endswith(".md") for r in rels)})
    base_hits = base_total = 0
    for row in fired:
        for _ in range(args.draws):
            for _try in range(30):
                when = rng.choice(active)
                if any(abs(when - t) <= span for t in fire_times[row["cursor"]]):
                    continue
                base_total += 1
                if any(when < t <= when + span for t, _s in touched[row["cursor"]]):
                    base_hits += 1
                break
    base = 100.0 * base_hits / base_total if base_total else 0.0

    owned = [r for r in fired if r["owned"]]
    unowned = [r for r in fired if not r["owned"] and r["session"]]
    no_session = [r for r in fired if not r["session"]]
    subst = [r for r in fired if r["substantive"]]
    thin = [r for r in fired if not r["substantive"]]

    report = {
        "home": str(home), "commits": len(commits), "cursors_seen": len(timeline),
        "window_hours": args.window, "conditions_fired": len(fired),
        "base_rate_pct": round(base, 1), "base_windows": base_total,
        "follow_through_pct": round(rate(fired), 1),
        "owned": {"n": len(owned), "follow_pct": round(rate(owned), 1),
                  "follow_same_session_pct": round(rate(owned, "followed_same"), 1)},
        "unowned": {"n": len(unowned), "follow_pct": round(rate(unowned), 1),
                    "follow_same_session_pct": round(rate(unowned, "followed_same"), 1)},
        "no_session_trailer": len(no_session),
        "substantive": {"n": len(subst), "follow_pct": round(rate(subst), 1)},
        "thin": {"n": len(thin), "follow_pct": round(rate(thin), 1)},
    }
    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0


def _render(r):
    o, u, s, t = r["owned"], r["unowned"], r["substantive"], r["thin"]
    return "\n".join([
        f"home              {r['home']}",
        f"memory commits    {r['commits']}   cursors seen {r['cursors_seen']}   window {r['window_hours']}h",
        f"conditions fired  {r['conditions_fired']}",
        "",
        f"follow-through    {r['follow_through_pct']}%  (the cursor was committed inside the window)",
        f"base rate         {r['base_rate_pct']}%  per cursor, over {r['base_windows']:,} ACTIVITY-MATCHED windows where it did not fire",
        f"lift              {round(r['follow_through_pct'] - r['base_rate_pct'], 1):+} points",
        "",
        "OWNERSHIP FILTER — what it would suppress, and what that costs",
        f"  owned      {o['n']:>6} fired   {o['follow_pct']:>5}% followed   {o['follow_same_session_pct']:>5}% by the same session",
        f"  NOT owned  {u['n']:>6} fired   {u['follow_pct']:>5}% followed   {u['follow_same_session_pct']:>5}% by the same session  <- suppressed",
        f"  no Session trailer {r['no_session_trailer']:>6} (excluded from the ownership half)",
        "",
        "SUBSTANCE TEST — does what the edit changed predict follow-through?",
        f"  description or head paragraph changed  {s['n']:>6} fired   {s['follow_pct']:>5}% followed",
        f"  body only                             {t['n']:>6} fired   {t['follow_pct']:>5}% followed",
    ])


if __name__ == "__main__":
    sys.exit(main())
