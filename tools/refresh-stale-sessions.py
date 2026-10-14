#!/usr/bin/env python3
"""Find Claude Code sessions still running a superseded plugin install, and refresh them.

THE BUG CLASS THIS EXISTS FOR, which is not specific to this plugin:

A plugin's root is resolved ONCE PER PROCESS, from <claude-home>/plugins/installed_plugins.json.
The hook SCRIPT is re-read at every invocation -- each hook call is a fresh interpreter -- but a
stale PATH re-read per invocation still yields stale CODE. Installs land at
<cache>/<marketplace>/<plugin>/<version>/, so each install is a SEPARATE DIRECTORY that keeps
existing after a newer one appears.

The consequence: `plugin update` is global and immediate, and it DOES NOT REACH ALREADY-RUNNING
SESSIONS. They keep executing the old directory until they restart. Nothing in their output says
so, which makes it silent -- and a staleness check written against the version-named layout goes
dead the moment the execution root moves somewhere that is not version-named, because it can no
longer recognise its own siblings.

Anyone with a plugin and long-lived sessions has this. A security or privacy fix is the worst case:
it ships, it is verified against the installed files, and it is not in effect where it matters.

WHAT THIS TOOL ASSERTS, AND WHAT IT REFUSES TO ASSERT

It compares each session's startedAt against the install's lastUpdated to find the affected set,
and it identifies a build by gitCommitSha, never by version string -- a version can be set by an
earlier commit and not bumped by the one that matters, in which case the leaky and fixed builds
report the same version and "running vX" is not a receipt.

After a refresh it verifies from the session's OWN new output, and it distinguishes three outcomes:
a clean pass needs the plugin's context to have actually RENDERED SOMETHING. "No defect found" in
output that never exercised the code path is reported as UNPROVEN, not as success.

It reads structure, timestamps and counts. It never prints transcript content: the incident that
motivated it was a tool quoting a user's own turns into other sessions, and a remediation tool
with the same failure mode would be worse than the bug.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_CLAUDE_HOME = Path.home() / ".claude"

# Defaults describe receipts-wiki's own context block. Override for another plugin; a probe that
# matches nothing is reported as such rather than counted as a pass.
# One entry PER CODE PATH, each with its own liveness. A probe may only license a conclusion about
# the path its own liveness proves ran: the first version of this tool checked site-A liveness and
# then reported on site B, and scored two provably-stale sessions CLEAN because the path the probe
# covered had never fired. Proving *a* path ran says nothing about *another*.
SITES = [
    {"name": "cursor-pointer",   # hooks.py::_cursor_pointers, SessionStart
     "liveness": r"\[moved [^\]]{0,200}\]",
     "probe":    r"\[moved [^\]]{0,200}?: \"",
     "marker":   None},
    {"name": "per-prompt-notice",  # watch.render via watch.notice, UserPromptSubmit
     "liveness": r"Memory changed elsewhere while you worked",
     "probe":    r"by another session[^\n\"]{0,40}: \"",
     "marker":   "Memory changed elsewhere while you worked"},
]
DEFAULT_LIVENESS = r"\[moved [^\]]{0,200}\]|changed \d+ \w+ ago by (?:another session|outside)"
DEFAULT_PROBE = r"\[moved [^\]]{0,200}?: \"|by another session[^\n\"]{0,40}: \""
# A POSITIVE tell for the old build, independent of whether it had anything to quote. Without one,
# a stale session that simply had no reason to quote renders a block with no quote tail and is
# indistinguishable from a fixed one -- an absence-based CLEAN. Measured: 2 of 15 known-stale
# sessions were reported CLEAN before this existed, which is the one wrong answer that matters,
# because a false clean ends the remediation while the leak is live.
DEFAULT_OLD_TELL = r"\(no reason recorded\)"


class Problem(Exception):
    pass


def run(argv, timeout=120):
    """Run a command, returning (exit_code, stdout). Never raises on a non-zero exit."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        raise Problem(f"not found on PATH: {argv[0]}")
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"


def install_record(home, plugin):
    """The install this plugin resolves to right now: path, commit and when it last changed."""
    path = home / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Problem(f"cannot read {path}: {exc}")
    plugins = data.get("plugins") or {}
    if plugin is None:
        if len(plugins) != 1:
            raise Problem("--plugin is required; installed: " + ", ".join(sorted(plugins)) or "none")
        plugin = next(iter(plugins))
    entries = plugins.get(plugin)
    if not entries:
        raise Problem(f"{plugin!r} is not installed; installed: " + ", ".join(sorted(plugins)))
    # Several scopes can be recorded; the most recently updated is the one a new process picks.
    entry = max(entries, key=lambda e: e.get("lastUpdated") or "")
    return plugin, entry


