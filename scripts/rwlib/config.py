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


PATCH_RECORD_REL = "docs/patch-record.md"

# The files a hook actually executes. `__pycache__` is excluded because it is derived: it is
# rewritten on the first import after a patch, so its mtime reports when the code last RAN rather
# than when it last CHANGED, and counting it would report drift on a tree nobody touched.
_CODE_GLOBS = ("scripts/*.py", "scripts/**/*.py", "hooks/*.json")

# An install writes its tree in one operation but not in one instant. Files a few seconds apart are
# the same write; a file copied in hours later is not.
DRIFT_TOLERANCE_SECONDS = 10


def _code_files(root):
    seen, out = set(), []
    for pattern in _CODE_GLOBS:
        for path in sorted(Path(root).glob(pattern)):
            if "__pycache__" in path.parts or path in seen or not path.is_file():
                continue
            seen.add(path)
            out.append(path)
    return out


def _md5(path):
    try:
        import hashlib
        return hashlib.md5(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return ""


def _epoch(iso):
    """Epoch seconds for an install record timestamp, or None."""
    if not iso:
        return None
    try:
        from datetime import datetime, timezone
        parsed = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def drift(root=None, installed_at=None):
    """Which executable files in one install tree were written AFTER the tree itself was.

    `{"baseline", "population", "files": [{"rel", "mtime", "md5"}], "whole_tree", "reason"}`.

    An install writes its whole tree in one operation, so its files share one mtime to the second
    and a file copied in afterwards is the outlier. That makes the baseline the tree's OWN modal
    mtime rather than a threshold, which matters twice: no manifest of expected hashes has to be
    shipped and kept in step with every commit, and the answer still holds for a tree the install
    record no longer mentions -- which is most of them, since only the current install is recorded.

    Only LATER files count. An installer that preserved mtimes from somewhere else would leave
    files older than the mode, and "this was here before the tree" is not the question.

    The baseline is refused rather than guessed when no single write time accounts for most of the
    tree, because then the outliers are not outliers.

    The blind spot is the opposite extreme, and it is real: replace every file and the mode moves
    with them, so nothing is an outlier and this returns clean. `installed_at` -- the record's
    `lastUpdated`, and ONLY when this root is the recorded install path -- is the independent check
    for exactly that case: a mode that is not the install time means the whole tree moved.
    """
    base = Path(root or ROOT)
    files = _code_files(base)
    if len(files) < 5:
        return {"baseline": None, "population": len(files), "files": [], "whole_tree": False,
                "reason": "too few executable files here to establish a baseline"}
    stamps = {}
    for path in files:
        try:
            stamps[path] = path.stat().st_mtime
        except OSError:
            continue
    if not stamps:
        return {"baseline": None, "population": 0, "files": [], "whole_tree": False,
                "reason": "no file in this tree could be read"}
    import collections
    counts = collections.Counter(int(ts) for ts in stamps.values())
    baseline, agreeing = counts.most_common(1)[0]
    if agreeing * 2 <= len(stamps):
        return {"baseline": None, "population": len(stamps), "files": [], "whole_tree": False,
                "reason": "no single write time accounts for most of this tree"}
    later = []
    for path, ts in sorted(stamps.items()):
        if ts - baseline > DRIFT_TOLERANCE_SECONDS:
            later.append({"rel": str(path.relative_to(base)), "mtime": ts, "md5": _md5(path)})
    expected = _epoch(installed_at)
    return {"baseline": float(baseline), "population": len(stamps), "files": later,
            "whole_tree": bool(expected and not later and abs(baseline - expected) > 60),
            "reason": ""}


def patch_record(root):
    """What the committed patch record vouches for: `{"path", "hashes", "trees"}`, or `{}`.

    `docs/patch-record.md` is written and committed BEFORE any file under the plugin cache is
    copied, which is the whole reason it can turn "this tree is not the commit the host records for
    it" into an answer instead of an alarm. Read from the INSTALLED tree, never from this one: a
    patched tree is by definition older than the record, so it does not contain it.

    Deliberately coarse -- every 32-hex string and every backticked name in the document, with no
    table parsing at all. A strict parse of a hand-written markdown table is the wrong instrument
    here. Reformat a row and a strict parser either calls a recorded patch unexplained, which is a
    false alarm and how a gate teaches everyone to ignore it, or reads the wrong column and calls
    an unrecorded change explained, which is the false quiet this record exists to prevent. The
    coarse rule cannot go quiet: the notice fires either way and names the file and the hash, so a
    person can go and find the row.
    """
    path = Path(root) / PATCH_RECORD_REL
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    import re
    return {"path": str(path),
            "hashes": {h.lower() for h in re.findall(r"\b[0-9a-fA-F]{32}\b", text)},
            "trees": set(re.findall(r"`([0-9][0-9A-Za-z.\-]*)`", text))}


def _when(epoch):
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


def drift_line(here, patched, installed, build):
    """The agent-facing sentence for a tree whose content is not what the host recorded for it."""
    if patched["whole_tree"]:
        return (f"receipts-wiki: every executable file in {here} is dated {_when(patched['baseline'])}, which is "
                f"not when the install record says this copy was installed ({build.get('updated') or 'unknown'}). "
                "The whole tree differs from what the host recorded, not one file of it, so a per-file hash cannot "
                "see this. Reported rather than resolved: treat the recorded commit as unverified for this session.")
    record = patch_record(installed) if installed else {}
    vouched = record.get("hashes") or set()
    known = [f for f in patched["files"] if f["md5"] and f["md5"].lower() in vouched]
    unknown = [f for f in patched["files"] if f not in known]
    shown = ", ".join(f"{f['rel']} (md5 {f['md5'][:8] or '?'}, written {_when(f['mtime'])})"
                      for f in patched["files"][:6])
    more = f" and {len(patched['files']) - 6} more" if len(patched["files"]) > 6 else ""
    head = (f"receipts-wiki: this session's plugin tree was changed in place after it was installed -- "
            f"{shown}{more}.")
    if not record:
        return (f"{head} There is no patch record at {Path(installed or here) / PATCH_RECORD_REL} to account for it, "
                "so nothing says who changed it or why. This session's code is not the commit the install record "
                "names, and no receipt from it should cite that commit.")
    if unknown:
        return (f"{head} {record['path']} does not account for "
                + ", ".join(f['rel'] for f in unknown)
                + ". Either the record was not written before the copy, which is the one order this project fixes, "
                  "or something changed this tree that nobody recorded. Until a row explains it, this session's "
                  "code is not the commit the install record names.")
    return (f"{head} {record['path']} vouches for that content, so this is a recorded remediation and not a "
            "surprise -- but the tree still does not match the commit the install record names for it, so cite "
            "the record rather than the commit when this session reports its own build.")


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

    Three conditions, because they catch different things and each is quiet unless it is really true:
    the bound root differing from the recorded install path catches a version change and needs no
    history; the commit differing from the one seen earlier in this session catches a reinstall
    of the SAME version -- which is exactly the 89f2af7 -> d2b4ec9 case the version string hides;
    and the tree's own CONTENT being newer than the tree catches an in-place patch, which neither
    path nor commit can see because neither of them moves when a file is copied over.

    The third is the one that had to be added. The first gave three different states the same
    sentence -- a tree still carrying a defect, a tree patched in place to remove it, and an older
    install that was correct while it was current all read as "older code, restart" -- and it is
    blind at the installed path, where an in-place patch leaves the path identical and every
    session started after this build is bound. `docs/patch-record.md` is what turns that alarm into
    an answer. It is deliberately NOT what silences it: the content really does differ from the
    commit the host recorded, so a receipt from this session cannot cite that commit, and a true
    alarm with a documented answer is the thing this project wants rather than a quiet one.
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
    clauses = []
    if installed and installed != here:
        clauses.append(
            f"receipts-wiki: this session is running the copy at {here}, but the installed copy is "
            f"{installed} (commit {now['commit'][:12] or 'unknown'}, installed {now['updated'] or 'unknown'}). "
            "The plugin root is resolved once per process, so this session keeps the older code -- its rules, "
            "generators and gates are the ones it started with. Restart the session to pick up the installed copy, "
            "and until then avoid `build-index` and memory-wide rewrites.")
    elif seen and seen.get("commit") and now["commit"] and seen["commit"] != now["commit"]:
        clauses.append(
            f"receipts-wiki: the plugin was reinstalled during this session -- commit {seen['commit'][:12]} when it "
            f"started, {now['commit'][:12]} now, at the same path. The version string does not change on a "
            "reinstall, so nothing else will say so. This session is still running the older code; restart to "
            "pick it up.")
    # Content, not path -- and ADDED to whatever the path said rather than replacing it, because the
    # two facts are independent and a patched stale tree is the state where only the pair is true.
    # The path check alone gave three of the four states the same sentence: a tree still carrying a
    # defect, a tree patched in place to remove it, and an older install that was correct when it was
    # current all read as "older code, restart". It is also blind in the one direction that matters
    # from here on: a tree patched in place AT the installed path passes the path check, and every
    # session started after this build is bound to exactly that tree.
    patched = drift(here, installed_at=now["updated"] if installed == here else None)
    if patched["files"] or patched["whole_tree"]:
        clauses.append(drift_line(here, patched, installed, now))
    return "\n\n".join(clauses)


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
