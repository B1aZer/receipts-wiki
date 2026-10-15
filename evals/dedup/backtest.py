#!/usr/bin/env python3
"""Dedup backtest: when two sessions write up the same finding, would the topic scorer have said so?

Runs over a memory home's own git history. No model calls, no network, nothing written.

    python3 evals/dedup/backtest.py                         # the ambient memory home
    python3 evals/dedup/backtest.py --home ~/.agents --window 12 --draws 3
    python3 evals/dedup/backtest.py --json

WHAT IS BEING DECIDED. `topics.same_topic()` already exists and already works -- it ranks a new note's
name and description against the committed corpus with BM25 and warns above `SAME_TOPIC = 3.5`. It is
gated on file CREATION (`hooks.py`: `is_new = rel not in pending and head_content is None`), and the
observed collision pattern is one session *creating* a note while another *appends the same finding as a
section to an existing note*. An append has `head_content is not None`, so the check is never consulted.
Extending it past creation needs a trigger, and a trigger that fires on healthy memory is worse than the
gap: this measures whether the pairing signal is real before anything is built on it.

METHOD. From the log, every note gets two kinds of event: `created` (its earliest commit here) and
`appended` (a commit adding at least --added lines to it). Any two events on *different* notes inside
--window hours are a candidate pair. Each pair is scored with the SAME arithmetic `same_topic` uses --
BM25 over the other note's body plus a boosted label field, divided by the number of distinct query
words -- so the 3.5 threshold means here what it means in the hook. The score is symmetric by taking the
better of the two directions, because either session could have been the one warned.

The outcome is whether the pair was later RESOLVED: one of the two deleted, a `Supersedes` line naming
the other, a `status: retired`, or one collapsing to a pointer (losing most of its body while gaining a
link to the other). That is the author doing by hand what the warning would have asked for.

A rate alone means nothing, because two notes written the same night are both new and both likely to be
edited again. The number is the lift over a placebo: pairs drawn from the same notes with the time
relationship broken -- events more than --window hours apart -- scored and resolved-tested identically.

⚠️ INSTRUMENT FIRST, RATE SECOND. Two pairs are known positives, recorded the night they happened:

    feedback_fixing_deletes_the_detector.md   <-> feedback_check_can_fail.md
    feedback_never_compare_across_measurements.md <-> feedback_denominator_rule.md

Each is a new note against an appended section carrying the same finding. If the scorer cannot place
these near the top of the pair distribution there is no rate worth reading, and this script says so and
stops rather than printing a number.

⭐ AND THE CHECK IS A PERCENTILE, NOT A SCORE, BECAUSE THE CALIBRATION IS A RANK CLAIM.
`same_topic`'s docstring reads: "On a 203-note home, 3.5 put the known duplicate pairs in the top
tenth." That is a statement about RANK; the code implements it as an absolute threshold, and the two
coincide only at the corpus size it was tuned on. This home now has 571 active notes. Measured
2026-10-15 over 24,090 random pairs:

    median 0.29 | 90th 0.77 | 99th 1.75 | 99.9th 3.07 | max 6.05
    known duplicate pairs: 1.20 (96.9th percentile) and 1.34 (97.6th)
    SAME_TOPIC = 3.5 keeps the top 0.037% of pairs

⚠️ SCORING USES HEAD TEXTS, measured before being relied on: the two known pairs score 1.20 / 1.34 at
HEAD against 0.95-1.51 across every nearby historical commit, so reconstructing each side as it was at
the pairing commit does not move where a pair sits in the distribution -- and it costs two git calls per
pair, which is what made the first version of this script fail to finish. One authority, stated.

⚠️ So the shipped duplicate check CANNOT FIRE on the two pairs it was calibrated against. The signal is
intact -- both are top-decile, as the docstring intended -- and the constant has drifted out from under
it as the corpus nearly tripled. A percentile that became an absolute constant, erring toward silence:
the same shape as a version string that was descriptive until an updater decided on it, and as a noise
floor that is permissive once it is stale. Fixing the extension-past-creation question without fixing
this would build a trigger for a check that never speaks.

KNOWN LIMITS, stated because they bound the result rather than decorate it:

  1. The IDF and average document length come from the corpus as it is NOW, not as it was at each
     commit. Reconstructing a corpus per commit is possible and expensive; the background word
     distribution moves slowly, while the thing being tested -- one pair's score against a fixed
     threshold -- is dominated by the two documents. A pair scored today against a bigger corpus scores
     slightly LOWER, since IDF falls as a word spreads, so this errs toward under-reporting.
  2. `created` means "earliest commit in this log", so a note older than the log's first commit looks
     created at its first appearance here. Those events are excluded when --since is given.
  3. Resolution is detected from git, so a pair resolved by a decision not written down is invisible and
     counts as unresolved. Again a floor, not a ceiling.
  4. A pair can be resolved for reasons unrelated to duplication. That is exactly what the placebo
     controls for, and it is why the lift rather than the rate is the answer.
"""
RESULT on the author's home, 2026-10-16 (571 active notes, 958 authoring events, 12h window, top-decile
threshold 0.77, placebo exposure-matched within 3 days):

    similarity   33.1% of co-occurring pairs clear the threshold, against 20.0% of exposure-matched
                 pairs that do not co-occur. So co-occurrence DOES predict similarity, 1.7x.
    resolution   0 of 1,985 co-occurring pairs above threshold were later resolved. 26 of 3,364
                 placebo pairs were. Lift -0.8 points.

