#!/usr/bin/env python3
"""Update-correctness eval: after a correction, does memory give the current value, and at what cost?

Two arms run the same scenarios with the same model and prompts:
  baseline       Claude Code auto memory only
  receipts-wiki  the same, plus this plugin loaded with --plugin-dir, and a memory home set up the way
                 the setup skill leaves it: a git repository with one setup commit and an AGENTS.md holding
                 the template's Memory section only (its example rules for other work would add behaviour
                 that has nothing to do with memory)

Each scenario gets a fresh temporary directory per arm with a memory home and a separate, empty project
directory that the sessions run in, as in real use. Three separate `claude -p` sessions:
  1. teach    the user states facts and asks the agent to remember them
  2. correct  the user corrects one fact, explicitly or implicitly
  3. ask      questions answered from memory only
After the teach session the runner checks that the taught fact reached a memory note ('seeded'). When it
did not, that arm had nothing to correct, and the scenario does not measure update handling for it.

After the ask session the runner also checks the trail: whether the old value and the evidence for the change
('trail' in scenarios.json) are still in a memory note, or, for receipts-wiki, in the git history of memory.

Sessions load no user or local settings (--setting-sources project), so the user's own hooks and plugins
stay out. Answers are graded by fixed string checks (scenarios.json), not by a model judge, so grading is
cheap and repeatable but crude: read the saved answers before trusting a number. Time, model turns, output
tokens and cost come from Claude Code's JSON result for each session.

Scenarios are written for this repository and modelled on STALE (arXiv:2605.06527) and
Supersede (arXiv:2606.27472).

Usage:
    python3 evals/update_correctness/run.py --dry-run
    python3 evals/update_correctness/run.py --arm both [--scenario ttl-explicit] [--keep]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parents[1]
RESULTS = HERE / "results"
ARMS = ("baseline", "receipts-wiki")
PHASES = ("teach", "correct", "ask")
FIND_RULE = "Bash(python3 *receipts-wiki*/scripts/rw.py find *)"

ASK = (
    "Answer from your saved memory only. Do not create, edit or delete any files in this session. "
    "Reply with exactly {count} numbered lines and nothing else, one short answer per question.\n\n{questions}"
)


def claude(cwd, prompt, settings, with_plugin, env, timeout, extra_args=()):
    command = ["claude", "-p", "--settings", str(settings), "--setting-sources", "project",
               "--permission-mode", "acceptEdits", "--output-format", "json", *extra_args]
    if with_plugin:
        command += ["--plugin-dir", str(PLUGIN_ROOT)]
    command.append(prompt)
    started = time.time()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                                timeout=timeout, stdin=subprocess.DEVNULL, check=False)
        stdout, code = result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        stdout, code = "", "timeout"
    session = {"prompt": prompt, "exit": code, "seconds": round(time.time() - started, 1)}
    try:
        data = json.loads(stdout)
    except ValueError:
        data = {}
    usage = data.get("usage") or {}
    session.update({
        "output": data.get("result", stdout),
        "session_id": data.get("session_id"),
        "model_turns": data.get("num_turns"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": data.get("total_cost_usd"),
        "permission_denials": len(data.get("permission_denials") or []),
        "is_error": data.get("is_error"),
    })
    return session


def split_answers(output, count):
    answers = {}
    for line in str(output).splitlines():
        match = re.match(r"^\s*(\d+)[.):]\s*(.*)$", line)
        if match and 1 <= int(match.group(1)) <= count and int(match.group(1)) not in answers:
            answers[int(match.group(1))] = match.group(2).strip()
    return [answers.get(index, "") for index in range(1, count + 1)]


def grade(answer, question):
    lowered = answer.lower()
    if "expect_all" in question:
        return all(item.lower() in lowered for item in question["expect_all"])
    return any(item.lower() in lowered for item in question.get("expect_any", []))


def notes_text(home):
    parts = []
    for path in sorted((home / "memory").glob("*.md")):
        if path.name != "MEMORY.md" and not path.name.startswith("index-"):
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts).lower()


def git(home, *args):
    return subprocess.run(["git", *args], cwd=home, capture_output=True, text=True, check=False)


def memory_rules(home):
    """The Memory section of templates/AGENTS.md, pointed at this eval's memory home."""
    text = (PLUGIN_ROOT / "templates" / "AGENTS.md").read_text(encoding="utf-8").replace("~/.agents", str(home))
    start = text.index("## Memory")
    end = text.find("\n## ", start + 1)
    return "# AGENTS.md\n\n" + text[start:end if end != -1 else len(text)].strip() + "\n"


