"""Conversation archive and lesson candidates, updated at the end of each turn, outside git.

Archive files are append-only: one file per session per month, and text already written is never
changed. Lesson candidates are the user's own words, quoted; nothing is drafted by a model here and
nothing is written to memory.
"""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from . import secrets, transcript

LESSON_MARKER = re.compile(
    r"\b(from now on|never|always|don't|do not|stop doing|i meant|that's wrong|that is wrong|not what i|remember that|make sure)\b",
    re.I,
)
LESSON_MIN_CHARS = 15
LESSON_MAX_CHARS = 600


def _safe(session):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session or "unknown")[:128]


def _one_line(value):
    return " ".join(str(value or "").split())


def _month_folder(home, timestamp):
    if timestamp and re.match(r"^\d{4}-\d{2}", str(timestamp)):
        year, month = str(timestamp)[:4], str(timestamp)[5:7]
    else:
        now = datetime.now(timezone.utc)
        year, month = f"{now:%Y}", f"{now:%m}"
    return Path(home) / "sessions" / year / month


def append(home, session, transcript_path, cwd, data):
    """Append messages written since the last call. Updates the session log in data. Returns the new messages."""
    meta, messages = transcript.read(transcript_path, data.get("archived_line", 0), data.get("archived_offset", 0))
    data["archived_line"], data["archived_offset"] = meta["last_line"], meta["offset"]
    if meta["title"]:
        data["title"] = meta["title"]
    for key in ("branch", "cwd"):
        if meta[key] and not data.get(key):
            data[key] = meta[key]

    groups = {}
    for message in messages:
        text = secrets.redact(message["text"]).strip()
        if text:
            block = f"## {_one_line(message['ts'])} {message['role']} (line {message['line']})\n\n{text}\n"
            groups.setdefault(_month_folder(home, message["ts"]), []).append(block)
    for folder, blocks in groups.items():
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_safe(session)}.md"
        header = ""
        if not path.exists():
            header = "\n".join([
                "---",
                f"session: {_one_line(session)}",
                f"title: {_one_line(data.get('title'))}",
                f"cwd: {_one_line(data.get('cwd') or cwd)}",
                f"branch: {_one_line(data.get('branch'))}",
                f"transcript: {_one_line(transcript_path)}",
                "---",
                "",
                "",
            ])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(header + "\n".join(blocks) + "\n")
    return messages


def lesson_candidates(messages, limit=2):
    """Short paragraphs of user messages that read like a correction or a standing rule."""
    scored = []
    for message in messages:
        if message["role"] != "user":
            continue
        for paragraph in re.split(r"\n\s*\n", message["text"]):
            text = paragraph.strip()
            if not (LESSON_MIN_CHARS <= len(text) <= LESSON_MAX_CHARS):
                continue
            markers = {hit.lower() for hit in LESSON_MARKER.findall(text)}
            if markers:
                scored.append((len(markers), message["line"], dict(message, text=text)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [message for _, _, message in scored[:limit]]


def _digest(text):
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:16]


def write_proposals(home, session, picks, data):
    """Append new candidates to proposals/<session>.md, skipping ones already proposed in this session."""
    seen = set(data.get("lessons") or [])
    fresh = [message for message in picks if _digest(message["text"]) not in seen]
    if not fresh:
        return None
    folder = Path(home) / "proposals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_safe(session)}.md"
    lines = []
    if not path.exists():
        lines += [
            "# Lesson candidates",
            "",
            f"Session {session}. These are the user's own words, flagged because they read like a correction or a standing rule. "
            "Nothing has been written to memory. Review them with the receipts-wiki lint-review skill: draft a note with the user, or discard them.",
            "",
        ]
    for message in fresh:
        quote = "\n".join("> " + line for line in secrets.redact(message["text"]).strip().splitlines())
        lines += [f"## {_one_line(message['ts'])} (line {message['line']})", "", quote, "", f"Receipt: session:{session}#L{message['line']}", ""]
        seen.add(_digest(message["text"]))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    data["lessons"] = sorted(seen)
    return path