⭐ VERDICT: DO NOT BUILD THE EXTENSION PAST CREATION. Not because the selector is weak -- because the
OUTCOME almost never happens. Twenty-six relational resolutions in the whole history: authors here do
not merge, retire or supersede a duplicate pair, they let both notes stand. ⚠️ The two known-positive
pairs are the proof, and they are the collisions that motivated the proposal in the first place: both
are still separate notes, unresolved, a week later. A warning whose requested action is one nobody
takes has no demonstrated value, and the 2-part proposal's second half is now unsupported.

The FIRST half still stands on its own reasoning rather than on this number: adding other sessions'
uncommitted writes to the corpus addresses concurrency, which no create-time check can see, and it does
not depend on anyone resolving anything.

⭐ AND THE FINDING THAT MATTERS MORE THAN EITHER, measured on the way: SAME_TOPIC = 3.5 keeps the top
0.037% of pairs on this corpus, so the SHIPPED duplicate check cannot fire on the two pairs it was
calibrated against. See the instrument section below. That is a live defect in a check that exists,
which outranks a new trigger for one.

⚠️ THREE INVALID OUTCOME MEASURES WERE TRIED FIRST, all of which produced a confident wrong number, and
they are kept here because each is a trap anyone measuring this would fall into:

  1. An unmatched placebo (any two events more than one window apart). Resolution is cumulative, the
     real arm skews to the dense recent log, and the placebo drew from the whole history -- so it had
     longer to resolve. Reported -1.5 points. Matching on exposure made the gap WIDER, which is how the
     confound was shown not to be the whole story.
  2. "Collapsed to a pointer" as "a short note links the other". That describes most cross-links in a
     healthy home: it scored `project_citrus_lending_bot <-> reference_magic_eden_api_key` as resolved.
     The real test is that the body SHRANK, which needs historical text -- dropped earlier to make the
     script finish, so a speed trade had silently invalidated the measurement.
  3. ⭐ `deleted` and `retired` taken as pair outcomes. They are properties of ONE note. Any pair that
     happened to contain a retired note counted, and since retired notes are a fixed population the
     placebo collected them at a high rate: -4.1 points, built on pairs like
     `feedback_git_push <-> project_ai_memory_methodology` that have no relationship at all.
     **A rate from a non-relational outcome measures the population, not the pairing.** Every outcome
     now needs evidence it was about the other note.

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from rwlib import frontmatter, topics  # noqa: E402

KNOWN_POSITIVES = [
    ("feedback_fixing_deletes_the_detector.md", "feedback_check_can_fail.md"),
    ("feedback_never_compare_across_measurements.md", "feedback_denominator_rule.md"),
]


def git(home, *args):
    out = subprocess.run(["git", "-C", str(home)] + list(args), capture_output=True, text=True, check=False)
    return out.stdout if out.returncode == 0 else ""


