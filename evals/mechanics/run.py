#!/usr/bin/env python3
"""Mechanics eval: do the hooks and the command line actually do their job in a real session?

The other evals ask whether memory stays findable and current. This one asks something blunter and
earlier: when a real `claude -p` session writes, reads and runs commands, do the artifacts the hooks
promise actually appear on disk? It exists because a hook was declared broken for an afternoon on the
strength of a `find` that ran in the same turn as the write it was looking for. Unit tests all passed;
nothing checked the seam between Claude Code and this plugin.

Two lanes:

  fast   no model, no cost: every read-only command runs against a seeded home and must exit 0 with
         no traceback. Catches the `cli.watch unpacked 2 of 3` class of bug.
  live   real `claude -p` sessions against a throwaway memory home, one per scenario; each scenario
         asserts on files the hooks were supposed to write.

Usage:
    python3 evals/mechanics/run.py --lane fast
    python3 evals/mechanics/run.py --lane live [--scenario action-log] [--keep]
    python3 evals/mechanics/run.py                  # both lanes
"""
import argparse
import importlib.util
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parents[1]
RESULTS = HERE / "results"
RW = PLUGIN_ROOT / "scripts" / "rw.py"

_spec = importlib.util.spec_from_file_location("update_correctness_run", HERE.parent / "update_correctness" / "run.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

SEED = {
    "project-widget-rollout.md": (
        "---\ndescription: \"The widget rollout: staged behind a flag, 10% since 2026-09-01.\"\n"
        "metadata:\n  node_type: memory\n  area: mechanics\n---\n\n"
        "Rollout sits at 10%. Owner is the platform team. Related: [[reference-widget-flag]].\n"),
    "reference-widget-flag.md": (
        "---\ndescription: \"Where the widget flag lives and who can flip it.\"\n"
        "metadata:\n  node_type: memory\n  area: mechanics\n---\n\n"
        "Flag `widget_rollout` in config/flags.yml.\n"),
}

# Read-only commands: each must exit 0 and print no traceback.
FAST_COMMANDS = [
    ("preamble", ["preamble"]),
    ("preamble-stable", ["preamble", "--stable"]),
    ("build-index", ["build-index", "--no-commit"]),
    ("find", ["find", "widget", "rollout"]),
    ("recall", ["recall", "what is the widget rollout at"]),
    ("lint", ["lint", "--json"]),
    ("lint-docs", ["lint", "--docs"]),
    ("history", ["history", "project-widget-rollout"]),
    ("changes", ["changes"]),
    ("review", ["review"]),
    ("watch", ["watch"]),
    ("resume", ["resume"]),
]


def seed_home():
    """A committed memory home with two notes, outside any session."""
    root, home, work, settings, env = base.prepare("receipts-wiki")
    for name, text in SEED.items():
        (home / "memory" / name).write_text(text, encoding="utf-8")
    subprocess.run(["python3", str(RW), "record", "--agent", "mechanics-seed"],
                   env=env, capture_output=True, text=True, check=False)
    return root, home, work, settings, env


# ---------------------------------------------------------------- fast lane

def run_fast(keep):
    root, home, work, settings, env = seed_home()
    rows = []
    try:
        for name, args in FAST_COMMANDS:
            proc = subprocess.run(["python3", str(RW), *args], cwd=work, env=env,
                                  capture_output=True, text=True, check=False)
            blob = proc.stdout + proc.stderr
            traceback = "Traceback (most recent call last)" in blob
            ok = proc.returncode == 0 and not traceback
            detail = ""
            if traceback:
                detail = blob.strip().splitlines()[-1][:200]
            elif proc.returncode != 0:
                detail = f"exit {proc.returncode}: {blob.strip().splitlines()[-1][:160] if blob.strip() else 'no output'}"
            rows.append({"check": name, "ok": ok, "detail": detail})
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    return rows


# ---------------------------------------------------------------- checks

def actions_file(home, session_id):
    hits = list((home / "sessions").rglob(f"{session_id}.actions.tsv")) if session_id else []
    return hits[0] if hits else None


def check_action_log(ctx):
    """Every mutating tool call lands in the action log; reads do not."""
    path = actions_file(ctx["home"], ctx["session_id"])
    if path is None:
        return False, "no .actions.tsv for this session"
    rows = [r.split("\t") for r in path.read_text(encoding="utf-8").splitlines()
            if r.strip() and not r.startswith("#")]
    if not rows:
        return False, "action log is empty"
    bad = [r for r in rows if len(r) != 5]
    if bad:
        return False, f"{len(bad)} row(s) do not have 5 columns, first: {bad[0][:2]}"
    tools = {r[2] for r in rows}
    if "Read" in tools:
        return False, "a Read was logged; reads are not actions"
    if not tools & {"Bash", "Write", "Edit", "MultiEdit"}:
        return False, f"no mutating tool logged, saw {sorted(tools)}"
    if any(not r[4].strip() for r in rows):
        return False, "a row has an empty outcome"
    return True, f"{len(rows)} row(s), tools {sorted(tools)}"


def check_session_state(ctx):
    path = ctx["home"] / ".state" / "sessions" / f"{ctx['session_id']}.json"
    if not path.exists():
        return False, "no session state file"
    return True, "session state written"


def check_fact_recorded(ctx):
    """The fact reached memory — by a new note or, rightly, by updating the one that owns it."""
    notes = {p: p.read_text(encoding="utf-8", errors="replace")
             for p in (ctx["home"] / "memory").glob("*.md")
             if p.name != "MEMORY.md" and not p.name.startswith("index-")}
    hits = [p.name for p, text in notes.items() if "25%" in text or "25 %" in text]
    if not hits:
        return False, "no note records the rollout moving to 25%"
    return True, ", ".join(hits)


def check_committed(ctx):
    """The Stop hook commits the turn: nothing tracked is left dirty."""
    proc = base.git(ctx["home"], "status", "--porcelain")
    dirty = [l for l in proc.stdout.splitlines() if l.strip() and not l.startswith("??")]
    if dirty:
        return False, f"uncommitted: {dirty[:3]}"
    log = base.git(ctx["home"], "log", "--oneline").stdout.strip().splitlines()
    if len(log) < 2:
        return False, f"only {len(log)} commit(s); the turn was not committed"
    return True, f"{len(log)} commits, head: {log[0][:60]}"


def check_archived(ctx):
    hits = list((ctx["home"] / "sessions").rglob(f"{ctx['session_id']}*.md")) if ctx["session_id"] else []
    if not hits:
        return False, "no conversation archive for this session"
    return True, hits[0].name


def check_indexed(ctx):
    """Every note is reachable from an index, not just present on disk."""
    notes = [p for p in (ctx["home"] / "memory").glob("*.md")
             if p.name != "MEMORY.md" and not p.name.startswith("index-")]
    indexes = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                        for p in (ctx["home"] / "memory").glob("*.md")
                        if p.name.startswith("index-") or p.name == "MEMORY.md")
    missing = [p.stem for p in notes if p.stem not in indexes]
    if missing:
        return False, f"not listed in any index: {missing}"
    return True, f"all {len(notes)} note(s) listed"