def iso_to_epoch(text):
    if not text:
        return None
    try:
        from datetime import datetime, timezone
        clean = text.replace("Z", "+00:00")
        return datetime.fromisoformat(clean).replace(tzinfo=timezone.utc).timestamp() \
            if "+" not in clean else datetime.fromisoformat(clean).timestamp()
    except ValueError:
        return None


def sessions():
    """Live sessions as Claude Code reports them. Read-only."""
    code, out, err = run(["claude", "agents", "--json"])
    if code != 0:
        raise Problem(f"`claude agents --json` failed ({code}): {err.strip()[:200]}")
    try:
        return json.loads(out)
    except ValueError:
        raise Problem("`claude agents --json` did not return JSON")


def transcript(projects_dir, session_id):
    hits = sorted(projects_dir.glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


def snapshot(path):
    """Enough to tell later which records are new. Counts lines; reads no content."""
    if path is None or not path.exists():
        return {"lines": 0, "exists": False}
    with path.open(errors="replace") as fh:
        return {"lines": sum(1 for _ in fh), "exists": True}


def _strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, out)


def inspect_new(path, since_lines, liveness, probe, since_ts=None,
                delivered=("attachment", "system"), block_marker=None, old_tell=None,
                exclude=("cross-session-message", "toolUseResult", "tool_use")):
    """Count liveness and probe hits in records after `since_lines` and/or after `since_ts`.

    `since_ts` is what makes a read-only verdict possible: without it, a transcript that leaked
    BEFORE the install reads exactly like one leaking now, and every long-lived session would be
    reported as still broken. The timestamp bound is the difference between "is it emitting" and
    "has it ever emitted".

    Returns counts only. The matched text is never returned, stored or printed -- callers must not
    be able to leak it even by accident.
    """
    live_rx, probe_rx = re.compile(liveness), re.compile(probe)
    old_rx = re.compile(old_tell) if old_tell else None
    n_records = n_live = n_probe = n_echo = n_ambig = n_old = 0
    if path is None or not path.exists():
        return {"records": 0, "liveness": 0, "probe": 0, "echo": 0, "ambiguous": 0, "old": 0}
    with path.open(errors="replace") as fh:
        for i, line in enumerate(fh):
            if i < since_lines:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if since_ts and (obj.get("timestamp") or "") < since_ts:
                continue
            n_records += 1
            buf = []
            _strings(obj, buf)
            text = "\n".join(buf)
            hits = len(probe_rx.findall(text))
            # Attribution, in three layers, because each one alone gives a wrong answer:
            #  - record type: only DELIVERED context counts, never the session's own turns. A
            #    session that investigated this defect quotes the pattern itself.
            #  - exclusions: a peer's message arrives as delivered context too, so a coordinator
            #    being TOLD about the leak scored 17 "hits" before this filter existed.
            #  - block marker: the match must sit inside the plugin's own rendered block.
            # Measured on the first run of this tool: without these, 3 sessions that merely
            # discussed the problem were reported as victims of it.
            own_text = (obj.get("type") or "") not in delivered
            foreign = any(tok in text for tok in exclude)
            in_block = (block_marker in text) if block_marker else True
            if hits and (own_text or foreign):
                n_echo += hits
            elif hits and not in_block:
                n_ambig += hits
            else:
                n_probe += hits
                if not (own_text or foreign):
                    n_live += len(live_rx.findall(text))
            if old_rx and not (own_text or foreign) and in_block:
                n_old += len(old_rx.findall(text))
    return {"records": n_records, "liveness": n_live, "probe": n_probe,
            "echo": n_echo, "ambiguous": n_ambig, "old": n_old}


def inspect_sites(path, since_lines, sites, since_ts=None, old_tell=None,
                  delivered=("attachment", "system"),
                  exclude=("cross-session-message", "toolUseResult", "tool_use")):
    """Per-code-path counts. Returns counts only; matched text is never returned or printed."""
    out = {s["name"]: {"liveness": 0, "probe": 0, "echo": 0} for s in sites}
    out["_old"] = 0
    out["_records"] = 0
    if path is None or not path.exists():
        return out
    rx = [(s, re.compile(s["liveness"]), re.compile(s["probe"])) for s in sites]
    old_rx = re.compile(old_tell) if old_tell else None
    with path.open(errors="replace") as fh:
        for i, line in enumerate(fh):
            if i < since_lines:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if since_ts and (obj.get("timestamp") or "") < since_ts:
                continue
            out["_records"] += 1
            buf = []
            _strings(obj, buf)
            text = "\n".join(buf)
            own = (obj.get("type") or "") not in delivered
            foreign = any(tok in text for tok in exclude)
            for s, live_rx, probe_rx in rx:
                hits = len(probe_rx.findall(text))
                if own or foreign:
                    out[s["name"]]["echo"] += hits
                    continue
                if s["marker"] and s["marker"] not in text:
                    continue
                out[s["name"]]["probe"] += hits
                out[s["name"]]["liveness"] += len(live_rx.findall(text))
            if old_rx and not (own or foreign):
                out["_old"] += len(old_rx.findall(text))
    return out