def events(home, added_threshold):
    """[(epoch, rel, kind, sha)] for every note creation and substantial append in the log."""
    raw = git(home, "log", "--reverse", "--format=C %H %at", "--numstat", "--", "memory")
    seen, out = set(), []
    sha = stamp = None
    for line in raw.splitlines():
        if line.startswith("C "):
            _, sha, at = line.split(" ", 2)
            stamp = int(at)
            continue
        parts = line.split("\t")
        if len(parts) != 3 or not sha:
            continue
        plus, minus, rel = parts
        if not rel.endswith(".md") or not rel.startswith("memory/") or rel.count("/") != 1:
            continue
        if Path(rel).name in ("MEMORY.md",) or Path(rel).name.startswith("index-"):
            continue        # generated, so its churn is not an authoring event
        try:
            plus_n = int(plus)
        except ValueError:
            continue        # binary or rename marker
        if rel not in seen:
            seen.add(rel)
            out.append((stamp, rel, "created", sha))
        elif plus_n >= added_threshold:
            out.append((stamp, rel, "appended", sha))
    return out


def text_at(home, sha, rel):
    return git(home, "show", f"{sha}:{rel}")


def query_of(text):
    fm, _ = frontmatter.split(text)
    return f"{frontmatter.get(fm, 'name') or ''} {frontmatter.get(fm, 'description') or ''}"


class Scorer:
    """`same_topic`'s arithmetic, applied to one document instead of the whole corpus.

    Reuses the live Corpus for idf and average length so the number is comparable with SAME_TOPIC;
    the score is divided by the distinct query words exactly as `same_topic` divides it.
    """

    def __init__(self, home):
        self.corpus = topics.Corpus(home)

    def score(self, query, other_text):
        query_words = set(topics.words(query))
        if len(query_words) < 2:
            return 0.0
        fm, body_text = frontmatter.split(other_text)
        label = Counter(topics.words(f"{frontmatter.get(fm, 'name') or ''} "
                                     f"{frontmatter.get(fm, 'description') or ''}"))
        body = Counter(topics.words(body_text))
        length = sum(body.values())
        total = 0.0
        for w in query_words & (set(label) | set(body)):
            idf = self.corpus.idf.get(w, math.log(1 + (len(self.corpus.items) + 0.5) / 0.5))
            tf = body.get(w, 0)
            total += idf * tf * (topics.K1 + 1) / (
                tf + topics.K1 * (1 - topics.B + topics.B * length / self.corpus.average))
            if w in label:
                total += topics.LABEL_WEIGHT * idf
        return total / len(query_words)

    def pair(self, text_a, text_b):
        """Symmetric: either session could have been the one warned."""
        return max(self.score(query_of(text_a), text_b), self.score(query_of(text_b), text_a))


SUPERSEDES = re.compile(r"^\s*(?:\*\*)?Supersedes(?:\*\*)?\s*:", re.I | re.M)


def name_of(rel):
    return Path(rel).name[:-3].replace("_", "-")


