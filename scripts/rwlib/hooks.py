"""Claude Code hook handlers.

During a turn the hooks stay quiet and cheap: reads and writes are noted, a write is blocked only when
something is wrong, and a new note that closely matches an existing one gets a single hint. Commits,
index rebuilds and archiving happen at the end of the turn and never produce output for the agent.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

from . import archive, config, gitlog, indexer, related, secrets, state, turns

REVISION = re.compile(r"^(HEAD|ORIG_HEAD|FETCH_HEAD|@)([~^]\d*)*$|^[0-9a-f]{7,40}([~^]\d*)*$")
RESET_MODES = {"--hard", "--soft", "--mixed", "--merge", "--keep"}
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")"}


def read_payload():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _emit(obj):
    sys.stdout.write(json.dumps(obj))


def _context(event, text):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def _tool_input(payload):
    value = payload.get("tool_input")
    return value if isinstance(value, dict) else {}


def _proposed_text(tool_input):
    """Full text the tool is about to write (Write) or insert (Edit, MultiEdit)."""
    if "content" in tool_input:
        return tool_input.get("content") or ""
    if "new_string" in tool_input:
        return tool_input.get("new_string") or ""
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        return "\n".join(str(e.get("new_string", "")) for e in edits if isinstance(e, dict))
    return ""


def _added_lines(path, proposed):
    """Lines of the proposed text that the file does not already contain."""
    try:
        existing = set(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return proposed
    return "\n".join(line for line in proposed.splitlines() if line not in existing)


def _proposals_waiting(home):
    folder = home / "proposals"
    return sorted(folder.glob("*.md")) if folder.exists() else []


def hook_read(payload):
    rel = config.tracked(_tool_input(payload).get("file_path"))
    if not rel:
        return
    digest = state.content_hash(config.home() / rel, rel)
    if digest is None:
        return
    session = payload.get("session_id")
    data = state.load(session)
    data["reads"][rel] = digest
    state.save(session, data)
    state.touch_read(rel)


def hook_gate(payload):
    tool_input = _tool_input(payload)
    rel = config.tracked(tool_input.get("file_path"))
    if not rel:
        return
    path = config.home() / rel
    proposed = _proposed_text(tool_input)
    added = _added_lines(path, proposed)

    reasons = []
    if indexer.is_index_file(rel) and (not path.exists() or indexer.is_generated_index(config.home(), rel)):
        reasons.append("index files are generated from note frontmatter; change the note's area, name or description instead")
    secret = secrets.find_secret(proposed)
    if secret:
        reasons.append(f"it contains a secret value ({secret}); store the secret's name or location, never its value")
    tag = secrets.find_injected_tag(added)
    if tag:
        reasons.append(f"it contains injected context (<{tag}>); remove tool or system text before saving")
    phrase = secrets.find_relative_date(added)
    if phrase:
        reasons.append(f"it uses a relative date ({phrase!r}); write an absolute date such as 2026-09-14")
    current = state.content_hash(path, rel)
    if current is not None:
        seen = state.load(payload.get("session_id"))["reads"].get(rel)
        if seen and seen != current:
            reasons.append("the file changed after this session read it; read it again and decide whether your change still applies")

    if reasons:
        _emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"receipts-wiki blocked this write to {rel}: " + "; ".join(reasons) + ".",
        }})


def _rewrites_history(sub, args):
    """True when this git subcommand removes or replaces commits or moves a ref backwards."""
    if sub in ("rebase", "filter-branch", "filter-repo", "update-ref", "replace"):
        return True
    if sub == "reset":
        return any(arg in RESET_MODES or REVISION.match(arg) for arg in args)
    if sub == "commit":
        return "--amend" in args
    if sub == "push":
        return any(arg in ("-f", "--force") or arg.startswith(("--force-with-lease", "--force-if-includes")) or arg.startswith("+") for arg in args)
    if sub == "reflog":
        return bool(args) and args[0] in ("expire", "delete")
    if sub == "gc":
        return any(arg.startswith("--prune") for arg in args)
    if sub == "branch":
        return any(arg in ("-f", "--force", "-D", "-d", "--delete", "-M", "-m", "--move") for arg in args)
    return False


def _git_calls(command, cwd):
    """Yield (repository directory, subcommand, arguments) for each git invocation in a shell command."""
    current = cwd
    for line in str(command).splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            tokens = line.split()
        segment = []
        for token in tokens + [";"]:
            if token not in SEPARATORS:
                segment.append(token)
                continue
            while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
                segment.pop(0)
            if segment and segment[0] == "cd" and len(segment) > 1:
                current = os.path.join(current or "", os.path.expanduser(segment[1]))
            elif segment and os.path.basename(segment[0]) == "git":
                repo, index = current, 1
                while index < len(segment) and segment[index].startswith("-"):
                    option = segment[index]
                    if option == "-C" and index + 1 < len(segment):
                        repo = os.path.join(repo or "", os.path.expanduser(segment[index + 1]))
                        index += 2
                        continue
                    if option in ("--git-dir", "--work-tree") and index + 1 < len(segment):
                        target = os.path.expanduser(segment[index + 1])
                        repo = os.path.dirname(target.rstrip("/")) if option == "--git-dir" else target
                        index += 2
                        continue
                    if option.startswith("--git-dir="):
                        repo = os.path.dirname(os.path.expanduser(option.split("=", 1)[1]).rstrip("/"))
                    elif option.startswith("--work-tree="):
                        repo = os.path.expanduser(option.split("=", 1)[1])
                    elif option == "-c" and index + 1 < len(segment):
                        index += 1
                    index += 1
                if index < len(segment) and repo:
                    yield repo, segment[index], segment[index + 1:]
            segment = []


def hook_history(payload):
    """PreToolUse on Bash: refuse git commands that rewrite the memory repository's history."""
    command = _tool_input(payload).get("command") or ""
    if "git" not in command:
        return
    home = config.home()
    for repo, sub, args in _git_calls(command, payload.get("cwd")):
        try:
            target = Path(repo).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if (target == home or home in target.parents) and _rewrites_history(sub, args):
            _emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"receipts-wiki blocked `git {sub}` in the memory repository {home}: memory history is append-only, "
                    "so commits are never removed or replaced. Correct forward instead: edit the note and add a Supersedes line, "
                    "or use `git revert <commit>`, which records the undo as a new commit. "
                    "If the user still wants to rewrite history, tell them they can run the command themselves outside the agent."),
            }})
            return