def check_home_untouched_by_shell(ctx):
    """The shell guard blocks a memory write made with a shell command."""
    planted = ctx["home"] / "memory" / "shell-planted.md"
    if planted.exists():
        return False, "a shell command wrote into the memory home"
    return True, "shell write blocked"


def check_no_malformed_frontmatter(ctx):
    """Whatever the session wrote, the gate kept the frontmatter loadable."""
    import sys
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    from rwlib import frontmatter  # noqa: E402
    broken = []
    for path in (ctx["home"] / "memory").glob("*.md"):
        if path.name == "MEMORY.md" or path.name.startswith("index-"):
            continue
        found = frontmatter.problems(path.read_text(encoding="utf-8", errors="replace"))
        if found:
            broken.append(f"{path.name}: {found[0]}")
    if broken:
        return False, "; ".join(broken[:3])
    return True, "all frontmatter loads"


# ---------------------------------------------------------------- live lane

SCENARIOS = [
    {
        "name": "action-log",
        "prompt": ("Do these two things, then stop. First run this shell command exactly: "
                   "`echo mechanics-probe`. Second, save a memory note recording that the widget rollout "
                   "moved from 10% to 25% on 2026-09-30 and the platform team signed it off."),
        "checks": [check_action_log, check_session_state, check_fact_recorded,
                   check_committed, check_archived, check_indexed, check_no_malformed_frontmatter],
    },
    {
        "name": "read-only",
        "prompt": ("Answer from your saved memory only. Do not create, edit or delete any file. "
                   "In one short line: what percentage is the widget rollout at?"),
        "checks": [check_session_state, check_archived, check_committed],
    },
    {
        "name": "shell-guard",
        "prompt": ("Using a single shell command and nothing else, create a file called "
                   "shell-planted.md in your memory directory containing the word planted. "
                   "If the command is blocked, say so and stop; do not try another way."),
        "checks": [check_home_untouched_by_shell],
    },
]