class Resolutions:
    """Everything needed to answer "was this pair resolved?" without touching git per pair.

    One log pass for deletions and one read per surviving note. A pair resolved by a decision nobody
    wrote down stays invisible, which makes every rate here a floor rather than a ceiling.
    """

    def __init__(self, home):
        self.home = home
        self._shrink_cache = {}
        self.deleted = {}
        raw = git(home, "log", "--format=D %at", "--diff-filter=D", "--name-only", "--", "memory")
        stamp = None
        for line in raw.splitlines():
            if line.startswith("D "):
                stamp = int(line.split(" ", 1)[1])
            elif line.strip() and stamp:
                self.deleted.setdefault(line.strip(), stamp)
        self.head = {}
        for item in topics.indexer.notes(home):
            rel = f"memory/{item['file']}"
            fm, body = frontmatter.split(item["text"])
            self.head[rel] = {
                "supersedes": bool(SUPERSEDES.search(item["text"])),
                "retired": str(item.get("status") or "").lower() == "retired",
                "links": set(re.findall(r"\[\[([^\]|#]+)", item["text"])),
                "body": len(body),
                "text": item["text"],
            }

    def _linked(self, survivor, dead):
        """Does the surviving note point at the dead one? The cheapest relational evidence there is."""
        head = self.head.get(survivor)
        return bool(head and name_of(dead) in head["links"])

    def _mentions(self, survivor, dead, when):
        """Either the survivor links the dead note now, or the dead note linked the survivor at the end."""
        if self._linked(survivor, dead):
            return True
        key = ("last", dead, when)
        if key not in self._shrink_cache:
            sha = git(self.home, "rev-list", "-1", f"--before=@{when}", "HEAD").strip()
            last = git(self.home, "show", f"{sha}:{dead}") if sha else ""
            self._shrink_cache[key] = name_of(survivor) in last
        return self._shrink_cache[key]

    def _shrank(self, rel, after):
        """Did this note's body lose most of its length after `after`? One git read, cached."""
        key = (rel, after)
        if key in self._shrink_cache:
            return self._shrink_cache[key]
        sha = git(self.home, "rev-list", "-1", f"--before=@{after}", "HEAD").strip()
        answer = False
        if sha:
            was = git(self.home, "show", f"{sha}:{rel}")
            if was:
                _, old_body = frontmatter.split(was)
                if len(old_body) > 400:
                    answer = self.head[rel]["body"] < 0.5 * len(old_body)
        self._shrink_cache[key] = answer
        return answer

    def how(self, rel_a, rel_b, after):
        """⚠️ EVERY outcome has to be RELATIONAL, which two of these were not.

        The first version counted a pair as resolved if either note was later deleted or carried
        `status: retired`. Those are properties of ONE note, not of the pair -- so any pair that
        happened to contain a retired note scored as a resolution, and since retired notes are a fixed
        population the placebo arm collected them at a high rate. It reported a -4.1 point lift built
        almost entirely on pairs like `feedback_git_push <-> project_ai_memory_methodology`, which have
        no relationship at all. A rate from a non-relational outcome measures the population, not the
        pairing.

        So a death now counts only with evidence that it was about the OTHER note: the survivor links
        it, or its own last text linked the survivor.
        """
        for rel, other in ((rel_a, rel_b), (rel_b, rel_a)):
            when = self.deleted.get(rel)
            if when and when >= after and self._mentions(other, rel, when):
                return "deleted"
        for rel, other in ((rel_a, rel_b), (rel_b, rel_a)):
            head = self.head.get(rel)
            if not head:
                continue
            if head["retired"] and self._linked(other, rel):
                return "retired"
            if head["supersedes"] and name_of(other) in head["text"]:
                return "superseded"
            if name_of(other) in head["links"] and head["body"] < 1200:
                # ⚠️ A short note linking another is NOT evidence of a collapse: that describes most
                # cross-links in a healthy home, and the first run of this backtest proved it by
                # scoring `project_citrus_lending_bot <-> reference_magic_eden_api_key` as resolved.
                # A collapse means the body SHRANK -- which needs the historical text I had dropped to
                # make this fast, so the speed trade had quietly invalidated the outcome measure.
                # Restored here only for pairs that both clear the threshold AND link each other, which
                # is a small enough subset to afford one git read.
                if self._shrank(rel, after):
                    return "collapsed to a pointer"
        return None


def pairs_within(evts, hours):
    span = hours * 3600
    out = []
    for i, (t_a, rel_a, kind_a, sha_a) in enumerate(evts):
        for t_b, rel_b, kind_b, sha_b in evts[i + 1:]:
            if t_b - t_a > span:
                break
            if rel_a == rel_b:
                continue
            out.append(((t_a, rel_a, kind_a, sha_a), (t_b, rel_b, kind_b, sha_b)))
    return out


def pairs_apart(evts, hours, per_real, rng, real_pairs, match_days):
    """Placebo: the same notes, co-occurrence broken, EXPOSURE MATCHED.

    ⚠️ The first version drew any two events more than `hours` apart and reported a negative lift. That
    was an artefact, not a result: resolution is cumulative, the real arm requires two events within one
    window so it skews to the dense recent log, and an unmatched placebo drawn from the whole history
    skews older and has had longer to be resolved. Each placebo pair is now matched to a real pair on
    the timestamp of its LATER event, so time-to-HEAD is held roughly constant.

    Same family as the two invalid controls kept in evals/dependency/backtest.py, which are there
    because anyone measuring this falls into one of them.
    """
    import bisect
    span = hours * 3600
    match = match_days * 86400
    by_time = sorted(evts, key=lambda e: e[0])
    stamps = [e[0] for e in by_time]
    out = []
    for real in real_pairs:
        target = max(real[0][0], real[1][0])
        lo = bisect.bisect_left(stamps, target - match)
        hi = bisect.bisect_right(stamps, target + match)
        nearby = by_time[lo:hi]
        if len(nearby) < 2:
            continue
        for _ in range(per_real):
            for _try in range(40):
                a, b = rng.sample(nearby, 2)
                if a[1] == b[1] or abs(a[0] - b[0]) <= span:
                    continue
                out.append((a, b) if a[0] <= b[0] else (b, a))
                break
    return out