def hook_capture(payload):
    rel = config.tracked(_tool_input(payload).get("file_path"))
    home = config.home()
    if not rel or indexer.is_generated_index(home, rel):
        return
    path = home / rel
    if not path.exists():
        return
    session = payload.get("session_id")
    data = state.load(session)
    pending = data["pending"]
    is_new = rel not in pending and gitlog.head_content(home, rel) is None
    previous = pending.get(rel) or {}
    pending[rel] = {
        "turn": payload.get("prompt_id") or previous.get("turn"),
        "cwd": payload.get("cwd") or previous.get("cwd"),
        "transcript": payload.get("transcript_path") or previous.get("transcript"),
        "at": state.now_iso(),
    }
    data["reads"][rel] = state.content_hash(path, rel)
    state.save(session, data)
    state.touch_read(rel)

    if is_new and indexer.is_note(rel):
        strong, _ = related.candidates(home, rel, path.read_text(encoding="utf-8", errors="replace"))
        if strong:
            _emit(_context("PostToolUse", "Possible duplicate or contradiction: " + ", ".join(strong)
                           + ". If this note changes what they say, update them or add a Supersedes line; otherwise leave them unchanged."))


def _end_turn(payload):
    home = config.home()
    if not home.exists():
        return
    session = payload.get("session_id")
    data = state.load(session)
    if data["pending"]:
        turns.flush_session(home, session, data, turn=payload.get("prompt_id"),
                            cwd=payload.get("cwd"), transcript=payload.get("transcript_path"))
    transcript_path = payload.get("transcript_path")
    if transcript_path:
        messages = archive.append(home, session, transcript_path, payload.get("cwd"), data)
        archive.write_proposals(home, session, archive.lesson_candidates(messages), data)
    state.save(session, data)
    failure = data.get("commit_failure")
    if failure and data.get("pending"):
        _emit({"systemMessage": _failure_message(home, len(data["pending"]), failure)})


def _failure_message(home, count, failure):
    tries = f", {failure['count']} attempts since {failure['since']}" if int(failure.get("count") or 0) > 1 else ""
    detail = str(failure.get("detail") or "").rstrip()
    if detail and detail[-1] not in ".!?":
        detail += "."
    return (f"receipts-wiki could not commit {count} memory file(s) in {home}{tries}: {detail} "
            "The changes are on disk and are retried every turn; run `rw.py lint` to see them.")


