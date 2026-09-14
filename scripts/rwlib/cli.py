"""Maintenance commands. Only build-index writes; history, recall and lint read and report."""
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import config, frontmatter, gitlog, indexer, secrets, state, turns

HOOK_MARK = "receipts-wiki pre-commit hook"
HOOK_SCRIPT = """#!/bin/sh
# {mark}: checks staged memory files for secret values and missing frontmatter on every commit,
# including commits made by other agents or by hand. Skip it once with `git commit --no-verify`.
RW="${{RECEIPTS_WIKI_RW:-}}"
if [ -z "$RW" ]; then
  RW=$(ls -dt "$HOME"/.claude/plugins/cache/receipts-wiki/receipts-wiki/*/scripts/rw.py 2>/dev/null | head -n 1)
fi
[ -n "$RW" ] || RW="{fallback}"
if [ ! -f "$RW" ]; then
  echo "receipts-wiki pre-commit: plugin not found, commit not checked" >&2
  exit 0
fi
RECEIPTS_WIKI_HOME="$(git rev-parse --show-toplevel)" exec python3 "$RW" precommit
"""


def precommit(home):
    """Check the staged memory files of any commit. Exit status 1 blocks the commit."""
    staged = gitlog.git(home, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "--", "memory", "AGENTS.md").stdout.split()
    problems, warnings = [], []
    for rel in staged:
        if not rel.endswith(".md"):
            continue
        text = gitlog.git(home, "show", f":{rel}").stdout
        label = secrets.find_secret(text)
        if label:
            problems.append(f"{rel} contains a secret value ({label}); store the secret's name or location instead")
        if indexer.is_note(rel):
            fm, _ = frontmatter.split(text)
            if not fm:
                problems.append(f"{rel} has no frontmatter (name, description, metadata.type)")
            else:
                missing = [key for key in ("name", "description") if not frontmatter.get(fm, key)]
                if missing:
                    problems.append(f"{rel} is missing {' and '.join(missing)} in its frontmatter")
        elif rel == "AGENTS.md":
            if len(text.encode("utf-8")) > config.AGENTS_BUDGET_BYTES:
                warnings.append(f"AGENTS.md is over the {config.AGENTS_BUDGET_BYTES}-byte budget")
        elif not indexer.within_budget(text):
            warnings.append(f"{rel} is over the {indexer.MAX_LINES}-line / {indexer.MAX_BYTES}-byte budget")
    for warning in warnings:
        print(f"receipts-wiki pre-commit warning: {warning}", file=sys.stderr)
    if problems:
        print("receipts-wiki pre-commit blocked this commit: " + "; ".join(problems) + ".", file=sys.stderr)
        return 1
    return 0