def classify_sites(out, sites):
    """Worst verdict across paths. CLEAN requires EVERY path's own liveness to have fired."""
    leaking = [s["name"] for s in sites if out[s["name"]]["probe"] > 0]
    if leaking:
        n = sum(out[s]["probe"] for s in leaking)
        return "LEAK", f"{n} hit(s) on {', '.join(leaking)}: still on the old build"
    if out["_old"]:
        return "STALE", f"old-build tell x{out['_old']} (nothing to quote, but not the fixed code)"
    silent = [s["name"] for s in sites if out[s["name"]]["liveness"] == 0]
    if silent:
        ran = [s["name"] for s in sites if out[s["name"]]["liveness"] > 0]
        detail = f"ran: {', '.join(ran)}; " if ran else ""
        return "UNPROVEN", f"{detail}never ran: {', '.join(silent)} -- cannot tell fixed from untested"
    return "CLEAN", "every path rendered, 0 hits in any"


def classify(counts):
    """CLEAN requires the code path to have RUN. A quiet probe over a dead subject proves nothing."""
    tail = ""
    if counts.get("echo"):
        tail += f"; {counts['echo']} echo(es) in own/peer text, not counted"
    if counts.get("ambiguous"):
        tail += f"; {counts['ambiguous']} unattributable"
    if counts["probe"] > 0:
        return "LEAK", f"{counts['probe']} hit(s) in the plugin's own block: still on the old build{tail}"
    if counts.get("old"):
        # Old build, but it had nothing to quote this time. Still unremediated.
        return "STALE", f"old-build tell x{counts['old']} (nothing to quote, but not the fixed code){tail}"
    if counts.get("ambiguous"):
        # Never resolve an unattributable hit to CLEAN. A false clean ends the remediation early.
        return "AMBIGUOUS", f"hits present but not attributable to the plugin's block{tail}"
    if counts["liveness"] == 0:
        return "UNPROVEN", f"nothing rendered -- cannot tell fixed from untested{tail}"
    return "CLEAN", f"{counts['liveness']} line(s) rendered, 0 hits in the plugin's block{tail}"


def plan(args):
    home = Path(args.claude_home).expanduser()
    projects = Path(args.projects_dir).expanduser() if args.projects_dir else home / "projects"
    name, entry = install_record(home, args.plugin)
    commit, updated = entry.get("gitCommitSha"), entry.get("lastUpdated")
    cutoff = iso_to_epoch(updated)

    print(f"plugin        {name}")
    print(f"installPath   {entry.get('installPath')}")
    print(f"gitCommitSha  {commit or '(none recorded)'}")
    print(f"lastUpdated   {updated or '(none recorded)'}")
    if args.expect_commit:
        ok = (commit or "").startswith(args.expect_commit)
        print(f"expected      {args.expect_commit}  -> {'MATCH' if ok else 'MISMATCH'}")
        if not ok:
            raise Problem("installed gitCommitSha does not match --expect-commit; refusing to plan")
    if cutoff is None:
        raise Problem("the install record has no usable lastUpdated; cannot compute the affected set")
    print()

    args.since_ts = updated or ""
    rows = sessions()
    stale, fresh = [], []
    for r in rows:
        started = (r.get("startedAt") or 0) / 1000.0
        (stale if started < cutoff else fresh).append(r)
    stale.sort(key=lambda r: r.get("startedAt") or 0)

    print(f"{len(rows)} live session(s): {len(stale)} started before the install, {len(fresh)} after")
    print()
    if not stale:
        print("Nothing to do: every live session started after the current install.")
        return [], projects

    kinds = {r.get("kind") for r in stale}
    print(f"{'started':<17} {'name':<22} {'id':<10} {'kind':<12} {'state':<6} cwd")
    for r in stale:
        started = time.strftime("%Y-%m-%d %H:%M", time.localtime((r.get("startedAt") or 0) / 1000))
        print(f"{started:<17} {(r.get('name') or '?'):<22} {(r.get('sessionId') or '?')[:8]:<10} "
              f"{(r.get('kind') or '?'):<12} {(r.get('status') or '?'):<6} {r.get('cwd') or ''}")
    print()
    if kinds - {"background"}:
        n = len([r for r in stale if r.get("kind") != "background"])
        print(f"!! {n} of these are not `background` sessions, and the two obvious verbs are documented")
        print("   for background sessions only -- `claude stop --help`: \"Stop a background session\";")
        print("   `claude attach --help`: \"Open the background session in this terminal\". This tool has")
        print("   NOT verified either against an interactive session, so --apply may fail on them.")
        print("   The route that is known to work is: END each session in its own terminal, then run")
        print("   `claude --resume <id>` there. --emit-vscode-task builds that as one action.")
        print()
    return stale, projects