def hook_stop(payload):
    """End of a turn (Stop, StopFailure). Silent; never asks the agent to continue."""
    if payload.get("stop_hook_active") or payload.get("agent_id"):
        return
    _end_turn(payload)


def hook_session_end(payload):
    _end_turn(payload)


def hook_prompt(payload):
    """New user prompt: commit an interrupted previous turn, catch up now and then, mention proposals once a day.

    A prompt can also arrive inside a running turn, for example when a background task finishes; it then
    carries the running turn's prompt_id, and that turn's writes stay pending until its Stop.
    """
    home = config.home()
    if not home.exists():
        return
    session = payload.get("session_id")
    data = state.load(session)
    if data["pending"]:
        turns.flush_session(home, session, data, cwd=payload.get("cwd"), transcript=payload.get("transcript_path"),
                            recovered=True, skip_turn=payload.get("prompt_id"))
    if state.seconds_since(data.get("swept_at")) > config.SWEEP_INTERVAL_SECONDS:
        state.save(session, data)
        turns.sweep(home, current_session=session)
        data["swept_at"] = state.now_iso()
    note = None
    waiting = _proposals_waiting(home)
    if waiting and state.seconds_since(data.get("proposals_noticed_at")) > config.PROPOSAL_NOTICE_SECONDS:
        note = f"{len(waiting)} lesson proposal file(s) are waiting in {home / 'proposals'}. Mention this to the user once; they can review them with the receipts-wiki lint-review skill."
        data["proposals_noticed_at"] = state.now_iso()
    state.save(session, data)
    if note:
        _emit(_context("UserPromptSubmit", note))


def hook_session_start(payload):
    home = config.home()
    session = payload.get("session_id")
    parts, notices = [], []
    agents = home / "AGENTS.md"
    if agents.exists():
        raw = agents.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        if len(raw) > config.AGENTS_BUDGET_BYTES:
            cut = raw[: config.AGENTS_BUDGET_BYTES].decode("utf-8", errors="ignore")
            if "\n" in cut:
                cut = cut[: cut.rfind("\n")]
            text = cut + f"\n\n[receipts-wiki loaded only the first {config.AGENTS_BUDGET_BYTES} of {len(raw)} bytes of AGENTS.md; shorten it.]"
        parts.append(f"Rules from {agents}, loaded by receipts-wiki:\n\n{text}")

    if not home.exists():
        parts.append(f"receipts-wiki is installed but there is no memory home at {home}. If the user wants shared memory, suggest the receipts-wiki setup skill.")
    else:
        data = state.load(session)
        if not gitlog.is_repo(home):
            parts.append(f"receipts-wiki: {home} is not the root of a git repository, so memory changes are not recorded. Suggest the receipts-wiki setup skill.")
        else:
            if data["pending"]:
                turns.flush_session(home, session, data, recovered=True)
            state.save(session, data)
            turns.sweep(home, current_session=session)
            failure = data.get("commit_failure")
            data = state.load(session)
            data["swept_at"] = state.now_iso()
            if failure and data.get("pending"):
                notices.append(_failure_message(home, len(data["pending"]), failure))
            health = state.load_health()
            if health.get("detail"):
                notices.append(f"receipts-wiki could not commit memory changes made outside a session turn in {home} "
                               f"(last attempt {health.get('at')}): {health['detail']}")
            stale = turns.stale_uncommitted(home)
            if stale:
                shown = ", ".join(stale[:3]) + (f" and {len(stale) - 3} more" if len(stale) > 3 else "")
                notices.append(f"receipts-wiki: {len(stale)} memory file(s) have been uncommitted for over "
                               f"{turns.STALE_UNCOMMITTED_MINUTES} minutes: {shown}. Run `rw.py lint` for details.")
        waiting = _proposals_waiting(home)
        if waiting:
            parts.append(f"{len(waiting)} lesson proposal file(s) are waiting in {home / 'proposals'}. Mention this to the user once; they can review them with the receipts-wiki lint-review skill.")
            data["proposals_noticed_at"] = state.now_iso()
        state.save(session, data)

    output = _context("SessionStart", "\n\n".join(parts)) if parts else {}
    if notices:
        output["systemMessage"] = " ".join(notices)
    if output:
        _emit(output)
