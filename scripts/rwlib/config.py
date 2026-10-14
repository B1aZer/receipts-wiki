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


INSTALL_RECORD = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def installed_build(record=None):
    """What Claude Code records as the installed copy of this plugin: {"path", "commit", "updated"}, or {}.

    Deliberately not the version string. `0.4.1-dev.1` was set in 89f2af7, the commit BEFORE the
    multi-session fix, and d2b4ec9 never bumped it -- so the build that quoted another session's user
    turns into this one and the build that stopped doing it report the identical version. Three
    sessions circulated "running 0.4.1-dev.1" as an install receipt, and that sentence was satisfied
    by the leaking build. `gitCommitSha` changes on every install, a reinstall of one version
    included, and is the only field here that does.
    """
    try:
        import json
        data = json.loads((record or INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mine = version_name()
    for key, entries in (data.get("plugins") or {}).items():
        if str(key).partition("@")[0] != mine:
            continue
        for entry in entries if isinstance(entries, list) else [entries]:
            if isinstance(entry, dict) and entry.get("installPath"):
                return {"path": entry["installPath"], "commit": entry.get("gitCommitSha") or "",
                        "updated": entry.get("lastUpdated") or ""}
    return {}


def version_name():
    """This plugin's name as the install record spells it, or "" when it cannot be read."""
    try:
        import json
        return str(json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("name") or "")
    except (OSError, ValueError):
        return ""


def superseded(seen=None, record=None, root=None):
    """A line for the agent when this process is not running the installed copy, else "".

    `${CLAUDE_PLUGIN_ROOT}` is resolved once per PROCESS, so a session goes on executing the tree it
    started with however many times the plugin is reinstalled. On 2026-10-14 a fix for a context leak
    was installed and 15 of 16 live sessions kept running trees that still carried it for hours; three
    were proven to have emitted after the install, the last of them nearly five hours later.

    `newer_installed()` cannot catch that, and not because it is broken: it is evaluated in the
    SessionStart hook, which runs BEFORE the newer copy exists. In the one situation the guard was
    written for -- a long-running session -- it is structurally guaranteed to return "". So the check
    is correct and runs at the only moment it cannot know anything. This is the same question asked on
    the prompt path, where there is something to compare against.

    Two conditions, because they catch different things and each is quiet unless it is really true:
    the bound root differing from the recorded install path catches a version change and needs no
    history, while the commit differing from the one seen earlier in this session catches a reinstall
    of the SAME version -- which is exactly the 89f2af7 -> d2b4ec9 case the version string hides.
    """
    now = installed_build(record)
    if not now:
        return ""
    here = Path(root or ROOT)
    # Only when this process is running ANOTHER INSTALL of the plugin, which is the real hazard: the
    # installs are siblings under one cache directory. A working checkout -- a contributor's clone, or
    # the marketplace checkout, neither of which a hook binds -- lives elsewhere and must stay quiet,
    # or the notice fires forever in the one place the code is being changed on purpose and teaches
    # everyone to ignore it.
    installed = Path(now["path"]) if now["path"] else None
    if installed and here.parent != installed.parent:
        return ""
    if installed and installed != here:
        return (f"receipts-wiki: this session is running the copy at {here}, but the installed copy is "
                f"{installed} (commit {now['commit'][:12] or 'unknown'}, installed {now['updated'] or 'unknown'}). "
                "The plugin root is resolved once per process, so this session keeps the older code -- its rules, "
                "generators and gates are the ones it started with. Restart the session to pick up the installed copy, "
                "and until then avoid `build-index` and memory-wide rewrites.")
    if seen and seen.get("commit") and now["commit"] and seen["commit"] != now["commit"]:
        return (f"receipts-wiki: the plugin was reinstalled during this session -- commit {seen['commit'][:12]} when it "
                f"started, {now['commit'][:12]} now, at the same path. The version string does not change on a "
                "reinstall, so nothing else will say so. This session is still running the older code; restart to "
                "pick it up.")
    return ""


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