def install_git_hook(home, rw_path):
    """Install the pre-commit check in the memory repository without replacing a hook written by someone else."""
    if not gitlog.is_repo(home):
        print(f"{home} is not the root of a git repository")
        return 1
    hooks_dir = Path(gitlog.git(home, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hooks_dir.is_absolute():
        hooks_dir = Path(home) / hooks_dir
    hook = hooks_dir / "pre-commit"
    if hook.exists() and HOOK_MARK not in hook.read_text(errors="replace"):
        print(f"{hook} already exists and was not written by receipts-wiki, so it was not replaced. "
              f"Add `RECEIPTS_WIKI_HOME=\"$(git rev-parse --show-toplevel)\" python3 {rw_path} precommit || exit 1` to it instead.")
        return 1
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK_SCRIPT.format(mark=HOOK_MARK, fallback=rw_path), encoding="utf-8")
    hook.chmod(0o755)
    print(f"installed {hook}")
    return 0

RELITIGATE = re.compile(r"re-?litigate|don.t revisit|do not revisit|don.t rebuild", re.I)
LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
IGNORED = ("sessions/", "proposals/", ".state/")


def record(home, agent="unknown"):
    """Commit every uncommitted change to memory, AGENTS.md and .gitignore in one commit, credited to agent."""
    if not gitlog.is_repo(home):
        print(f"{home} is not the root of a git repository")
        return 1
    paths = gitlog.dirty_paths(home)
    if gitlog.git(home, "status", "--porcelain", "--", ".gitignore").stdout.strip():
        paths.append(".gitignore")
    changes = turns.changes_for(home, paths, event="external.change")
    committed, detail, extra = turns.record(home, changes, agent)
    if committed:
        print(f"committed {len(changes)} change(s) and {len(extra)} index file(s) as {detail}")
    else:
        print(f"nothing committed ({detail})")
    return 0


def build_index(home, commit=True):
    changed, warnings = indexer.build(home)
    if changed and commit and gitlog.is_repo(home):
        gitlog.commit_paths(home, changed, gitlog.simple_message(
            "memory(general): rebuild indexes", [("index.rebuilt", path) for path in changed], "receipts-wiki"))
    for rel in changed:
        print(f"updated {rel}")
    for warning in warnings:
        print(f"warning: {warning}")
    if not changed:
        print("indexes are up to date")
    return 0


def resolve_note(home, target):
    memory = Path(home) / "memory"
    stem = target[:-3] if target.endswith(".md") else target
    direct = memory / f"{Path(stem).name}.md"
    if direct.exists():
        return f"memory/{direct.name}"
    wanted = gitlog.slug(target)
    for item in indexer.notes(home):
        if gitlog.slug(item["name"]) == wanted:
            return f"memory/{item['file']}"
    return None


def history(home, target, patch=False):
    rel = resolve_note(home, target)
    if not rel:
        print(f"no note matches {target!r}")
        return 1
    args = ["log", "--reverse", "--date=short", "--format=%h %ad %s%n%b"]
    if patch:
        args.append("-p")
    output = gitlog.git(home, *args, "--", rel).stdout.strip()
    print(f"# History of {rel}\n")
    print(output or "(no commits)")
    return 0


def recall(home, query, limit=5):
    words = sorted({w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2})
    if not words:
        print("query too short")
        return 1
    root = Path(home) / "sessions"
    hits = []
    for path in sorted(root.rglob("*.md")) if root.exists() else []:
        fm, body = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        for block in re.split(r"\n(?=## )", "\n" + body):
            block = block.strip()
            if not block.startswith("## "):
                continue
            lowered = block.lower()
            matched = [w for w in words if w in lowered]
            if matched:
                hits.append((len(matched), sum(lowered.count(w) for w in matched), path, fm, block))
    if not hits:
        print(f"no archived conversation matches {query!r}")
        return 0
    hits.sort(key=lambda hit: (-hit[0], -hit[1], str(hit[2])))
    for _, _, path, fm, block in hits[:limit]:
        heading, _, content = block.partition("\n")
        print(f"## {path.relative_to(home)} ({fm.get('title') or 'untitled'}, session {fm.get('session') or '?'})")
        print(heading.lstrip("# ").strip())
        print(_excerpt(content, words))
        print()
    return 0


def _excerpt(text, words, width=400):
    lowered = text.lower()
    positions = [lowered.find(w) for w in words if lowered.find(w) >= 0]
    start = max(0, min(positions) - width // 3) if positions else 0
    snippet = " ".join(text[start:start + width].split())
    return ("..." if start else "") + snippet + ("..." if start + width < len(text) else "")


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _first_commit_date(home, rel):
    lines = gitlog.git(home, "log", "--diff-filter=A", "--format=%ad", "--date=short", "--", rel).stdout.split()
    return _parse_date(lines[-1]) if lines else None


def lint(home, stale_days=90, unread_days=60, today=None):
    home = Path(home)
    today = today or date.today()
    if not home.exists():
        print(f"No memory home at {home}. Run the receipts-wiki setup skill.")
        return 0
    memory = home / "memory"
    problems, warnings, forget = [], [], {}

    if not gitlog.is_repo(home):
        problems.append(f"{home} is not the root of a git repository")
    else:
        if gitlog.git(home, "fsck", "--no-progress").returncode != 0:
            problems.append("git fsck reports problems in the memory history")
        dirty = gitlog.git(home, "status", "--porcelain", "--untracked-files=all", "--", "memory", "AGENTS.md").stdout.strip()
        if dirty:
            warnings.append(f"{len(dirty.splitlines())} memory file(s) have uncommitted changes; they are committed at the end of the writing session's turn, or as external.change at the next catch-up")
        health = state.load_health()
        if health.get("detail"):
            problems.append(f"the last catch-up commit failed at {health.get('at')} (failing since {health.get('since')}): {health['detail']}")
        for data in state.all_sessions():
            failure = data.get("commit_failure")
            if failure and data.get("pending"):
                problems.append(f"session {data['session']} has {len(data['pending'])} uncommitted memory write(s), "
                                f"failing since {failure.get('since')}: {failure.get('detail')}")

    ignore_file = home / ".gitignore"
    ignored = set()
    if ignore_file.exists():
        ignored = {line.strip().rstrip("/") + "/" for line in ignore_file.read_text().splitlines() if line.strip()}
    missing = [entry for entry in IGNORED if entry not in ignored]
    if missing:
        problems.append(".gitignore does not exclude " + ", ".join(missing) + "; archived conversations and state must stay out of git")

    try:
        configured = json.loads(config.claude_settings_path().read_text()).get("autoMemoryDirectory")
    except (OSError, ValueError, AttributeError):
        configured = None
    if configured and Path(configured).expanduser().resolve() != memory.resolve():
        warnings.append(f"Claude Code autoMemoryDirectory is {configured}, not {memory}")

    agents = home / "AGENTS.md"
    if agents.exists():
        raw = agents.read_bytes()
        line_count = raw.count(b"\n")
        if len(raw) > config.AGENTS_BUDGET_BYTES or line_count > config.AGENTS_BUDGET_LINES:
            warnings.append(f"AGENTS.md is {line_count} lines / {len(raw)} bytes, over the {config.AGENTS_BUDGET_LINES}-line / {config.AGENTS_BUDGET_BYTES}-byte budget")
        label = secrets.find_secret(raw.decode("utf-8", errors="replace"))
        if label:
            problems.append(f"AGENTS.md contains a secret value ({label})")

    notes = indexer.notes(home)
    reads = state.last_reads()
    names = {}
    for item in notes:
        rel = f"memory/{item['file']}"
        text, fm = item["text"], item["frontmatter"]
        if not fm:
            problems.append(f"{rel} has no frontmatter")
        else:
            for key, value in (("name", frontmatter.get(fm, "name")), ("description", frontmatter.get(fm, "description")),
                               ("type", frontmatter.get(fm, "metadata.type", "type"))):
                if not value:
                    warnings.append(f"{rel} is missing {key}")
        names.setdefault(item["name"], []).append(rel)
        label = secrets.find_secret(text)
        if label:
            problems.append(f"{rel} contains a secret value ({label})")
        if item["type"] == "project" and not gitlog.receipts_of(text) and not gitlog.INLINE_RECEIPT.search(frontmatter.split(text)[1]):
            warnings.append(f"{rel} is a project note without receipts (no Receipts line, and no commit, file, transaction or id cited in the text)")
        if RELITIGATE.search(text) and not gitlog.REOPEN.search(text):
            warnings.append(f"{rel} says not to revisit a decision but has no 'Reopen if:' line")
        if item["status"] == "retired":
            continue
        verified = _parse_date(frontmatter.get(fm, "last_verified", "metadata.last_verified"))
        if verified and (today - verified).days > stale_days:
            forget.setdefault(rel, []).append(f"last verified {verified} ({(today - verified).days} days ago)")
        last = _parse_date(reads.get(rel)) or _first_commit_date(home, rel)
        if last and (today - last).days > unread_days:
            forget.setdefault(rel, []).append(f"not read by any session since {last}")
    for name, rels in names.items():
        if len(rels) > 1:
            warnings.append(f"duplicate name {name!r}: " + ", ".join(rels))

    link_sources = [memory / "MEMORY.md", *sorted(memory.glob("index-*.md")), *(memory / item["file"] for item in notes)]
    for path in link_sources:
        if not path.exists():
            continue
        for target in LINK.findall(path.read_text(encoding="utf-8", errors="replace")):
            if not target.startswith(("http://", "https://")) and not (path.parent / target).exists():
                problems.append(f"memory/{path.name} links to missing {target}")
    for path in [*sorted(memory.glob("index-*.md")), memory / "MEMORY.md"]:
        if path.exists():
            size = path.stat().st_size
            lines = path.read_text(encoding="utf-8", errors="replace").count("\n")
            if size > indexer.MAX_BYTES or lines > indexer.MAX_LINES:
                warnings.append(f"memory/{path.name} is {lines} lines / {size} bytes, over the {indexer.MAX_LINES}-line / {indexer.MAX_BYTES}-byte budget")

    pending = sorted((home / "proposals").glob("*.md")) if (home / "proposals").exists() else []

    print(f"# receipts-wiki lint: {home}\n")
    print("Report only; nothing was changed.\n")
    for title, items in (("Problems", problems), ("Warnings", warnings)):
        print(f"## {title} ({len(items)})\n")
        print("\n".join(f"- {item}" for item in items) if items else "None.")
        print()
    print(f"## Forgetting candidates ({len(forget)}), retire only with the owner's approval\n")
    print("\n".join(f"- {rel}: {'; '.join(reasons)}" for rel, reasons in sorted(forget.items())) if forget else "None.")
    print()
    print(f"## Lesson proposals waiting ({len(pending)})\n")
    print("\n".join(f"- {path.relative_to(home)}" for path in pending) if pending else "None.")
    return 0