def vscode_task(stale, label="Refresh stale Claude sessions"):
    """A compound task that reopens every affected session, each in its own terminal.

    Two details are load-bearing. `dependsOrder: parallel` is the default for `dependsOn`, but
    `presentation.panel` defaults to SHARED -- so without an explicit per-task `dedicated`, all the
    sub-tasks pile into one terminal and the point is lost. And each sub-task sets its own `cwd`,
    because a session resumed in the wrong directory gets the wrong project context.
    """
    tasks = []
    for r in stale:
        sid, nm = r.get("sessionId"), r.get("name") or (r.get("sessionId") or "?")[:8]
        tasks.append({
            "label": f"resume: {nm}",
            "type": "shell",
            "command": "claude",
            "args": ["--resume", sid],
            "options": {"cwd": r.get("cwd") or "${workspaceFolder}"},
            # dedicated, not shared: one terminal per session, reused if the task runs again.
            "presentation": {"panel": "dedicated", "group": "claude-refresh",
                             "reveal": "always", "focus": False, "echo": True},
            "problemMatcher": [],
        })
    tasks.append({
        "label": label,
        "dependsOn": [t["label"] for t in tasks],
        "dependsOrder": "parallel",
        "problemMatcher": [],
    })
    return {"version": "2.0.0", "tasks": tasks}


def verify_only(args, stale, projects):
    """Read-only: does each session's EXISTING output show the defect, and did the path run at all?

    Scans each transcript from the install moment onward, so it answers "is this session still
    emitting" without stopping, resuming or writing anything. UNPROVEN is a real answer here and the
    common one: a session that has not been prompted since the install has rendered nothing to judge.
    """
    print("--verify-only: reading existing output; nothing is stopped or resumed.\n")
    worst = 0
    for r in stale:
        sid, nm = r.get("sessionId"), r.get("name") or "?"
        path = transcript(projects, sid)
        if path is None:
            print(f"  {'NO_TRANSCRIPT':<12} {nm:<22} nothing to read")
            continue
        out = inspect_sites(path, 0, SITES, since_ts=args.since_ts, old_tell=args.old_tell)
        status, why = classify_sites(out, SITES)
        print(f"  {status:<12} {nm:<22} {why}")
        worst = max(worst, {"CLEAN": 0, "UNPROVEN": 1, "AMBIGUOUS": 2, "STALE": 3, "LEAK": 3}.get(status, 1))
    print("\nLEAK means that session is still on the old build. UNPROVEN means the code path did not")
    print("run in what was read -- not that it is fixed.")
    return worst


