#!/usr/bin/env python3
"""Drift eval: does memory stay findable and current when work moves across sessions and directories?

Built from failures seen in a live memory home (see scenarios.json). Same two arms and session runner as
the update-correctness eval (baseline = Claude Code auto memory; receipts-wiki = the same plus this
plugin from the working tree). Per scenario and arm:

  1. seed the memory directory (optional), committed as setup for receipts-wiki
  2. run each step as its own `claude -p` session in work/<cwd>
  3. check the memory files (deterministic, see CHECKS)
  4. ask the questions from work/elsewhere, graded by fixed strings

Checks read note files only (not MEMORY.md or index-*.md), except `listed`, which reads the indexes.

Usage:
    python3 evals/drift/run.py --dry-run
    python3 evals/drift/run.py --arm both [--scenario cursor-follow] [--repeat 2] [--keep]
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
_spec = importlib.util.spec_from_file_location("update_correctness_run", HERE.parent / "update_correctness" / "run.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

RESULTS = HERE / "results"
# A stale phrase may stay on a line that marks it as history.
HISTORY_WORDS = ("supersede", "previous", "was ", "were ", "earlier", "before", "old ", "formerly", "until", "moved from", "changed from")
FILLER_TOPICS = ["dns ttl", "log retention", "backup window", "cdn cache", "queue depth alert", "tls renewal", "pager rota",
                 "disk quota", "cron drift", "vpn split tunnel", "image registry", "secrets rotation", "load balancer idle timeout",
                 "database vacuum", "metrics cardinality", "feature flag cleanup", "canary share", "rate limit", "sso session length",
                 "artifact retention"]


def filler(count):
    notes, lines = {}, []
    for i in range(count):
        topic = FILLER_TOPICS[i % len(FILLER_TOPICS)]
        name = f"ops-{topic.replace(' ', '-')}-{i}"
        value = 10 + i * 7
        notes[f"project_{name.replace('-', '_')}.md"] = (
            f"---\nname: {name}\ndescription: {topic} setting is {value} for service {i}\nmetadata:\n  type: project\n  area: ops\n---\n\n"
            f"The {topic} setting for service {i} is {value}, set 2026-08-{1 + i % 28:02d}.\n")
        lines.append(f"- [{name}](project_{name.replace('-', '_')}.md): {topic} setting is {value} for service {i}\n")
    return notes, "".join(lines)


def seed(home, spec):
    memory = home / "memory"
    files = dict(spec or {})
    count = files.pop("{filler}", 0)
    extra, index_lines = filler(count)
    files.update(extra)
    for name, text in files.items():
        (memory / name).write_text(text.replace("{filler_index}", index_lines), encoding="utf-8")


def notes(home):
    return {p.name: p.read_text(encoding="utf-8", errors="replace").lower() for p in sorted((home / "memory").glob("*.md"))
            if p.name != "MEMORY.md" and not p.name.startswith("index-")}


def indexes(home):
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted((home / "memory").glob("*.md"))
                     if p.name == "MEMORY.md" or p.name.startswith("index-"))


def check(home, spec):
    found = notes(home)
    kind = spec["kind"]
    if kind in ("mentioned", "one_note", "listed"):
        text = spec["text"].lower()
        holders = [name for name, body in found.items() if text in body]
        if kind == "mentioned":
            return bool(holders), f"{len(holders)} note(s)"
        if kind == "one_note":
            return len(holders) == 1, ", ".join(holders) or "none"
        listed = indexes(home)
        missing = [name for name in holders if not re.search(r"\((?:\./)?" + re.escape(name) + r"[)#]", listed)]
        return bool(holders) and not missing, "unlisted: " + (", ".join(missing) or "none")
    if kind == "stale_absent":
        hits = []
        for name, body in found.items():
            for line in body.splitlines():
                if any(t.lower() in line for t in spec["texts"]) and not any(w in line for w in HISTORY_WORDS):
                    hits.append(f"{name}: {line.strip()[:120]}")
        return not hits, "; ".join(hits) or "none"
    raise ValueError(f"unknown check {kind}")


def run_scenario(scenario, arm, keep, timeout):
    root, home, work, settings, env = base.prepare(arm)
    with_plugin = arm == "receipts-wiki"
    if scenario.get("seed"):
        seed(home, scenario["seed"])
        if with_plugin:
            subprocess.run(["python3", str(base.PLUGIN_ROOT / "scripts" / "rw.py"), "record", "--agent", "eval-seed"],
                           env=env, capture_output=True, text=True, check=True)
    sessions = []
    for step in scenario["steps"]:
        cwd = work / step["cwd"]
        cwd.mkdir(exist_ok=True)
        sessions.append(base.claude(cwd, step["prompt"], settings, with_plugin, env, timeout))
    checks = []
    for spec in scenario.get("checks", []):
        ok, detail = check(home, spec)
        checks.append({**spec, "pass": ok, "detail": detail})
    questions = scenario["questions"]
    elsewhere = work / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    prompt = base.ASK.format(count=len(questions), questions="\n".join(f"{i}. {q['q']}" for i, q in enumerate(questions, 1)))
    ask = base.claude(elsewhere, prompt, settings, with_plugin, env, timeout)
    answers = base.split_answers(ask["output"], len(questions))
    graded = [{"kind": q["kind"], "question": q["q"], "answer": a, "pass": base.grade(a, q)} for q, a in zip(questions, answers)]
    memory = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted((home / "memory").glob("*.md"))
              if not p.name.startswith("project_ops_")}
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return {"scenario": scenario["id"], "arm": arm, "checks": checks, "graded": graded, "steps": sessions, "ask": ask,
            "memory_files": memory, "root": str(root) if keep else None}


def summarise(results):
    lines = ["| scenario | arm | runs | file checks | answers | cost USD |", "|---|---|---|---|---|---|"]
    groups = {}
    for r in results:
        groups.setdefault((r["scenario"], r["arm"]), []).append(r)
    totals = {}
    for (scenario, arm), runs in groups.items():
        c_pass = sum(c["pass"] for r in runs for c in r["checks"])
        c_all = sum(len(r["checks"]) for r in runs)
        a_pass = sum(g["pass"] for r in runs for g in r["graded"])
        a_all = sum(len(r["graded"]) for r in runs)
        cost = sum((s.get("cost_usd") or 0) for r in runs for s in [*r["steps"], r["ask"]])
        t = totals.setdefault(arm, [0, 0, 0, 0, 0.0])
        for i, v in enumerate((c_pass, c_all, a_pass, a_all, cost)):
            t[i] += v
        lines.append(f"| {scenario} | {arm} | {len(runs)} | {c_pass}/{c_all} | {a_pass}/{a_all} | {cost:.2f} |")
    for arm, t in totals.items():
        lines.append(f"| **all** | {arm} | | {t[0]}/{t[1]} | {t[2]}/{t[3]} | {t[4]:.2f} |")
    failures = [f"- {r['scenario']} / {r['arm']}: {c['kind']} failed ({c['detail']})" for r in results for c in r["checks"] if not c["pass"]]
    failures += [f"- {r['scenario']} / {r['arm']}: answer to \"{g['question']}\" was \"{g['answer']}\"" for r in results for g in r["graded"] if not g["pass"]]
    return "\n".join(lines) + "\n\n## Failures\n\n" + ("\n".join(failures) or "None.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", choices=(*base.ARMS, "both"), default="both")
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scenarios = json.loads((HERE / "scenarios.json").read_text())["scenarios"]
    if args.scenario:
        scenarios = [s for s in scenarios if s["id"] in args.scenario]
    arms = base.ARMS if args.arm == "both" else (args.arm,)
    sessions = sum(len(s["steps"]) + 1 for s in scenarios) * len(arms) * args.repeat
    print(f"{len(scenarios)} scenarios x {len(arms)} arms x {args.repeat} = {sessions} claude sessions", flush=True)
    if args.dry_run:
        for s in scenarios:
            print(f"- {s['id']}: {len(s['steps'])} steps, {len(s['questions'])} questions, checks: "
                  + (", ".join(c["kind"] for c in s.get("checks", [])) or "none"))
        return 0

    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"{stamp}.jsonl"
    results = []
    with out.open("w", encoding="utf-8") as handle:
        for _ in range(args.repeat):
            for scenario in scenarios:
                for arm in arms:
                    result = run_scenario(scenario, arm, args.keep, args.timeout)
                    results.append(result)
                    handle.write(json.dumps(result) + "\n")
                    handle.flush()
                    print(f"{scenario['id']:20s} {arm:14s} checks {sum(c['pass'] for c in result['checks'])}/{len(result['checks'])}"
                          f" answers {sum(g['pass'] for g in result['graded'])}/{len(result['graded'])}", flush=True)
    summary = summarise(results)
    (RESULTS / f"{stamp}-summary.md").write_text(f"# Drift eval {stamp}\n\n{summary}\n", encoding="utf-8")
    print("\n" + summary + f"\n\nfull results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