def prepare(arm):
    root = Path(tempfile.mkdtemp(prefix=f"rw-eval-{arm}-"))
    home, work = root / "home", root / "work"
    (home / "memory").mkdir(parents=True)
    work.mkdir()
    settings = root / "eval-settings.json"
    config = {
        "autoMemoryDirectory": str(home / "memory"),
        "claudeMdExcludes": [str(Path.home() / ".claude" / "CLAUDE.md")],
    }
    if arm == "receipts-wiki":
        # As the setup skill leaves it: the memory search command is allowed.
        config["permissions"] = {"allow": [FIND_RULE]}
    settings.write_text(json.dumps(config))
    env = dict(os.environ)
    env.pop("RECEIPTS_WIKI_HOME", None)
    if arm == "receipts-wiki":
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "eval"], ["config", "user.email", "eval@example.com"]):
            git(home, *args)
        (home / ".gitignore").write_text("sessions/\n.state/\n")
        (home / "AGENTS.md").write_text(memory_rules(home), encoding="utf-8")
        env["RECEIPTS_WIKI_HOME"] = str(home)
        # `claude -p` sessions count as unattended; the eval stands in for a user, so it gets the full plugin.
        env["RECEIPTS_WIKI_ATTENDED"] = "1"
        env["RECEIPTS_WIKI_CLAUDE_SETTINGS"] = str(settings)
        subprocess.run(["python3", str(PLUGIN_ROOT / "scripts" / "rw.py"), "record", "--agent", "eval-setup"],
                       env=env, capture_output=True, text=True, check=True)
    return root, home, work, settings, env


def run_scenario(scenario, arm, keep, timeout):
    root, home, work, settings, env = prepare(arm)
    with_plugin = arm == "receipts-wiki"
    sessions = {"teach": claude(work, scenario["teach"], settings, with_plugin, env, timeout)}
    seeded = all(item.lower() in notes_text(home) for item in scenario.get("seeded", []))
    sessions["correct"] = claude(work, scenario["correct"], settings, with_plugin, env, timeout)
    questions = scenario["questions"]
    prompt = ASK.format(count=len(questions), questions="\n".join(f"{i}. {q['q']}" for i, q in enumerate(questions, 1)))
    sessions["ask"] = claude(work, prompt, settings, with_plugin, env, timeout)
    answers = split_answers(sessions["ask"]["output"], len(questions))
    graded = [{"kind": q["kind"], "question": q["q"], "answer": a, "pass": grade(a, q)} for q, a in zip(questions, answers)]
    memory = {path.name: path.read_text(encoding="utf-8", errors="replace") for path in sorted((home / "memory").glob("*.md"))}
    files = notes_text(home)
    history = git(home, "log", "-p", "--", "memory").stdout.lower() if with_plugin else ""
    trail = [item.lower() for item in scenario.get("trail", [])]
    commits, commit_count = "", None
    if with_plugin:
        commits = git(home, "log", "--format=%h %s | %(trailers:key=Change,valueonly,separator=%x2C )").stdout
        commit_count = max(0, len(commits.strip().splitlines()) - 1)
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return {"scenario": scenario["id"], "arm": arm, "seeded": seeded, "graded": graded, "sessions": sessions,
            "trail_in_files": all(item in files for item in trail),
            "trail_in_files_or_history": all(item in files or item in history for item in trail),
            "memory_files": memory, "commits": commits, "commit_count": commit_count, "root": str(root) if keep else None}


def correctness_table(results):
    table = {}
    for result in results:
        for item in result["graded"]:
            cell = table.setdefault(result["arm"], {}).setdefault(item["kind"], [0, 0])
            cell[0] += item["pass"]
            cell[1] += 1
    kinds = sorted({kind for arm in table.values() for kind in arm})
    lines = ["| arm | " + " | ".join(kinds) + " | all |", "|---|" + "---|" * (len(kinds) + 1)]
    for arm, cells in table.items():
        passed = sum(c[0] for c in cells.values())
        total = sum(c[1] for c in cells.values())
        row = [f"{cells[k][0]}/{cells[k][1]}" if k in cells else "-" for k in kinds]
        lines.append(f"| {arm} | " + " | ".join(row) + f" | {passed}/{total} |")
    return "\n".join(lines)


