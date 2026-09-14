"""Conversation archive, updated at the end of each turn, outside git.

Archive files are append-only: one file per session per month, and text already written is never changed.
It holds only what the user and the agent wrote as messages, redacted, and is searched only on request.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from . import secrets, transcript


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
