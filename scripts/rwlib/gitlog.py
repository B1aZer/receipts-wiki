"""Git as the memory log: event detection, turn commit messages (docs/COMMIT-SPEC.md) and commits."""
import os
import re
import subprocess
import time
from pathlib import Path

from . import frontmatter

VERBS = {
    "fact.added": "add",
    "fact.updated": "update",
    "fact.superseded": "supersede",
    "fact.verified": "verify",
    "fact.retired": "retire",
    "fact.removed": "remove",
    "rules.changed": "update",
    "external.change": "record",
    "proposal.accepted": "accept",
    "index.rebuilt": "rebuild",
}
SPECIAL = {"memory/MEMORY.md": "MEMORY.md", "AGENTS.md": "AGENTS.md"}

SUPERSEDES = re.compile(r"^\s*Supersedes \((\d{4}-\d{2}-\d{2})\):\s*(.+?)\s*$", re.M)
WHY = re.compile(r"^\s*(?:\*\*)?Why:(?:\*\*)?\s*(.+?)\s*$", re.M)
REOPEN = re.compile(r"^\s*(?:\*\*)?Reopen if:(?:\*\*)?\s*(.+?)\s*$", re.M)
RECEIPTS_LINE = re.compile(r"^\s*(?:\*\*)?Receipts:(?:\*\*)?\s*(.+?)\s*$", re.M)
LAST_VERIFIED = re.compile(r"^\s*last_verified:.*$", re.M)

ACTION_LIMIT = 200
SUBJECT_LIMIT = 72
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")


