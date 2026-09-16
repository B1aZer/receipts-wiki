"""Resume: recover a dead or interrupted session.

Mines a session's redacted conversation archive (sessions/**/<id>.md) for the decisions,
next actions and open loops it reached, drops the ones an existing memory note already
covers, and returns the rest as recovery candidates.

Nothing here is written to memory. The archive text is untrusted data (redacted past
conversation, possibly carrying injected content), so it is quoted as a candidate for a
human to review, never executed as an instruction.
"""
import re
from pathlib import Path

from . import frontmatter, indexer, related

# Blocks that read like a position, a decision or a next action worth carrying forward.
SIGNAL = re.compile(
    r"\b(decided|decision|next step|next:|to ?do|still need|still to|remaining|left to do|"
    r"blocked|open question|the plan is|we will|i will|ready to|not yet|haven'?t|"
    r"in progress|working on|figured out|turns out|conclusion|so the fix|the fix is)\b",
    re.I,
)
MIN_CHARS = 20
MAX_CHARS = 800
COVERED_THRESHOLD = 0.7
HEADING = re.compile(r"^##\s+(?P<ts>\S+)\s+(?P<role>user|assistant)\s+\(line\s+(?P<line>\d+)\)", re.I)


def sessions(home, session_id=None, cwd=None):
    """Session descriptors from the archive, most recent first.

    Each: {session, title, cwd, files:[Path,...], mtime}. Filter by exact session id;
    else, when cwd is given, keep only sessions whose archived cwd matches it.
    """
    want_cwd = _resolve(cwd) if cwd else None
    found = {}
    root = Path(home) / "sessions"
    for path in sorted(root.rglob("*.md")) if root.exists() else []:
        try:
            fm, _ = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        sid = str(frontmatter.get(fm, "session") or path.stem)
        if session_id and sid != session_id and path.stem != session_id:
            continue
        entry = found.setdefault(sid, {"session": sid, "title": "", "cwd": "", "files": [], "mtime": 0.0})
        entry["files"].append(path)
        entry["title"] = entry["title"] or (frontmatter.get(fm, "title") or "")
        entry["cwd"] = entry["cwd"] or (frontmatter.get(fm, "cwd") or "")
        try:
            entry["mtime"] = max(entry["mtime"], path.stat().st_mtime)
        except OSError:
            pass
    result = list(found.values())
    if want_cwd and not session_id:
        result = [entry for entry in result if _resolve(entry["cwd"]) == want_cwd]
    result.sort(key=lambda entry: entry["mtime"], reverse=True)
    return result


def _resolve(path):
    try:
        return str(Path(str(path)).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


def _blocks(body):
    for block in re.split(r"\n(?=## )", "\n" + body):
        block = block.strip()
        match = HEADING.match(block)
        if not match:
            continue
        _, _, content = block.partition("\n")
        yield {"ts": match.group("ts"), "role": match.group("role").lower(),
               "line": int(match.group("line")), "text": content.strip()}


def mine(home, entry):
    """Candidate position/decision blocks from a session's archive files, in transcript order."""
    picks = []
    for path in entry["files"]:
        try:
            _, body = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for block in _blocks(body):
            if MIN_CHARS <= len(block["text"]) <= MAX_CHARS and SIGNAL.search(block["text"]):
                picks.append(dict(block, file=str(path.relative_to(Path(home)))))
    picks.sort(key=lambda block: block["line"])
    return picks


def _memory_vocab(home):
    """The union of tokens across every active note: what memory already knows about."""
    vocab = set()
    for item in indexer.notes(home):
        if item["status"] == "retired":
            continue
        vocab |= related.tokens(f"{item['name']} {item['description']} {item['text'][:800]}")
    return vocab


def uncovered(home, picks, threshold=COVERED_THRESHOLD):
    """Drop candidates whose distinctive words are mostly already present in memory."""
    vocab = _memory_vocab(home)
    out = []
    for block in picks:
        toks = related.tokens(block["text"])
        if len(toks) < 3:
            continue
        known = (len(toks & vocab) / len(toks)) if vocab else 0.0
        if known < threshold:
            out.append(dict(block, known=round(known, 2)))
    return out
