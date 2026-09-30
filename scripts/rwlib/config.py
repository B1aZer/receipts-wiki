"""Where the memory home and the plugin's own files live, and the timing and size limits."""
import os
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
WRITING_GUIDE = PLUGIN_ROOT / "templates" / "WRITING.md"

# Claude Code replaces oversized hook output with a stub, so rules injected at session start stay under this.
AGENTS_BUDGET_BYTES = 8000
AGENTS_BUDGET_LINES = 50
# The area index for the working directory is loaded by its own SessionStart hook, under the same output cap.
AREA_INDEX_CHARS = 9000

# Generated block inside memory/MEMORY.md; text outside it belongs to the user and the agent.
BLOCK_START = "<!-- receipts-wiki:areas:start -->"
BLOCK_END = "<!-- receipts-wiki:areas:end -->"

# A session log with uncommitted writes and no activity for this long is committed by another session.
STALE_JOURNAL_MINUTES = 60
# Catch-up at a new prompt runs at most this often per session.
SWEEP_INTERVAL_SECONDS = 600
# Session logs with nothing pending are removed after this many days of inactivity.
JOURNAL_RETENTION_DAYS = 30


def attended():
    """False in sessions nobody is watching, such as `claude -p` or SDK runs, where receipts-wiki adds no context.

    Claude Code sets CLAUDE_CODE_SESSION_ATTENDED (1 or 0) and CLAUDE_CODE_ENTRYPOINT (cli, sdk-cli, ...) for hooks.
    RECEIPTS_WIKI_ATTENDED=1 or 0 overrides both, for example in evals that use `claude -p` to stand in for a user.
    """
    override = os.environ.get("RECEIPTS_WIKI_ATTENDED")
    if override in ("0", "1"):
        return override == "1"
    flag = os.environ.get("CLAUDE_CODE_SESSION_ATTENDED")
    if flag in ("0", "1"):
        return flag == "1"
    return not os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk")


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


ROOT = Path(__file__).resolve().parents[2]


def version():
    """This copy's version string, or "" when it cannot be read."""
    try:
        import json
        return str(json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def _version_key(text):
    """Sortable key for 0.3.0-dev.26: release numbers first, then the pre-release number.

    A release sorts above its own pre-releases, so 0.3.0 beats 0.3.0-dev.26.
    """
    head, _, pre = text.partition("-")
    nums = [int(n) if n.isdigit() else 0 for n in head.split(".")]
    pre_num = int("".join(c for c in pre if c.isdigit()) or 0) if pre else None
    return (nums, 1 if pre_num is None else 0, pre_num or 0)


def newer_installed():
    """A newer version of this plugin installed beside this one, or "".

    Installs live at <cache>/<marketplace>/<plugin>/<version>/, so the siblings of this copy's
    directory are the other installed versions. A long-running session keeps the code it started
    with, so it can silently act on rules and generators several releases old -- which on 2026-09-30
    rewrote 29 of 33 generated indexes from a session that had not restarted.
    """
    mine = version()
    if not mine or ROOT.name != mine:
        return ""   # not running from a versioned install directory; nothing to compare against
    try:
        siblings = [d.name for d in ROOT.parent.iterdir() if d.is_dir() and d.name != mine]
    except OSError:
        return ""
    newer = [name for name in siblings if _version_key(name) > _version_key(mine)]
    return max(newer, key=_version_key) if newer else ""


# What the memory repository versions. `memory/` and `AGENTS.md` are the notes and the rules; `plans/`
# holds long-form maintainer documents that are private, durable and too large to be notes — a plan is
# not a fact, so it gets no frontmatter, no index line and no 12 KB budget, but it does get history.
# Anything else in the home is either ignored by the home's own .gitignore (sessions/, .state/,
# proposals/) or deliberately not the plugin's business.
VERSIONED = ("memory", "AGENTS.md", "plans")


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