def git(home, *args, stdin=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(
        ["git", "-C", str(home), *args],
        input=stdin, capture_output=True, text=True, env=env, check=False,
    )


def is_repo(home):
    """True only when the memory home is itself the root of a git repository."""
    result = git(home, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return False
    return Path(result.stdout.strip()).resolve() == Path(home).resolve()


def operation_in_progress(home):
    """A merge, rebase, cherry-pick or revert is under way; commits wait until it is finished."""
    result = git(home, "rev-parse", "--git-dir")
    if result.returncode != 0:
        return False
    gitdir = Path(result.stdout.strip())
    if not gitdir.is_absolute():
        gitdir = Path(home) / gitdir
    return any((gitdir / name).exists() for name in IN_PROGRESS)


def has_head(home):
    return git(home, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


def head_content(home, rel):
    result = git(home, "show", f"HEAD:{rel}")
    return result.stdout if result.returncode == 0 else None


def tracked(home):
    return {line for line in git(home, "ls-files", "--", "memory", "AGENTS.md").stdout.splitlines() if line}


def dirty_paths(home):
    """Memory paths whose working copy differs from HEAD, including untracked files."""
    names = set()
    if has_head(home):
        names.update(git(home, "diff", "HEAD", "--name-only", "--", "memory", "AGENTS.md").stdout.splitlines())
    else:
        names.update(git(home, "ls-files", "--", "memory", "AGENTS.md").stdout.splitlines())
    names.update(git(home, "ls-files", "--others", "--exclude-standard", "--", "memory", "AGENTS.md").stdout.splitlines())
    return sorted(name for name in names if name)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48] or "note"


def derive_event(rel, old, new):
    if rel == "AGENTS.md":
        return "rules.changed"
    if new is None:
        return "fact.removed"
    if old is None:
        new_fm, _ = frontmatter.split(new)
        if frontmatter.get(new_fm, "source", "metadata.source") == "proposal":
            return "proposal.accepted"
        return "fact.added"
    if len(SUPERSEDES.findall(new)) > len(SUPERSEDES.findall(old)):
        return "fact.superseded"
    old_fm, _ = frontmatter.split(old)
    new_fm, _ = frontmatter.split(new)
    old_status = frontmatter.get(old_fm, "status", "metadata.status")
    new_status = frontmatter.get(new_fm, "status", "metadata.status")
    if new_status == "retired" and old_status != "retired":
        return "fact.retired"
    old_verified = frontmatter.get(old_fm, "last_verified", "metadata.last_verified")
    new_verified = frontmatter.get(new_fm, "last_verified", "metadata.last_verified")
    if old_verified != new_verified and LAST_VERIFIED.sub("", old) == LAST_VERIFIED.sub("", new):
        return "fact.verified"
    return "fact.updated"


def receipts_of(text):
    fm, body = frontmatter.split(text or "")
    found = []
    listed = frontmatter.get(fm, "receipts", "metadata.receipts", default=[])
    found.extend(listed if isinstance(listed, list) else [listed])
    for match in RECEIPTS_LINE.finditer(body):
        found.extend(part.strip().strip("`") for part in match.group(1).split(","))
    unique = []
    for item in found:
        item = str(item).strip()
        if item and item not in unique:
            unique.append(item)
    return unique


def _new_matches(pattern, old, new):
    before = {m.group(0).strip() for m in pattern.finditer(old or "")}
    return [m for m in pattern.finditer(new or "") if m.group(0).strip() not in before]


def _cap(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _trailer_block(trailers):
    return "\n".join(f"{key}: {' '.join(str(value).split())}" for key, value in trailers)


def _label(change):
    rel = change["rel"]
    if rel in SPECIAL:
        return SPECIAL[rel], None
    fm, _ = frontmatter.split(change.get("new") or change.get("old") or "")
    return slug(frontmatter.get(fm, "name") or Path(rel).stem), slug(frontmatter.get(fm, "metadata.area", "area") or "general")


def action_lines(change, name):
    old, new = change.get("old"), change.get("new")
    if new is None:
        return []
    lines = []
    for match in _new_matches(SUPERSEDES, old, new):
        claim, _, evidence = match.group(2).partition(". ")
        line = f"rejected({name}): {claim.strip().rstrip('.')}"
        if evidence.strip():
            line += f"; {evidence.strip()}"
        lines.append(line)
    for match in _new_matches(WHY, old, new):
        lines.append(f"intent({name}): {match.group(1)}")
    for match in _new_matches(REOPEN, old, new):
        lines.append(f"constraint({name}): reopen if {match.group(1)}")
    return [_cap(line, ACTION_LIMIT) for line in lines]


def _subject(prefix, parts):
    for shown in range(len(parts), 0, -1):
        rest = len(parts) - shown
        text = prefix + ", ".join(parts[:shown]) + (f" and {rest} more" if rest else "")
        if len(text) <= SUBJECT_LIMIT:
            return text
    return _cap(prefix + parts[0], SUBJECT_LIMIT)


def turn_message(changes, extra_paths, agent, session=None, turn=None, cwd=None, transcript=None, recovered=False):
    """One commit message for everything a turn changed. changes: dicts with rel, event, old, new."""
    labelled = [(change, *_label(change)) for change in changes]
    notes = [item for item in labelled if item[0]["rel"] not in SPECIAL]
    scopes = {scope for _, _, scope in notes}
    scope = next(iter(scopes)) if len(scopes) == 1 else "general"
    kind = "rules" if changes and all(c["rel"] == "AGENTS.md" for c in changes) else "memory"
    ordered = notes + [item for item in labelled if item[0]["rel"] in SPECIAL]
    parts = [f"{VERBS.get(change['event'], 'update')} {name}" for change, name, _ in ordered] or ["rebuild indexes"]
    subject = _subject(f"{kind}({scope}): ", parts)

    actions = []
    receipts = []
    for change, name, _ in labelled:
        actions.extend(action_lines(change, name))
        for receipt in receipts_of(change.get("new")):
            if receipt not in receipts:
                receipts.append(receipt)

    trailers = [("Change", f"{change['event']} {change['rel']}") for change in changes]
    trailers += [("Change", f"index.rebuilt {path}") for path in extra_paths]
    trailers.append(("Agent", agent))
    for key, value in (("Session", session), ("Turn", turn), ("Cwd", cwd), ("Transcript", transcript)):
        if value:
            trailers.append((key, value))
    if receipts:
        trailers.append(("Receipts", ", ".join(receipts)))
    if recovered:
        trailers.append(("Recovered", "true"))

    message = [subject]
    if actions:
        message.append("\n".join(actions))
    message.append(_trailer_block(trailers))
    return "\n\n".join(message) + "\n"


def simple_message(subject, change_lines, agent, session=None):
    trailers = [("Change", f"{event} {rel}") for event, rel in change_lines] + [("Agent", agent)]
    if session:
        trailers.append(("Session", session))
    return _cap(subject, SUBJECT_LIMIT) + "\n\n" + _trailer_block(trailers) + "\n"


def commit_paths(home, rels, message, attempts=6):
    """Commit exactly these paths, leaving anything else staged or dirty alone. Returns (committed, detail)."""
    added = git(home, "add", "-A", "--", *rels)
    if added.returncode != 0:
        return False, added.stderr.strip()
    if git(home, "diff", "--cached", "--quiet", "--", *rels).returncode == 0:
        return False, "no change"
    detail = ""
    for attempt in range(attempts):
        result = git(home, "commit", "-q", "--only", "-F", "-", "--", *rels, stdin=message)
        if result.returncode == 0:
            return True, git(home, "rev-parse", "--short", "HEAD").stdout.strip()
        detail = (result.stderr or result.stdout).strip()
        if "index.lock" not in detail and "cannot lock ref" not in detail:
            break
        time.sleep(0.25 * (attempt + 1))
    return False, detail