def apply(args, stale, projects):
    todo = stale if args.max <= 0 else stale[: args.max]
    print(f"--apply: {len(todo)} session(s) this run (of {len(stale)}); one at a time.\n")
    results = []
    for r in todo:
        sid, nm = r.get("sessionId"), r.get("name") or "?"
        path = transcript(projects, sid)
        before = snapshot(path)
        print(f"=== {nm} ({sid[:8]}) ===")
        if not before["exists"]:
            print("  no transcript found; skipping (cannot verify what cannot be read)")
            results.append((nm, "SKIPPED", "no transcript"))
            continue
        if args.confirm and input(f"  stop and resume {nm}? [y/N] ").strip().lower() != "y":
            results.append((nm, "SKIPPED", "declined"))
            continue

        code, _, err = run(["claude", "stop", sid])
        print(f"  stop  -> exit {code}" + (f"  {err.strip()[:120]}" if err.strip() else ""))
        if code != 0:
            results.append((nm, "STOP_FAILED", err.strip()[:120]))
            if args.stop_on_error:
                print("  aborting (--stop-on-error)")
                break
            continue

        code, _, err = run(["claude", "--resume", sid, "-p", args.resume_prompt], timeout=args.timeout)
        print(f"  resume-> exit {code}" + (f"  {err.strip()[:120]}" if err.strip() else ""))

        out = inspect_sites(path, before["lines"], SITES, old_tell=args.old_tell)
        status, why = classify_sites(out, SITES)
        print(f"  verify-> {status}: {why}  (new records: {out['_records']})")
        results.append((nm, status, why))
        if status == "LEAK" and args.stop_on_error:
            print("  aborting (--stop-on-error): a refreshed session is still on the old build")
            break

    print("\nsummary")
    for nm, status, why in results:
        print(f"  {status:<12} {nm:<22} {why}")
    bad = [r for r in results if r[1] not in ("CLEAN",)]
    return 1 if bad else 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Refresh Claude Code sessions still bound to a superseded plugin install.",
        epilog="Default is --dry-run: it reads, prints and changes nothing.")
    p.add_argument("--plugin", help="plugin key as installed_plugins.json spells it, e.g. name@marketplace")
    p.add_argument("--claude-home", default=str(DEFAULT_CLAUDE_HOME), help="default: ~/.claude")
    p.add_argument("--projects-dir", help="default: <claude-home>/projects")
    p.add_argument("--expect-commit", help="refuse to run unless the install's gitCommitSha starts with this")
    p.add_argument("--dry-run", action="store_true", default=True, help="the default; enumerate only")
    p.add_argument("--apply", action="store_true", help="actually stop and resume (operator only)")
    p.add_argument("--emit-commands", action="store_true", help="print the commands instead of running them")
    p.add_argument("--emit-vscode-task", metavar="PATH",
                   help="write a VS Code tasks.json opening one terminal per affected session ('-' for stdout)")
    p.add_argument("--verify-only", action="store_true",
                   help="check the CURRENT sessions' startup output for the defect; stops and resumes nothing")
    p.add_argument("--max", type=int, default=1, help="how many to refresh per run; 0 for all (default 1)")
    p.add_argument("--no-confirm", dest="confirm", action="store_false", help="do not ask per session")
    p.add_argument("--keep-going", dest="stop_on_error", action="store_false",
                   help="continue after a failure instead of aborting")
    p.add_argument("--timeout", type=int, default=600, help="seconds to allow a resume (default 600)")
    p.add_argument("--resume-prompt", default="reply with the single word: ok",
                   help="inert prompt used to make the resumed session run its startup hooks")
    p.add_argument("--liveness", default=DEFAULT_LIVENESS, help="regex proving the plugin rendered something")
    p.add_argument("--probe", default=DEFAULT_PROBE, help="regex matching the defect being remediated")
    p.add_argument("--old-tell", default=DEFAULT_OLD_TELL,
                   help="regex present ONLY in the old build; proves staleness even when the defect "
                        "had nothing to emit. Set empty to disable.")
    p.add_argument("--block-marker", default="Memory changed elsewhere while you worked",
                   help="literal text the plugin's own rendered block contains; a probe hit outside "
                        "it is reported AMBIGUOUS rather than counted or dismissed")
    args = p.parse_args(argv)

    try:
        stale, projects = plan(args)
        if not stale:
            return 0
        if args.verify_only:
            return verify_only(args, stale, projects)
        if args.emit_vscode_task:
            doc = vscode_task(stale)
            text = json.dumps(doc, indent=2) + "\n"
            if args.emit_vscode_task != "-":
                out = Path(args.emit_vscode_task).expanduser()
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                print(f"wrote {out}  ({len(stale)} terminal(s) + 1 compound task)")
            else:
                print(text, end="")
            print()
            print("BEFORE running the task, end the sessions it will reopen. Their processes still")
            print("hold those terminals, and two processes on one conversation is the thing to avoid:")
            print("  1. in each listed terminal, exit the running session (its own quit command)")
            print("  2. then: Terminal > Run Task... > 'Refresh stale Claude sessions'")
            print("  3. then re-run this tool with --verify-only to confirm each one came up clean")
            return 0
        if args.emit_commands:
            print("# review, then run. One session at a time; verify before continuing.")
            for r in stale:
                print(f"# {r.get('name')}  (cwd {r.get('cwd')})")
                print(f"claude --resume {r.get('sessionId')}")
            return 0
        if args.apply:
            return apply(args, stale, projects)
        print("Dry run: nothing was stopped or resumed.")
        print("  --emit-commands  print the commands for review")
        print("  --apply          perform it (one session per run unless --max says otherwise)")
        return 0
    except Problem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
