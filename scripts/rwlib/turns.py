"""Recording at the end of each turn, and catch-up for turns whose end was missed.

A turn is one user message and the agent's whole response. The files a session writes during a turn
are noted in its log; at the end of the turn they become one commit, together with the index files
they affect. Nothing waits for a session to end: an interrupted turn is committed at the session's next
prompt, a log abandoned by a crashed session is committed by another session, and changes made without
hooks are committed as external.change.
"""
import os
import time
from pathlib import Path

from . import config, gitlog, indexer, state

IN_PROGRESS = "a merge, rebase, cherry-pick or revert is in progress in the memory repository; finish or abort it"
STALE_UNCOMMITTED_MINUTES = 30


def short_error(detail):
    text = " ".join(str(detail or "").split())
    return (text[:297] + "...") if len(text) > 300 else (text or "git commit failed without an error message")


def _note_failure(data, detail):
    previous = data.get("commit_failure") or {}
    data["commit_failure"] = {"since": previous.get("since") or state.now_iso(), "at": state.now_iso(),
                              "count": int(previous.get("count") or 0) + 1, "detail": short_error(detail)}


def stale_uncommitted(home, minutes=STALE_UNCOMMITTED_MINUTES):
    """Memory files changed on disk more than `minutes` ago and still not committed, excluding files that
    a session active within the last hour is still working on."""
    active = set()
    for data in state.all_sessions():
        if state.seconds_since(data.get("updated")) < config.STALE_JOURNAL_MINUTES * 60:
            active.update(data.get("pending") or {})
    stale = []
    for rel in gitlog.dirty_paths(home):
        if rel in active or indexer.is_generated(home, rel):
            continue
        try:
            age = time.time() - os.stat(Path(home) / rel).st_mtime
        except OSError:
            age = float("inf")
        if age > minutes * 60:
            stale.append(rel)
    return stale


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def changes_for(home, rels, event=None):
    """Net change of each path against HEAD. Generated index files are left to the index rebuild."""
    changes = []
    for rel in sorted(set(rels)):
        if indexer.is_generated_index(home, rel):
            continue
        new = _read(Path(home) / rel)
        old = gitlog.head_content(home, rel)
        if new == old:
            continue
        kind = event or gitlog.derive_event(rel, old, new)
        changes.append({"rel": rel, "event": kind, "old": old, "new": new})
    return changes


def claims(exclude=None):
    """Paths other sessions have written but not yet committed."""
    claimed = set()
    for data in state.all_sessions():
        if data.get("session") != exclude:
            claimed.update(data.get("pending") or {})
    return claimed


def record(home, changes, agent, session=None, turn=None, cwd=None, transcript=None, recovered=False, claimed=frozenset()):
    """Commit these changes and the index files they affect. Returns (committed, detail, index paths)."""
    rels = [change["rel"] for change in changes]
    note_rels = {rel for rel in rels if indexer.is_note(rel)}
    # A missing MEMORY.md is created too, so an agent can see an empty memory with one read.
    if note_rels or not (Path(home) / "memory" / "MEMORY.md").exists():
        indexer.build(home, include=gitlog.tracked(home) | note_rels)
    extra = [path for path in gitlog.dirty_paths(home)
             if indexer.is_generated(home, path) and path not in rels and path not in claimed]
    if not changes and not extra:
        return False, "no change", []
    message = gitlog.turn_message(changes, extra, agent, session, turn, cwd, transcript, recovered)
    committed, detail = gitlog.commit_paths(home, rels + extra, message)
    return committed, detail, extra


def flush_session(home, session, data, turn=None, cwd=None, transcript=None, recovered=False, skip_turn=None):
    """Commit what this session wrote and has not committed. Mutates data; the caller saves it.

    skip_turn leaves the writes of that turn pending: the turn is still running.
    """
    pending = data.get("pending") or {}
    selected = {rel: entry for rel, entry in pending.items() if not skip_turn or entry.get("turn") != skip_turn}
    if not selected or not gitlog.is_repo(home):
        return None
    if gitlog.operation_in_progress(home):
        _note_failure(data, IN_PROGRESS)
        return False, IN_PROGRESS
    entries = list(selected.values())
    turn = turn or ", ".join(sorted({str(e.get("turn")) for e in entries if e.get("turn")})) or None
    cwd = cwd or next((e.get("cwd") for e in entries if e.get("cwd")), None)
    transcript = transcript or next((e.get("transcript") for e in entries if e.get("transcript")), None)
    changes = changes_for(home, selected)
    claimed = claims(exclude=session) | (set(pending) - set(selected))
    committed, detail, extra = record(home, changes, "claude-code", session, turn, cwd, transcript, recovered, claimed)
    if committed or detail == "no change":
        data["pending"] = {rel: entry for rel, entry in pending.items() if rel not in selected}
        data.pop("commit_failure", None)
        for rel in extra:
            if rel in data["reads"]:
                data["reads"][rel] = state.content_hash(Path(home) / rel, rel)
    else:
        _note_failure(data, detail)
    return committed, detail


def sweep(home, current_session=None):
    """Commit logs abandoned by other sessions (credited to them) and changes made without hooks."""
    if not gitlog.is_repo(home):
        return
    if gitlog.operation_in_progress(home):
        dirty = gitlog.dirty_paths(home)
        if dirty:
            state.save_health(IN_PROGRESS, dirty)
        return
    for data in state.all_sessions():
        session = data.get("session")
        if session == current_session:
            continue
        idle = state.seconds_since(data.get("updated"))
        if data.get("pending") and idle > config.STALE_JOURNAL_MINUTES * 60:
            flush_session(home, session, data, recovered=True)
            state.save(session, data)
        elif not data.get("pending") and idle > config.JOURNAL_RETENTION_DAYS * 86400:
            state.remove(session)
    claimed = claims()
    external = [path for path in gitlog.dirty_paths(home) if path not in claimed and not indexer.is_generated_index(home, path)]
    changes = changes_for(home, external, event="external.change")
    if changes:
        committed, detail, _ = record(home, changes, "unknown", claimed=claimed)
        if committed or detail == "no change":
            state.clear_health()
        else:
            state.save_health(short_error(detail), [change["rel"] for change in changes])
    elif not gitlog.dirty_paths(home):
        state.clear_health()
