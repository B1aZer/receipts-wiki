#!/usr/bin/env python3
"""Dependency backtest: when a fact note is updated, do the notes that link it get updated too?

Runs over a memory home's own git history. No model calls, no network, nothing written: it answers
whether a `fact.updated` event predicts a change to the notes that declared a dependency on that
note, and by how much over chance.

    python3 evals/dependency/backtest.py                        # the ambient memory home
    python3 evals/dependency/backtest.py --home ~/.agents --window 2 --draws 3
    python3 evals/dependency/backtest.py --json

Method. For every commit carrying `Change: fact.updated memory/X.md`, the candidates are the notes
that contained `[[<name of X>]]` at that commit's parent — a dependency the author declared. For each
candidate the question is whether a *later* commit changed a line in it mentioning that name, found
with `git log -G`. Three buckets: `same` (the same commit, so the author handled it as one edit),
`later` (a gap, measured), `never`.

A rate on its own means nothing, because a note that is edited often will churn anyway, so the real
number is the lift over a placebo: the same pairs and the same window length, started at random times
that are not within one window of any real update of that note.

Two controls were tried first and both were invalid; they are kept here because the second is a trap
anyone measuring this would fall into:

  1. Comparing the window after each event with the window before it. The log ends at HEAD, so recent
     events have no room for an "after" window while "before" is always full. It reported a large
     negative lift.
  2. The same comparison restricted to events where both windows fit inside the log. Still wrong, and
     worse: every pair has a prior change, with no exceptions, because *acquiring the link is itself a
     change to the dependent's text about the note*. The before-window measures link creation.

Result on the author's home, 2026-10-06 (529 commits, 22.9 days, 2-day window, 3 placebo draws):
308 of 2,034 candidate pairs fall outside the log and are excluded; 11.3% of the remaining 1,726 changed after a real
event against 3.4% of 5,178 placebo windows — a lift of +7.9 points, about 3.3x chance. Real effect,
and far too diffuse to notify on: 4.4 declared dependents per event, of which about half of one needs
touching. That is the number any future dependency mechanism has to beat.
"""
import argparse
import json
import os
import random
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

UPDATED = re.compile(r"^Change: fact\.updated (memory/\S+)", re.M)
NAME = re.compile(r"^name:\s*(.+)$", re.M)


def git(home, *args):
    return subprocess.run(["git", "-C", str(home), *args], capture_output=True, text=True).stdout


def note_names(home):
    """file -> declared name. Memory files are never renamed, so the current tree is enough."""
    names = {}
    for rel in git(home, "ls-files", "memory/").split():
        base = rel.split("/")[-1]
        if not base.endswith(".md") or base == "MEMORY.md" or base.startswith("index-"):
            continue
        found = NAME.search(git(home, "show", f"HEAD:{rel}"))
        names[rel] = found.group(1).strip() if found else base[:-3].replace("_", "-")
    return names


def update_events(home, names):
    """[(sha, unix time, [updated note file, ...])] oldest first, and name -> [event times]."""
    events, by_name = [], defaultdict(list)
    for block in git(home, "log", "--format=%H %ct%n%B%n--END--", "--reverse").split("--END--\n"):
        block = block.strip("\n")
        if not block:
            continue
        head, _, body = block.partition("\n")
        sha, _, when = head.partition(" ")
        updated = [rel for rel in UPDATED.findall(body) if rel in names]
        if not updated:
            continue
        events.append((sha, int(when), updated))
        for rel in updated:
            by_name[names[rel]].append(int(when))
    return events, by_name