def cost_table(results):
    lines = ["| arm | phase | runs | seconds | model turns | output tokens | cost USD |", "|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        runs = [r for r in results if r["arm"] == arm]
        if not runs:
            continue
        for phase in PHASES:
            sessions = [r["sessions"][phase] for r in runs]
            total = lambda key: round(sum(s.get(key) or 0 for s in sessions), 3)
            lines.append(f"| {arm} | {phase} | {len(sessions)} | {total('seconds')} | {total('model_turns')} | {total('output_tokens')} | {total('cost_usd')} |")
    return "\n".join(lines)


def trail_table(results):
    lines = ["| arm | in note files | in note files or git history |", "|---|---|---|"]
    for arm in ARMS:
        runs = [r for r in results if r["arm"] == arm and "trail_in_files" in r]
        if runs:
            files = sum(r["trail_in_files"] for r in runs)
            either = sum(r["trail_in_files_or_history"] for r in runs)
            lines.append(f"| {arm} | {files}/{len(runs)} | {either}/{len(runs)} |")
    return "\n".join(lines)


def summarise(results):
    by_scenario = {}
    for result in results:
        by_scenario.setdefault(result["scenario"], {})[result["arm"]] = result
    comparable = [r for group in by_scenario.values() if all(x["seeded"] for x in group.values()) for r in group.values()]
    unseeded = sorted(f"{r['scenario']} ({r['arm']})" for r in results if not r["seeded"])
    commits = [r["commit_count"] for r in results if r["commit_count"] is not None]
    parts = [
        "## Correctness, all runs", correctness_table(results),
        "## Correctness, scenarios where every arm saved the taught fact", correctness_table(comparable) if comparable else "None.",
        "## Teach sessions that did not save the fact", ", ".join(unseeded) if unseeded else "None.",
        "## Trail: the old value and the evidence for the change are still in memory", trail_table(results),
        "## Cost per phase (totals)", cost_table(results),
    ]
    if commits:
        parts.append(f"## Memory commits (receipts-wiki, excluding setup)\n\n{sum(commits)} across {len(commits)} scenarios")
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", choices=(*ARMS, "both"), default="both")
    parser.add_argument("--scenario", action="append", help="scenario id; repeat to select several")
    parser.add_argument("--timeout", type=int, default=300, help="seconds per claude session")
    parser.add_argument("--keep", action="store_true", help="keep temporary directories for inspection")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scenarios = json.loads((HERE / "scenarios.json").read_text())["scenarios"]
    if args.scenario:
        scenarios = [s for s in scenarios if s["id"] in args.scenario]
    arms = ARMS if args.arm == "both" else (args.arm,)
    runs = len(scenarios) * len(arms) * len(PHASES)
    questions = sum(len(s["questions"]) for s in scenarios) * len(arms)
    print(f"{len(scenarios)} scenarios x {len(arms)} arms = {runs} claude sessions, {questions} graded answers", flush=True)
    if args.dry_run:
        for scenario in scenarios:
            print(f"- {scenario['id']}: " + ", ".join(q["kind"] for q in scenario["questions"]))
        return 0

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS / f"{stamp}.jsonl"
    results = []
    with out_path.open("w", encoding="utf-8") as handle:
        for scenario in scenarios:
            for arm in arms:
                result = run_scenario(scenario, arm, args.keep, args.timeout)
                results.append(result)
                handle.write(json.dumps(result) + "\n")
                handle.flush()
                passed = sum(item["pass"] for item in result["graded"])
                print(f"{scenario['id']:20s} {arm:14s} {passed}/{len(result['graded'])} seeded={result['seeded']}", flush=True)
    summary = summarise(results)
    (RESULTS / f"{stamp}-summary.md").write_text(f"# Update-correctness eval {stamp}\n\n{summary}\n", encoding="utf-8")
    print("\n" + summary)
    print(f"\nfull results: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
