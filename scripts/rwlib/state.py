"""State kept outside git, under <home>/.state/.

sessions/<id>.json   one log per session: files it wrote this turn and not yet committed ("pending"),
                     hashes of memory files it read or wrote, how far its transcript was archived,
                     when its current turn started and stopped, and when it last swept
last_read.json       per memory file: the last date any session read or wrote it (forgetting candidates)
commit_health.json   the last failed catch-up commit, until a later one succeeds
"""
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from . import config


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_since(stamp):
    try:
        then = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds()


def content_hash(path, rel):
    """Hash of a memory file as the gate compares it. For MEMORY.md the generated block is ignored."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if rel == "memory/MEMORY.md":
        text = data.decode("utf-8", errors="replace")
        if config.BLOCK_START in text and config.BLOCK_END in text:
            text = text.split(config.BLOCK_START, 1)[0].rstrip() + "\n" + text.split(config.BLOCK_END, 1)[1].lstrip()
        data = text.strip().encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _load_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


def _session_path(session):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session or "unknown")[:128]
    return config.state_dir() / "sessions" / f"{safe}.json"


def load(session):
    data = _load_json(_session_path(session))
    for key in ("reads", "pending"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    data["session"] = session or "unknown"
    return data


def save(session, data):
    data["session"] = session or "unknown"
    data["updated"] = now_iso()
    _save_json(_session_path(session), data)


def all_sessions():
    folder = config.state_dir() / "sessions"
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        data = _load_json(path)
        if data.get("session"):
            if not isinstance(data.get("pending"), dict):
                data["pending"] = {}
            if not isinstance(data.get("reads"), dict):
                data["reads"] = {}
            yield data


def remove(session):
    try:
        _session_path(session).unlink()
    except OSError:
        pass


def load_health():
    """The last failed commit outside a session's own turn (catch-up or record), if it has not recovered."""
    return _load_json(config.state_dir() / "commit_health.json")


def save_health(detail, paths):
    previous = load_health()
    _save_json(config.state_dir() / "commit_health.json", {
        "since": previous.get("since") or now_iso(), "at": now_iso(),
        "detail": detail, "paths": sorted(paths)[:10],
    })


def clear_health():
    try:
        (config.state_dir() / "commit_health.json").unlink()
    except OSError:
        pass


def touch_read(rel, when=None):
    path = config.state_dir() / "last_read.json"
    data = _load_json(path)
    data[rel] = when or date.today().isoformat()
    _save_json(path, data)


def last_reads():
    return _load_json(config.state_dir() / "last_read.json")