def run(home, window_days, draws, seed=11):
    home = Path(home).expanduser()
    names = note_names(home)
    events, by_name = update_events(home, names)
    stamps = [int(x) for x in git(home, "log", "--format=%ct").split() if x.strip()]
    first, last = min(stamps), max(stamps)
    window = window_days * 86400
    random.seed(seed)

    dependents, touches = {}, {}
    buckets, lags = Counter(), []
    pairs = no_inbound = event_notes = 0
    real_hit = real_n = placebo_hit = placebo_n = 0

    for sha, when, updated in events:
        for rel in updated:
            name = names[rel]
            event_notes += 1
            key = (sha, name)
            if key not in dependents:
                listed = git(home, "grep", "-l", "-F", f"[[{name}]]", f"{sha}^", "--", "memory/").split()
                found = [item.split(":", 1)[1] for item in listed if ":" in item]
                dependents[key] = [f for f in found if f != rel and f.endswith(".md")]
            if not dependents[key]:
                no_inbound += 1
                continue
            for dep in dependents[key]:
                pair = (dep, name)
                if pair not in touches:
                    pattern = r"\[\[" + re.escape(name) + r"\]\]"
                    touches[pair] = sorted(int(x) for x in
                                           git(home, "log", "--format=%ct", f"-G{pattern}", "--", dep).split()
                                           if x.strip())
                times = touches[pair]
                pairs += 1

                if any(t == when for t in times) and sha in git(home, "log", "--format=%H", "--", dep).split():
                    buckets["same"] += 1
                else:
                    after = [t for t in times if t > when]
                    if after:
                        buckets["later"] += 1
                        lags.append((min(after) - when) / 86400)
                    else:
                        buckets["never"] += 1

                # the controlled comparison, on pairs whose window fits inside the log
                if when + window > last:
                    continue
                real_n += 1
                if any(when < t <= when + window for t in times):
                    real_hit += 1
                drawn = tries = 0
                while drawn < draws and tries < 60:
                    tries += 1
                    start = random.randint(first, last - window)
                    if any(abs(start - e) < window for e in by_name[name]):
                        continue
                    drawn += 1
                    placebo_n += 1
                    if any(start < t <= start + window for t in times):
                        placebo_hit += 1

    lags.sort()
    return {
        "home": str(home),
        "span_days": round((last - first) / 86400, 1),
        "update_events": len(events),
        "event_notes": event_notes,
        "events_with_no_inbound_link": no_inbound,
        "candidate_pairs": pairs,
        "buckets": dict(buckets),
        "lag_days": {"median": round(lags[len(lags) // 2], 1) if lags else None,
                     "max": round(lags[-1], 1) if lags else None, "n": len(lags)},
        "window_days": window_days,
        "real": {"hit": real_hit, "n": real_n, "rate": round(real_hit / real_n, 4) if real_n else None},
        "placebo": {"hit": placebo_hit, "n": placebo_n,
                    "rate": round(placebo_hit / placebo_n, 4) if placebo_n else None},
        "lift": (round(real_hit / real_n - placebo_hit / placebo_n, 4)
                 if real_n and placebo_n else None),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--home", default=os.environ.get("RECEIPTS_WIKI_HOME", "~/.agents"))
    parser.add_argument("--window", type=int, default=2, help="window in days (default 2)")
    parser.add_argument("--draws", type=int, default=3, help="placebo windows per pair (default 3)")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run(args.home, args.window, args.draws, args.seed)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"{result['home']}: {result['update_events']} fact.updated commits over {result['span_days']} days")
    print(f"  events on notes nothing links: {result['events_with_no_inbound_link']}")
    print(f"  candidate (event, dependent) pairs: {result['candidate_pairs']}")
    for bucket in ("same", "later", "never"):
        count = result["buckets"].get(bucket, 0)
        share = count / result["candidate_pairs"] if result["candidate_pairs"] else 0
        print(f"    {bucket:6} {count:5} ({share:.0%})")
    lag = result["lag_days"]
    if lag["n"]:
        print(f"  catching up later took a median of {lag['median']} days (max {lag['max']}, n={lag['n']})")
    print(f"\n  {result['window_days']}-day window:")
    print(f"    after a real event:   {result['real']['hit']}/{result['real']['n']} = {result['real']['rate']:.1%}")
    print(f"    after a placebo time: {result['placebo']['hit']}/{result['placebo']['n']} = {result['placebo']['rate']:.1%}")
    print(f"    lift: {result['lift']:+.1%}")
    print("\n  A mechanism that notifies per pair is right at the real rate above. Beat it or do not build it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
