"""The memory log with its reasons: each memory commit joined to the conversation turn that made it.

Every commit written by the hooks names its Session and Turn; the archive holds that turn's messages. The
reason for a change is shown as three quotes from the archive, never a summary: the prompt that started the
turn, the assistant message the prompt answered when the prompt is a short reply ("yes pls"), and the last
assistant message of the turn before the commit. Archive entries written before turn ids were recorded are
joined by session and time instead, and the output says so.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import frontmatter, gitlog, indexer

HEADING = re.compile(r"^##\s+(?P<ts>\S+)\s+(?P<role>user|assistant)\s+\(line\s+(?P<line>\d+)(?:,\s*turn\s+(?P<turn>[\w.-]+))?\)", re.I)
TRAILER = re.compile(r"^(?P<key>Session|Turn|Agent|Change):\s*(?P<value>.+)$", re.M)
ACTION = re.compile(r"^(?:rejected|intent|constraint)\(.+$", re.M)
SHORT_PROMPT = 80
QUOTE = 160


def _time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _one_line(text, width=QUOTE, tail=False):
    flat = " ".join(str(text or "").split())
    if len(flat) <= width:
        return flat
    return "…" + flat[-(width - 1):] if tail else flat[:width - 1] + "…"


def commits(home, since=None, rel=None, limit=None, rev_range=None):
    """Memory commits, newest first, index rebuilds excluded.

    `since` is a git date; `rev_range` is a revision range such as "<sha>..HEAD", which is what a session's
    offset needs -- "everything after the commit I was last shown", which no date can express exactly.
    """
    args = ["log", "--format=%H%x01%cI%x01%s%x01%b%x02"]
    if since:
        args.append(f"--since={since}")
    if rev_range:
        args.append(rev_range)
    if rel:
        args += ["--", rel]
    out = gitlog.git(home, *args).stdout
    found = []
    for record in out.split("\x02"):
        record = record.strip("\n")
        if not record.strip():
            continue
        sha, when, subject, body = (record.split("\x01") + ["", "", ""])[:4]
        if subject.endswith("rebuild indexes"):
            continue
        trailers = {}
        paths = []
        for match in TRAILER.finditer(body):
            if match.group("key") == "Change":
                paths.append(match.group("value").split()[-1])
            else:
                trailers.setdefault(match.group("key").lower(), match.group("value").strip())
        found.append({"commit": sha[:10], "time": _time(when), "subject": subject, "session": trailers.get("session"),
                      "turn": trailers.get("turn", "").split(",")[0].strip() or None, "agent": trailers.get("agent"),
                      "paths": paths, "actions": ACTION.findall(body)})
        if limit and len(found) >= limit:
            break
    return found


def archive_entries(home, session):
    """All archived messages of one session, in time order: {ts, role, line, turn, text}."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session or "")[:128]
    entries = []
    for path in sorted((Path(home) / "sessions").glob(f"*/*/{safe}.md")):
        _, body = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        for block in re.split(r"\n(?=## )", "\n" + body):
            block = block.strip()
            match = HEADING.match(block)
            if not match:
                continue
            ts = _time(match.group("ts"))
            if ts is None:
                continue
            entries.append({"ts": ts, "role": match.group("role").lower(), "line": int(match.group("line")),
                            "turn": match.group("turn"), "text": block.partition("\n")[2].strip()})
    entries.sort(key=lambda e: e["ts"])
    return entries


def reason(entries, turn, when):
    """The three quotes for a commit made in `turn` at `when`, and how they were found ("turn" or "time")."""
    if when is None:
        return None
    # git stores commit times in whole seconds and the commit is made after the turn's last message, which the
    # truncation can place just "after" the commit
    upto = [e for e in entries if e["ts"] < when + timedelta(seconds=1)]
    in_turn = [e for e in upto if turn and e["turn"] == turn]
    if in_turn and any(e["role"] == "user" for e in in_turn):
        how = "turn"
        prompt = next(e for e in in_turn if e["role"] == "user")
        replies = [e for e in in_turn if e["role"] == "assistant" and e["ts"] >= prompt["ts"]]
    else:
        users = [e for e in upto if e["role"] == "user"]
        if not users:
            return None
        how = "time"
        prompt = users[-1]
        replies = [e for e in upto if e["role"] == "assistant" and e["ts"] >= prompt["ts"]]
    before = [e for e in entries if e["role"] == "assistant" and e["ts"] < prompt["ts"]]
    question = before[-1]["text"] if before and len(" ".join(prompt["text"].split())) <= SHORT_PROMPT else None
    return {"how": how, "prompt": prompt["text"], "prompt_at": prompt["ts"],
            "answered": question, "result": replies[-1]["text"] if replies else None}


def _areas(home):
    try:
        return {f"memory/{item['file']}": item["area"] for item in indexer.notes(home)}
    except OSError:
        return {}


def collect(home, since=None, rel=None, area=None, limit=20, rev_range=None):
    rows = commits(home, since=since, rel=rel, limit=None if area else limit, rev_range=rev_range)
    if area:
        areas = _areas(home)
        rows = [row for row in rows if any(areas.get(path) == area for path in row["paths"])][:limit]
    cache = {}
    for row in rows:
        session = row["session"]
        if session and session not in cache:
            cache[session] = archive_entries(home, session)
        row["why"] = reason(cache.get(session) or [], row["turn"], row["time"]) if session else None
    return rows


def render(rows):
    lines = []
    for row in rows:
        when = row["time"].strftime("%Y-%m-%d %H:%M") if row["time"] else "?"
        lines.append(f"{when}  {row['subject']}  [{row['commit']}]")
        why = row.get("why")
        if not row["session"]:
            lines.append(f"  changed outside a session ({row['agent'] or 'unknown agent'}); no conversation recorded")
        elif not why:
            lines.append(f"  session {row['session'][:8]}: no archived conversation before this commit")
        else:
            if why["answered"]:
                lines.append(f"  answered: \"{_one_line(why['answered'], tail=True)}\"")
            lines.append(f"  prompt:   \"{_one_line(why['prompt'])}\"")
            if why["result"]:
                lines.append(f"  result:   \"{_one_line(why['result'])}\"")
            if why["how"] == "time":
                lines.append("  (joined by time: this archive entry predates turn ids)")
        for action in row["actions"]:
            lines.append(f"  {_one_line(action, 200)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else "no memory changes in this range\n"


def as_json(rows):
    out = []
    for row in rows:
        why = row.get("why") or {}
        out.append({"commit": row["commit"], "time": row["time"].isoformat() if row["time"] else None,
                    "subject": row["subject"], "session": row["session"], "turn": row["turn"], "agent": row["agent"],
                    "paths": row["paths"], "actions": row["actions"], "joined_by": why.get("how"),
                    "prompt": why.get("prompt"), "answered": why.get("answered"), "result": why.get("result")})
    return out