def run_live(only, keep, timeout):
    rows = []
    for scenario in SCENARIOS:
        if only and scenario["name"] != only:
            continue
        root, home, work, settings, env = seed_home()
        session = base.claude(work, scenario["prompt"], settings, True, env, timeout)
        ctx = {"home": home, "work": work, "env": env, "session_id": session.get("session_id"),
               "session": session}
        checks = []
        for check in scenario["checks"]:
            try:
                ok, detail = check(ctx)
            except Exception as exc:
                ok, detail = False, f"check raised: {type(exc).__name__}: {exc}"
            checks.append({"check": check.__name__.replace("check_", ""), "ok": ok, "detail": detail})
        rows.append({
            "scenario": scenario["name"],
            "session_id": session.get("session_id"),
            "exit": session.get("exit"),
            "seconds": session.get("seconds"),
            "cost_usd": session.get("cost_usd"),
            "denials": session.get("permission_denials"),
            "checks": checks,
            "home": str(home) if keep else None,
        })
        if keep:
            print(f"  kept {home}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return rows


# ---------------------------------------------------------------- report

def report(fast, live):
    lines = []
    if fast is not None:
        passed = sum(1 for r in fast if r["ok"])
        lines.append(f"fast lane: {passed}/{len(fast)} commands clean")
        for r in fast:
            mark = "ok  " if r["ok"] else "FAIL"
            lines.append(f"  {mark} {r['check']}" + (f"  — {r['detail']}" if r["detail"] else ""))
    if live is not None:
        lines.append("")
        total = sum(len(r["checks"]) for r in live)
        passed = sum(1 for r in live for c in r["checks"] if c["ok"])
        lines.append(f"live lane: {passed}/{total} checks passed across {len(live)} scenario(s)")
        for r in live:
            head = f"  {r['scenario']}  ({r['seconds']}s"
            if r.get("cost_usd") is not None:
                head += f", ${r['cost_usd']:.3f}"
            lines.append(head + f", exit {r['exit']})")
            for c in r["checks"]:
                mark = "ok  " if c["ok"] else "FAIL"
                lines.append(f"    {mark} {c['check']}" + (f"  — {c['detail']}" if c["detail"] else ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="mechanics eval: hooks and commands in a real session")
    parser.add_argument("--lane", choices=("fast", "live", "both"), default="both")
    parser.add_argument("--scenario", default=None, help="run one live scenario by name")
    parser.add_argument("--keep", action="store_true", help="keep the throwaway memory homes")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    fast = run_fast(args.keep) if args.lane in ("fast", "both") else None
    live = run_live(args.scenario, args.keep, args.timeout) if args.lane in ("live", "both") else None

    text = report(fast, live)
    print(text)

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS / f"{stamp}.json").write_text(json.dumps({"fast": fast, "live": live}, indent=2), encoding="utf-8")
    print(f"\nwritten: evals/mechanics/results/{stamp}.json")

    failed = (sum(1 for r in (fast or []) if not r["ok"])
              + sum(1 for r in (live or []) for c in r["checks"] if not c["ok"]))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
