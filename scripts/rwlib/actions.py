"""The action log (PLAN-log-first §3.10): what a turn DID, beside what it said.

`archive.py` keeps the conversation — user and assistant text, redacted, forever. It keeps no tool
calls, so the permanent record holds claims and not deeds, and the evidence of what actually happened
survives only in Claude Code's raw transcripts, on a rolling delete.

This records one line per action that changed something: when, which turn, which tool, what it touched,
how it ended. Not the output — that is where the volume is, and the raw transcript serves it while it
lasts. Measured on 214 real turns: 6.8 tool calls per turn, 5.4 of them mutating, about 480 bytes a turn.

Reads are deliberately not recorded. They are half of all calls and rarely explain an outcome, and the
files a session read are already tracked in its state for the staleness gate.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from . import archive, secrets

# Tools that change something. A read leaves no trace worth keeping.
MUTATING = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "KillShell"}
TARGET = 160
OUTCOME = 100


def _target(tool, tool_input):
    """What the action touched: a path for an edit, the command itself for a shell call."""
    if tool == "Bash":
        return " ".join(str(tool_input.get("command") or "").split())
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    return str(path)


def outcome(response):
    """How it ended, in a few words. Failure is the high-signal case, so it is never collapsed to 'ok'."""
    if isinstance(response, dict):
        if response.get("error") or response.get("is_error"):
            return "ERROR: " + " ".join(str(response.get("error") or response.get("stderr") or "failed").split())
        for key in ("exit_code", "exitCode", "returncode"):
            if key in response and response[key] not in (0, None, "0"):
                return f"ERROR: exit {response[key]}"
        stderr = " ".join(str(response.get("stderr") or "").split())
        if stderr:
            return "ok, stderr: " + stderr
    elif isinstance(response, str) and response.strip().lower().startswith("error"):
        return "ERROR: " + " ".join(response.split())
    return "ok"


def line(payload):
    """One log line for this tool call, or None when the tool changed nothing."""
    tool = str(payload.get("tool_name") or "")
    if tool not in MUTATING:
        return None
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = _target(tool, tool_input)
    # A command line is the likeliest place in the whole system for a secret: Bash was 756 of 1453
    # calls on this machine, and roughly one raw transcript in six carries something secret-shaped.
    # Redact first; if it still looks secret-bearing, keep the fact of the call and drop the text.
    target = secrets.redact(target)
    if secrets.find_secret(target):
        target = f"({tool} command withheld: it still reads as secret-bearing after redaction)"
    result = outcome(payload.get("tool_response"))
    turn = re.sub(r"[^A-Za-z0-9_.-]", "", str(payload.get("prompt_id") or ""))[:64] or "-"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return "\t".join((when, turn, tool, target[:TARGET], secrets.redact(result)[:OUTCOME]))


def append(home, session, payload):
    """Write this action to the session's log for the current month. Never raises into the hook."""
    row = line(payload)
    if not row:
        return None
    folder = Path(home) / "sessions" / f"{datetime.now(timezone.utc):%Y}" / f"{datetime.now(timezone.utc):%m}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{archive._safe(session)}.actions.tsv"
        new = not path.exists()
        with open(path, "a", encoding="utf-8") as handle:
            if new:
                handle.write("# when\tturn\ttool\ttarget\toutcome\n")
            handle.write(row + "\n")
    except OSError:
        return None
    return row


def between(home, session, turn):
    """Every action recorded for one turn, oldest first. Used to show a commit's deeds beside its words."""
    safe = archive._safe(session)
    rows = []
    for path in sorted((Path(home) / "sessions").glob(f"*/*/{safe}.actions.tsv")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            if raw.startswith("#") or not raw.strip():
                continue
            parts = raw.split("\t")
            if len(parts) == 5 and parts[1] == turn:
                rows.append(dict(zip(("when", "turn", "tool", "target", "outcome"), parts)))
    return rows
