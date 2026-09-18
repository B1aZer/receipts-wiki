"""The warm list: the notes this memory home has been working with lately.

An area index follows the working directory and lists everything in that area, old and current alike. This
lists what was actually read or written recently, across areas, so a session starts from the live work.
Warmth is use, not age: a rule written in July stays useful and a note nobody has opened in months is not
worth session context, whatever its date.

Nothing is stored or moved. The list is computed at session start from the read tracker and git, and a note
missing from it is exactly as reachable as before, through its index or `receipts-wiki find`.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import gitlog, indexer, state

DAYS = 30
LIMIT = 15
BUDGET_CHARS = 1800


def _edits(home, days):
    """Newest commit date per memory file within the window."""
    out = gitlog.git(home, "log", f"--since={days}.days", "--date=short", "--format=%ad", "--name-only", "--", "memory")
    newest, stamp = {}, None
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) == 10 and line[4] == "-":
            stamp = line
        elif stamp and line.endswith(".md"):
            newest.setdefault(line, stamp)
    return newest


def _ago(stamp, today):
    try:
        days = (today - date.fromisoformat(stamp)).days
    except ValueError:
        return stamp
    return "today" if days <= 0 else ("yesterday" if days == 1 else f"{days}d ago")


def recent(home, limit=LIMIT, days=DAYS, today=None):
    """[(stamp, item)] for active notes touched within the window, newest first.

    A note counts as touched when a session read it (the read tracker) or a commit changed it.
    Cursor notes are left out: the session-start context already lists them.
    """
    today = today or datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=days)).isoformat()
    edits = _edits(home, days)
    reads = {rel: stamp for rel, stamp in state.last_reads().items() if stamp >= cutoff}
    touched = {}
    for source in (edits, reads):
        for rel, stamp in source.items():
            if indexer.is_note(rel) and stamp > touched.get(rel, ""):
                touched[rel] = stamp
    items = {f"memory/{item['file']}": item for item in indexer.notes(home)}
    found = [(stamp, items[rel]) for rel, stamp in touched.items()
             if rel in items and items[rel]["status"] != "retired" and items[rel]["type"] != "cursor"]
    found.sort(key=lambda pair: (pair[0], pair[1]["name"].lower()), reverse=True)
    return found[:limit]


def block(home, limit=LIMIT, days=DAYS, budget=BUDGET_CHARS, today=None):
    """The session-start section, or "" when nothing was touched."""
    found = recent(home, limit=limit, days=days, today=today)
    if not found:
        return ""
    today = today or datetime.now(timezone.utc).date()
    lines = []
    used = 0
    for stamp, item in found:
        line = f"- [{item['name']}](memory/{item['file']}) ({_ago(stamp, today)}): {item['description'] or ''}".rstrip(": ")
        if used + len(line) > budget:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    return ("Worked on lately (read or changed in the last %d days; everything else is reached through the area "
            "index or `receipts-wiki find <words>`):\n" % days) + "\n".join(lines)