def measure(scorer, pairs, threshold, resolutions, head_text):
    above = []
    for a, b in pairs:
        text_a, text_b = head_text.get(a[1]), head_text.get(b[1])
        if not text_a or not text_b:
            continue        # one of the pair is gone from HEAD, so nothing can be scored or resolved
        score = scorer.pair(text_a, text_b)
        if score >= threshold:
            later = max(a[0], b[0])
            above.append((score, a[1], b[1], resolutions.how(a[1], b[1], later)))
    hits = [row for row in above if row[3]]
    return above, hits


def distribution(scorer, rng, sample_size=220):
    """Pair scores over a random sample of the live corpus, sorted. The reference for any threshold."""
    items = scorer.corpus.items
    sample = rng.sample(items, min(sample_size, len(items)))
    scores = []
    for i, a in enumerate(sample):
        for b in sample[i + 1:]:
            scores.append(scorer.pair(a["text"], b["text"]))
    scores.sort()
    return scores


def quantile(scores, q):
    if not scores:
        return 0.0
    return scores[min(len(scores) - 1, int(len(scores) * q))]


def percentile_of(scores, value):
    if not scores:
        return 0.0
    return 100.0 * sum(1 for s in scores if s < value) / len(scores)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", default=os.environ.get("RECEIPTS_WIKI_HOME") or str(Path.home() / ".agents"))
    p.add_argument("--window", type=float, default=12.0, help="hours between two events to pair them (default 12)")
    p.add_argument("--added", type=int, default=25, help="added lines that count as a substantial append (default 25)")
    p.add_argument("--threshold", type=float, default=None,
                   help="absolute pair score to count as a warning; default is this corpus's top decile, "
                        "since the calibration being tested is a rank claim and the shipped constant has "
                        f"drifted (SAME_TOPIC={topics.SAME_TOPIC})")
    p.add_argument("--draws", type=int, default=3, help="placebo draws per real pair (default 3)")
    p.add_argument("--max-pairs", type=int, default=6000, dest="max_pairs",
                   help="cap on co-occurring pairs scored, sampled at random when exceeded (default 6000)")
    p.add_argument("--match", type=float, default=3.0,
                   help="days within which a placebo pair's later event must fall beside its matched real "
                        "pair's, holding time-to-HEAD constant (default 3)")
    p.add_argument("--seed", type=int, default=20261015)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    home = Path(args.home).expanduser()
    if not (home / ".git").exists():
        print(f"{home} is not a git repository", file=sys.stderr)
        return 2
    scorer = Scorer(home)
    rng = random.Random(args.seed)
    resolutions = Resolutions(home)
    head_text = {rel: data["text"] for rel, data in resolutions.head.items()}

    # ---- the instrument, before any rate, and in the calibration's own terms ----
    scores = distribution(scorer, rng)
    top_decile, top_pct = quantile(scores, 0.90), quantile(scores, 0.99)
    checks = []
    for a, b in KNOWN_POSITIVES:
        text_a, text_b = git(home, "show", f"HEAD:memory/{a}"), git(home, "show", f"HEAD:memory/{b}")
        if not text_a or not text_b:
            checks.append({"pair": [a, b], "score": None, "percentile": None,
                           "note": "one or both notes are gone from HEAD"})
            continue
        score = scorer.pair(text_a, text_b)
        checks.append({"pair": [a, b], "score": round(score, 2),
                       "percentile": round(percentile_of(scores, score), 1), "note": ""})
    alive = [c for c in checks if c["score"] is not None]
    passing = [c for c in alive if c["percentile"] >= 90.0]

    threshold = args.threshold if args.threshold is not None else round(top_decile, 2)
    evts = events(home, args.added)
    report = {"home": str(home), "events": len(evts), "window_hours": args.window,
              "notes": len(scorer.corpus.items), "pairs_sampled": len(scores),
              "quantiles": {"median": round(quantile(scores, 0.5), 2), "p90": round(top_decile, 2),
                            "p99": round(top_pct, 2), "p999": round(quantile(scores, 0.999), 2),
                            "max": round(scores[-1], 2) if scores else 0.0},
              "same_topic_constant": topics.SAME_TOPIC,
              "same_topic_keeps_top_pct": round(100.0 - percentile_of(scores, topics.SAME_TOPIC), 3),
              "threshold": threshold, "instrument": checks}

    if not alive or len(passing) < len(alive):
        report["verdict"] = ("INSTRUMENT FAILED: a known duplicate pair is not in the top decile of the "
                             "pair distribution, so the signal itself is absent and no rate means anything")
        print(json.dumps(report, indent=2) if args.json else _render(report, None, None))
        return 1

    all_real = pairs_within(evts, args.window)
    real = all_real if len(all_real) <= args.max_pairs else rng.sample(all_real, args.max_pairs)
    placebo = pairs_apart(evts, args.window, args.draws, rng, real, args.match)
    real_above, real_hits = measure(scorer, real, threshold, resolutions, head_text)
    fake_above, fake_hits = measure(scorer, placebo, threshold, resolutions, head_text)

    rate = len(real_hits) / len(real_above) * 100 if real_above else 0.0
    base = len(fake_hits) / len(fake_above) * 100 if fake_above else 0.0
    report.update({"pairs_co_occurring": len(all_real), "pairs_real": len(real), "pairs_real_above": len(real_above),
                   "resolved_real": len(real_hits), "rate_real_pct": round(rate, 1),
                   "pairs_placebo": len(placebo), "pairs_placebo_above": len(fake_above),
                   "resolved_placebo": len(fake_hits), "rate_placebo_pct": round(base, 1),
                   "lift_points": round(rate - base, 1),
                   "share_real_above_pct": round(100.0 * len(real_above) / len(real), 1) if real else 0.0,
                   "share_placebo_above_pct": round(100.0 * len(fake_above) / len(placebo), 1) if placebo else 0.0,
                   "examples": [{"score": round(s, 2), "a": a, "b": b, "how": how}
                                for s, a, b, how in sorted(real_hits, reverse=True)[:8]]})
    print(json.dumps(report, indent=2) if args.json else _render(report, real_above, fake_above))
    return 0


