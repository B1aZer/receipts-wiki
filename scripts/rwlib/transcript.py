"""Reads Claude Code session transcripts (JSONL), incrementally.

The transcript format is not a documented interface, so every field is read defensively.
Only user and assistant text blocks are returned; tool calls, tool results and metadata are skipped.
A final line without a newline may still be in progress and is left for the next read.
"""
import json
import os


def read(path, start_line=0, start_offset=0):
    """Return (meta, messages) for complete lines after the given line number and byte offset.

    meta: title, branch, cwd, last_line, offset. messages: dicts with line, role, ts, text.
    """
    meta = {"title": None, "branch": None, "cwd": None, "last_line": start_line, "offset": start_offset}
    messages = []
    try:
        handle = open(path, "rb")
    except (OSError, TypeError):
        return meta, messages
    with handle:
        try:
            size = os.fstat(handle.fileno()).st_size
        except OSError:
            size = 0
        if start_offset > size:
            start_line, start_offset = 0, 0
            meta["last_line"], meta["offset"] = 0, 0
        handle.seek(start_offset)
        number, offset = start_line, start_offset
        for raw in handle:
            if not raw.endswith(b"\n"):
                break
            number += 1
            offset += len(raw)
            meta["last_line"], meta["offset"] = number, offset
            try:
                record = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") == "ai-title" and record.get("aiTitle"):
                meta["title"] = record["aiTitle"]
            meta["branch"] = meta["branch"] or record.get("gitBranch")
            meta["cwd"] = meta["cwd"] or record.get("cwd")
            role = record.get("type")
            if role not in ("user", "assistant") or record.get("isMeta") or record.get("isSidechain") or _not_written_by_user(record):
                continue
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            text = _text(message.get("content"))
            if text.strip():
                messages.append({"line": number, "role": role, "ts": record.get("timestamp"), "text": text})
    return meta, messages


def _not_written_by_user(record):
    """Records stored under the user role that nobody typed: compaction summaries, task notifications
    (a background agent's report) and other prompts Claude Code marks as coming from the system."""
    origin = record.get("origin") if isinstance(record.get("origin"), dict) else {}
    return bool(record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly")
                or record.get("promptSource") == "system" or origin.get("kind") == "task-notification")


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text")
    return ""
