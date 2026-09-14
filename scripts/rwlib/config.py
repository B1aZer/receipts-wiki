"""Where the memory home and the plugin's own files live, and the timing and size limits."""
import os
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
WRITING_GUIDE = PLUGIN_ROOT / "templates" / "WRITING.md"

# Claude Code replaces oversized hook output with a stub, so rules injected at session start stay under this.
AGENTS_BUDGET_BYTES = 8000
AGENTS_BUDGET_LINES = 50

# Generated block inside memory/MEMORY.md; text outside it belongs to the user and the agent.
BLOCK_START = "<!-- receipts-wiki:areas:start -->"
BLOCK_END = "<!-- receipts-wiki:areas:end -->"

# A session log with uncommitted writes and no activity for this long is committed by another session.
STALE_JOURNAL_MINUTES = 60
# Catch-up at a new prompt runs at most this often per session.
SWEEP_INTERVAL_SECONDS = 600
# Pending lesson proposals are mentioned at most this often per session.
PROPOSAL_NOTICE_SECONDS = 86400
# Session logs with nothing pending are removed after this many days of inactivity.
JOURNAL_RETENTION_DAYS = 30


def home():
    """The memory home: $RECEIPTS_WIKI_HOME, or ~/.agents."""
    raw = os.environ.get("RECEIPTS_WIKI_HOME") or str(Path.home() / ".agents")
    return Path(raw).expanduser().resolve()


def memory_dir():
    return home() / "memory"


def state_dir():
    return home() / ".state"


def claude_settings_path():
    raw = os.environ.get("RECEIPTS_WIKI_CLAUDE_SETTINGS") or str(Path.home() / ".claude" / "settings.json")
    return Path(raw).expanduser()


def tracked(file_path):
    """Return the path relative to the memory home when hooks should act on it, else None.

    Hooks act on markdown files under memory/ and on the home's AGENTS.md.
    """
    if not file_path:
        return None
    try:
        real = Path(file_path).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    root = home()
    if real == root / "AGENTS.md":
        return "AGENTS.md"
    try:
        rel = real.relative_to(root / "memory")
    except ValueError:
        return None
    if real.suffix != ".md" or any(part.startswith(".") for part in rel.parts):
        return None
    return str(Path("memory") / rel)