def _render(report, real_above, fake_above):
    q = report["quantiles"]
    lines = [f"home             {report['home']}",
             f"active notes     {report['notes']}   (SAME_TOPIC = {report['same_topic_constant']} was tuned on 203)",
             f"authoring events {report['events']}  (creations + appends over {report['window_hours']}h windows)",
             "",
             f"PAIR SCORE DISTRIBUTION over {report['pairs_sampled']:,} random pairs",
             f"  median {q['median']}   90th {q['p90']}   99th {q['p99']}   99.9th {q['p999']}   max {q['max']}",
             f"  ** SAME_TOPIC = {report['same_topic_constant']} keeps the top {report['same_topic_keeps_top_pct']}% of pairs",
             "",
             "INSTRUMENT CHECK against known duplicate pairs (must be top decile, the calibration's own terms)"]
    for check in report["instrument"]:
        mark = "?" if check["percentile"] is None else ("PASS" if check["percentile"] >= 90.0 else "FAIL")
        pct = "" if check["percentile"] is None else f"{check['percentile']:>5}th pct"
        lines.append(f"  {mark:5} {check['score']:>5}  {pct}  {check['pair'][0]}  <->  {check['pair'][1]} {check['note']}")
    lines.append(f"  threshold used for the rate below: {report['threshold']}")
    if "verdict" in report:
        lines += ["", "** " + report["verdict"]]
        return "\n".join(lines)
    lines += ["",
              f"real     {report['pairs_real_above']:>5} pairs above threshold of {report['pairs_real']:>6} paired   "
              f"{report['resolved_real']:>4} later resolved   {report['rate_real_pct']:>5}%",
              f"placebo  {report['pairs_placebo_above']:>5} pairs above threshold of {report['pairs_placebo']:>6} drawn    "
              f"{report['resolved_placebo']:>4} later resolved   {report['rate_placebo_pct']:>5}%",
              f"lift     {report['lift_points']:+} points",
              "",
              f"SIMILARITY, a separate question from resolution:",
              f"  {report['share_real_above_pct']}% of co-occurring pairs clear the threshold, against "
              f"{report['share_placebo_above_pct']}% of exposure-matched pairs that do not co-occur"]
    if report["examples"]:
        lines += ["", "resolved pairs, best scoring first:"]
        for row in report["examples"]:
            lines.append(f"  {row['score']:>6}  {row['how']:<20} {row['a']}  <->  {row['b']}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
