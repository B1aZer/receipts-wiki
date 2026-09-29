"""Cross-session visibility (PLAN-log-first §3.5): tell a session when another one changed memory it relies on.

A session reads memory at start and is never told when a parallel session changes a note it is working from.
The write gate refuses to overwrite a note changed since it was read, but nothing flags *reading* a stale one.

So each session keeps an offset -- the last commit it has been shown -- and on every prompt the commits made
since then by other sessions are filtered to this session's focus and rendered as at most five lines. Silent
when nothing relevant changed, which is the normal case.

Focus starts deliberately narrow (the plan's own risk note: widen only on evidence):
  - notes this session has read or written
  - the cursor notes, which every session is shown at start
  - one hop: a changed note that links to something in the first two
Generated views (MEMORY.md, area indexes) are left out; they change because a note changed, and that note
shows up on its own.
"""
import re
from datetime import datetime, timezone

from . import changes, config, gitlog, indexer, state

LINK = re.compile(r"\[\[([^\]\n]+)\]\]")
MAX_LINES = 5
MAX_COMMITS = 60
QUOTE = 90

# A note this session actually read outranks a cursor it was merely shown at start, which outranks a
# note reached by one hop. The tier decides both the order and what the line says about why it is here.
TIERS = {"read": 0, "cursor": 1, "hop": 2}
MARKS = {0: "", 1: " (a cursor you were shown at start)", 2: " (linked to notes you read)"}


def head(home):
    """HEAD, or None when there is no repo or no commit yet.

    One git call, not three: this runs on every prompt and returns nothing to say almost every time,
    so the quiet path is the one that has to stay cheap. A missing repo and an unborn HEAD both fail
    this call, which is the only thing the caller needs to know.
    """
    result = gitlog.git(home, "rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _ago(when):
    if not when:
        return "?"
    seconds = (datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)} min ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


def _links(home, rel):
    text = gitlog.head_content(home, rel)
    return {gitlog.slug(name) for name in LINK.findall(text or "")}


def focus(home, data):
    """What this session relies on: (rels followed directly, names used as one-hop anchors).

    One hop runs only from notes the session actually READ. Cursors are followed for direct hits but are
    never hop anchors: they are the most heavily linked notes in a home, so hopping from them matches most
    of memory and the notice degenerates into noise. Measured 2026-09-29 on this home -- hopping from
    cursors filled four of the five lines from a single unrelated commit.
    """
    read = {rel for rel in (data.get("reads") or {})
            if indexer.is_note(rel) and not indexer.is_index_file(rel)}
    try:
        items = indexer.notes(home)
    except OSError:
        items = []
    by_rel = {f"memory/{item['file']}": item for item in items}
    cursors = {f"memory/{item['file']}" for item in items
               if item["type"] == "cursor" and item["status"] != "retired"}

    def name_of(rel):
        item = by_rel.get(rel)
        return gitlog.slug(item["name"] if item else rel.rsplit("/", 1)[-1][:-3])

    return read, cursors - read, {name_of(rel) for rel in read}


def _label(rel, by_rel):
    item = by_rel.get(rel)
    return item["name"] if item else rel.rsplit("/", 1)[-1][:-3]


def pending(home, session, data):
    """Rows for commits this session has not been shown, made by someone else, touching its focus."""
    since = data.get("seen_commit")
    if not since:
        return []
    rev = f"{since}..HEAD"
    if gitlog.git(home, "rev-list", "--count", rev).returncode != 0:
        return []  # the offset is gone (history rewritten or a fresh clone); caller resets it
    rows = changes.collect(home, rev_range=rev, limit=MAX_COMMITS)
    rows = [row for row in rows if row["session"] != session]
    if not rows:
        return []
    read, cursors, names = focus(home, data)
    try:
        by_rel = {f"memory/{item['file']}": item for item in indexer.notes(home)}
    except OSError:
        by_rel = {}
    out = []
    for row in rows:
        hits = []
        for rel in row["paths"]:
            if not indexer.is_note(rel) or indexer.is_index_file(rel):
                continue
            if rel in read:
                hits.append((rel, "read"))
            elif rel in cursors:
                hits.append((rel, "cursor"))
            elif names and _links(home, rel) & names:
                hits.append((rel, "hop"))
        if hits:
            out.append({**row, "hits": hits, "by_rel": by_rel})
    return out


def render(rows):
    """At most MAX_LINES lines: one line per commit, the ones touching notes read directly first.

    One line per commit, not per note. A single turn often rewrites a dozen notes for one reason, and
    printing each separately spends the whole budget on one change and repeats its reason verbatim.
    """
    groups = []
    seen = set()
    for row in rows:
        fresh = [(rel, how) for rel, how in row["hits"] if rel not in seen]
        if not fresh:
            continue
        seen.update(rel for rel, _ in fresh)
        why = row.get("why") or {}
        groups.append({"row": row, "hits": fresh,
                       "tier": min(TIERS[how] for _, how in fresh),
                       "reason": why.get("prompt") or why.get("result")})
    groups.sort(key=lambda g: (g["tier"], -(g["row"]["time"].timestamp() if g["row"]["time"] else 0)))

    lines = []
    for group in groups[:MAX_LINES]:
        row, hits = group["row"], group["hits"]
        names = [_label(rel, row["by_rel"]) for rel, _ in hits]
        who = "another session" if row["session"] else f"outside a session ({row['agent'] or 'unknown agent'})"
        tail = f': "{changes._one_line(group["reason"], QUOTE)}"' if group["reason"] else " (no reason recorded)"
        mark = MARKS[group["tier"]]
        if len(names) == 1:
            head = f"- {names[0]} changed"
        else:
            shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
            head = f"- {len(names)} notes changed ({shown})"
        lines.append(f"{head} {_ago(row['time'])} by {who}{mark}{tail}")
    if not lines:
        return ""
    dropped = len(groups) - len(lines)
    if dropped > 0:
        lines.append(f"- and {dropped} more change(s); `receipts-wiki watch` shows them")
    return ("Memory changed elsewhere while you worked:\n" + "\n".join(lines)
            + "\nRe-read what you are relying on before you use it.")


def last_reasons(home, rels, scan=250):
    """For each rel, when it last changed and why: {rel: {"time", "reason"}}.

    One pass over recent history rather than a git log per note, and the archive of each session involved is
    parsed once. A cursor that has not changed within `scan` commits is simply absent.
    """
    newest = {}
    for row in changes.commits(home, limit=scan):
        for rel in row["paths"]:
            if rel in rels and rel not in newest:
                newest[rel] = row
        if len(newest) == len(rels):
            break
    cache, out = {}, {}
    for rel, row in newest.items():
        session = row["session"]
        if session and session not in cache:
            cache[session] = changes.archive_entries(home, session)
        why = changes.reason(cache.get(session) or [], row["turn"], row["time"]) if session else None
        why = why or {}
        out[rel] = {"time": row["time"], "reason": why.get("prompt") or why.get("result")}
    return out


def notice(home, session, data):
    """The notice for this prompt, advancing the session's offset. Returns "" when there is nothing to say."""
    current = head(home)
    if not current:
        return ""
    if not data.get("seen_commit"):
        data["seen_commit"] = current  # first sight: start the offset here, never replay history
        return ""
    if data["seen_commit"] == current:
        return ""
    try:
        rows = pending(home, session, data)
    except OSError:
        rows = []
    data["seen_commit"] = current
    return render(rows)
