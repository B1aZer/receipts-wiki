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
import time
from pathlib import Path

from . import (actions, archive, checks, config, frontmatter, gitlog, indexer, related, secrets,
               state, topics, turns, warm, watch)

NO_HOME = ("receipts-wiki is installed but there is no memory home at {home}. "
           "If the user wants shared memory, suggest the receipts-wiki setup skill.")
NOT_REPO = ("receipts-wiki: {home} is not the root of a git repository, so memory changes "
            "are not recorded. Suggest the receipts-wiki setup skill.")

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
        _note_new_doc(payload, tool_input.get("file_path"))
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
            reasons.append(f"the file changed after this session read it{_who_changed(rel)}; read it again "
                           "and decide whether your change still applies")

    if reasons:
        _emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"receipts-wiki blocked this write to {rel}: " + "; ".join(reasons) + ".",
        }})


def _who_changed(rel):
    """Who the change belongs to, as a phrase for the write-gate rejection, or "" when unknown.

    Only a COMMITTED change can be attributed. If the file on disk differs from HEAD the change came
    from a session that has not committed yet, and naming the previous committer would blame the wrong
    session -- so that case says so instead of guessing. The git author cannot be used either: every
    session commits under the same identity, which is why the Session trailer exists.
    """
    home = config.home()
    try:
        on_disk = (Path(home) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    head = gitlog.head_content(home, rel)
    if head is None or head != on_disk:
        return " by a session that has not committed it yet"
    session = gitlog.last_session(home, rel)
    return f" in a commit from session {session[:8]}" if session else ""


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


SCRIPT_TOOL = re.compile(r"\b(python3?|node|ruby|perl|deno|bun|php)\b")
SCRIPT_WRITE = re.compile(r"open\([^)]*['\"][wax]\+?b?['\"]|\bmode\s*=\s*['\"][wax]|write_text|write_bytes|writeFileSync|writeFile|appendFile|"
                          r"shutil\.|os\.(remove|rename|replace|unlink)|\.unlink\(|File\.write|fs\.rm")


def _memory_markers(home):
    markers = {str(home)}
    raw = os.environ.get("RECEIPTS_WIKI_HOME")
    if raw:
        markers.add(raw.rstrip("/"))
    if str(home).startswith("/private/"):
        markers.add(str(home)[len("/private"):])
    try:
        inside = home.relative_to(Path.home())
        markers |= {f"~/{inside}", f"$HOME/{inside}", f"${{HOME}}/{inside}"}
    except ValueError:
        pass
    return markers


def _home_prefixes(home):
    """Every absolute spelling of the memory home a resolved path might legitimately carry."""
    out = set()
    for candidate in (str(home), str(Path(home).expanduser())):
        out.add(candidate.rstrip("/"))
        if candidate.startswith("/private/"):
            out.add(candidate[len("/private"):].rstrip("/"))
        else:
            out.add(("/private" + candidate).rstrip("/"))
    return out


def _lands_in(target, here, prefixes):
    """Does this write target resolve to a path inside the memory home?

    Resolved against `here` -- the directory the command will actually run in -- so a relative target
    after a `cd` is judged by where it LANDS and not by how it is spelled. No filesystem access: the
    target usually does not exist yet, and a gate must not depend on whether it does.
    """
    text = os.path.expandvars(os.path.expanduser(target.strip().strip("'\"")))
    if not text or text.startswith("$"):
        return False    # a path held in a shell variable: unresolvable from the text, see the docstring
    if not os.path.isabs(text):
        text = os.path.join(here or "", text)
    text = os.path.normpath(text).rstrip("/")
    return any(text == p or text.startswith(p + os.sep) for p in prefixes)


# `cd`/`pushd` move the directory for everything after them; `env -C` only for its own command.
_REDIRECT = re.compile(r"(?<![<0-9&])>{1,2}\|?\s*(?:['\"]([^'\"]+)['\"]|([^\s'\";|&()<>]+))")


def _shell_write_reason(command, home, cwd=None):
    """How a shell command writes into the memory home, or None.

    ⚠️ **This gate judges where a write LANDS, not how the path is spelled**, which is the whole
    difference between it working and looking like it works. Until 2026-10-15 it required the home's
    path to appear in the command text and then tested each write target as written -- so
    `cd <home>/memory && sed -i ... note.md` passed: the marker was there, in the `cd`, and the target
    `note.md` matched nothing. Probed: `cd`, `cd` via `~`, two-hop `cd`, `pushd`, a subshell and
    `env -C` all defeated it, for redirects, `tee`, `cp`, `mv`, `sed -i` and `truncate` alike.
    ⛔ **It stopped the careless path and missed the convenient one** -- a session reaching for a shell
    edit to save a step is exactly the session that would `cd` first. (Found by `unrekt-84`, relayed by
    `unrekt-79`. The relayed mechanism was "the path is not in the command"; it is in the command, and
    the fix follows from the real one: resolve the target, do not search the text.)

    ⚠️ **What a text-reading gate cannot do, stated rather than papered over.** A path computed at
    runtime -- held in a variable, read from a file, built by a script -- is not visible here and no
    amount of pattern work makes it visible. `[[feedback-proxy-is-not-the-property]]`: the command text
    is a proxy for the write, and the two come apart whenever the path is not literal. So this is a
    courtesy that redirects a session to Write/Edit, and **the detector that cannot be evaded is the
    catch-up pass**, which sees the file differ from `HEAD` at the next turn boundary and reports it as
    `external.change` whatever made it. Harden this; rely on that.

    Over-blocks rather than under-blocks in two known places, deliberately: a `cd` inside a subshell is
    treated as lasting for the rest of the command, and a script whose own text mentions a write is
    judged by that text. A session told to use Write/Edit has lost one step; a missed write to memory is
    an unrecorded change to the thing the project exists to keep honest.
    """
    prefixes = _home_prefixes(home)
    markers = _memory_markers(home)
    here = cwd or os.getcwd()
    script_cwd_inside = False
    for raw in re.split(r"&&|\|\||[;|\n]", command):
        segment = raw.strip().lstrip("(").rstrip(")").strip()
        if not segment:
            continue
        words = [w for w in segment.split() if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
        if not words:
            continue
        tool = os.path.basename(words[0])
        if tool in ("cd", "pushd") and len(words) > 1:
            moved = os.path.expandvars(os.path.expanduser(words[1].strip("'\"")))
            here = os.path.normpath(moved if os.path.isabs(moved) else os.path.join(here, moved))
            continue
        # `env -C <dir> cmd ...` runs one command elsewhere; judge that command from there.
        local = here
        while tool == "env" and len(words) > 2:
            if words[1] == "-C":
                local = os.path.normpath(os.path.join(local, os.path.expanduser(words[2].strip("'\""))))
                words = words[3:]
            elif words[1].startswith("-C"):
                local = os.path.normpath(os.path.join(local, os.path.expanduser(words[1][2:].strip("'\""))))
                words = words[2:]
            else:
                break
            tool = os.path.basename(words[0]) if words else ""
        if any(_lands_in(m.group(1) or m.group(2) or "", local, prefixes) for m in _REDIRECT.finditer(segment)):
            return "redirects output into a file"
        for match in re.finditer(r"\btee\b([^;|&\n]*)", segment):
            if any(_lands_in(word, local, prefixes) for word in match.group(1).split()):
                return "writes a file with tee"
        if tool in ("sed", "perl") and re.search(r"\s-[a-zA-Z]*i", segment):
            if any(_lands_in(word, local, prefixes) for word in words[1:]):
                return "edits a file in place"
        if tool in ("rm", "mv", "touch", "truncate", "unlink", "rmdir", "shred", "chmod", "chown"):
            if any(_lands_in(word, local, prefixes) for word in words[1:] if not word.startswith("-")):
                return f"runs {tool} on it"
        if tool in ("cp", "rsync", "install", "ln") and len(words) > 1:
            if _lands_in(words[-1], local, prefixes):
                return f"copies into it with {tool}"
        if tool == "dd":
            # Read from the RAW segment: dd's operands are `if=`/`of=`, which the env-assignment filter
            # above strips as though they were variable assignments. That is why dd passed the first
            # version of this fix, absolute path and all -- the branch was there and could never fire.
            for word in segment.split():
                if word.startswith("of=") and _lands_in(word[3:], local, prefixes):
                    return "writes a file with dd"
        if SCRIPT_TOOL.search(segment) and _lands_in(".", local, prefixes):
            script_cwd_inside = True
    # A script's own writes are invisible here, so two proxies, each labelled as one: it runs FROM inside
    # the home (its relative writes land there), or it names the home and a write in the same breath.
    if SCRIPT_WRITE.search(command) and (script_cwd_inside
                                         or (SCRIPT_TOOL.search(command)
                                             and any(marker in command for marker in markers))):
        return "runs a script that writes files"
    return None


def hook_shell(payload):
    """PreToolUse on Bash: refuse shell commands that write into the memory home, and point to Write or Edit."""
    command = _tool_input(payload).get("command") or ""
    home = config.home()
    how = _shell_write_reason(command, home, cwd=payload.get("cwd"))
    if how:
        _emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"receipts-wiki blocked this shell command: it {how} in the memory home {home}. Change memory files with "
                "the Write or Edit tool, so the write gate checks the change and it is credited to this turn. "
                "Reading memory with shell commands is fine."),
        }})


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


def hook_action(payload):
    """PostToolUse on any tool that changes something: record the deed, never block, never speak.

    Separate from hook_capture, which only tracks memory writes for the commit. This records every
    mutating call anywhere, because the question it answers is "what did this turn actually do".
    """
    home = config.home()
    if home.exists():
        actions.append(home, payload.get("session_id"), payload)


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

    if is_new and indexer.is_note(rel) and config.attended():
        text = path.read_text(encoding="utf-8", errors="replace")
        strong, _ = related.candidates(home, rel, text)
        matches = list(dict.fromkeys(strong + topics.same_topic(home, rel, text)))
        if matches:
            _emit(_context("PostToolUse", "Existing notes on the same topic: " + ", ".join(matches)
                           + ". Read them. If this note repeats one, put the content in that note and retire this one; "
                           "if it changes what one says, update that note with a Supersedes line."))


def _note_new_doc(payload, file_path):
    """Before a Write creates a markdown file outside memory, remember it for the end-of-turn check."""
    if payload.get("tool_name") != "Write" or not file_path or not config.attended():
        return
    home = config.home()
    if not home.exists() or Path(file_path).exists() or not checks.is_doc_candidate(file_path, home):
        return
    session = payload.get("session_id")
    data = state.load(session)
    docs = data.setdefault("new_docs", [])
    if file_path not in docs:
        docs.append(file_path)
        state.save(session, data)


def _end_turn(payload):
    home = config.home()
    if not home.exists():
        return
    session = payload.get("session_id")
    data = state.load(session)
    shell_written = turns.credit_shell_writes(home, session, data, payload.get("prompt_id"))
    if shell_written:
        data.setdefault("agent_notices", []).append(_shell_write_notice(home, shell_written))
    if data["pending"]:
        written = list(data["pending"])
        turns.flush_session(home, session, data, turn=payload.get("prompt_id"),
                            cwd=payload.get("cwd"), transcript=payload.get("transcript_path"))
        if config.attended():
            data.setdefault("agent_notices", []).extend(f"receipts-wiki: {notice}" for notice in checks.turn_notices(home, written))
    docs = data.pop("new_docs", None) or []
    if docs and config.attended():
        unnamed = checks.unnamed_docs(home, docs)
        if unnamed:
            data.setdefault("agent_notices", []).append("receipts-wiki: " + checks.docs_notice(unnamed))
    data["turn_stopped"] = time.time()
    transcript_path = payload.get("transcript_path")
    if transcript_path and config.attended():
        archive.append(home, session, transcript_path, payload.get("cwd"), data)
    state.save(session, data)
    failure = data.get("commit_failure")
    if failure and data.get("pending"):
        _emit({"systemMessage": _failure_message(home, len(data["pending"]), failure)})


def _shell_write_notice(home, rels):
    """What the write gate would have said about files changed through the shell during the last turn."""
    issues = []
    for rel in rels:
        try:
            text = (Path(home) / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        old = gitlog.head_content(home, rel) or ""
        added = "\n".join(line for line in text.splitlines() if line not in set(old.splitlines()))
        label = secrets.find_secret(text)
        if label:
            issues.append(f"{rel} contains a secret value ({label})")
        tag = secrets.find_injected_tag(added)
        if tag:
            issues.append(f"{rel} contains injected context (<{tag}>)")
        phrase = secrets.find_relative_date(added)
        if phrase:
            issues.append(f"{rel} uses a relative date ({phrase!r})")
        if indexer.is_note(rel):
            fm, _ = frontmatter.split(text)
            if not fm or not frontmatter.get(fm, "description"):
                issues.append(f"{rel} is missing a frontmatter description")
    found = f" The write gate would have flagged: {'; '.join(issues)}." if issues else ""
    return (f"receipts-wiki: in your last turn you changed {', '.join(rels)} with a shell command instead of Write or Edit. "
            f"It was recorded for that turn, but the write gate did not check it.{found} Use Write or Edit for memory files.")


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
    """New user prompt: commit an interrupted previous turn, catch up now and then, pass on notices for the agent.

    A prompt can also arrive inside a running turn, for example when a background task finishes; it then
    carries the running turn's prompt_id, and that turn's writes stay pending until its Stop.
    """
    home = config.home()
    if not home.exists():
        return
    session = payload.get("session_id")
    data = state.load(session)
    if payload.get("prompt_id") != data.get("turn_id") or not data.get("turn_started"):
        data["turn_id"] = payload.get("prompt_id")
        data["turn_started"] = time.time()
    if data["pending"]:
        turns.flush_session(home, session, data, cwd=payload.get("cwd"), transcript=payload.get("transcript_path"),
                            recovered=True, skip_turn=payload.get("prompt_id"))
    if state.seconds_since(data.get("swept_at")) > config.SWEEP_INTERVAL_SECONDS:
        state.save(session, data)
        turns.sweep(home, current_session=session)
        data["swept_at"] = state.now_iso()
    notes = data.pop("agent_notices", None) or []
    if config.attended():
        elsewhere = watch.notice(home, session, data)
        if elsewhere:
            notes.append(elsewhere)
        # Asked here rather than only at session start, because the session-start answer is the one
        # answer that cannot be informative: the newer copy does not exist yet when it runs. First
        # sight records the installed commit and says nothing, exactly as the watch offset does, so a
        # session never opens with a notice about an install it has always been running.
        stale = config.superseded(seen=data.get("install"))
        if stale:
            notes.append(stale)
        if not data.get("install"):
            data["install"] = config.installed_build()
    state.save(session, data)
    if notes and config.attended():
        _emit(_context("UserPromptSubmit", "\n\n".join(notes)))


def area_index_for(home, cwd):
    return indexer.area_index_for(home, cwd)


def _cursor_pointers(home, limit=8):
    """One line per active cursor note, so a new session opens the right one instead of re-deriving state.

    Each line also says when the cursor last moved. It used to say why, quoted from the conversation that
    moved it -- which was another session's user turn pulled out of the archive, and the thing section 6
    and docs/comparison.md promise never happens automatically. The description says where the work
    stands and the timestamp says how stale that is; "where it came from" has to be earned without
    reading anyone's transcript (PLAN-log-first §3.5, §3.7).
    """
    try:
        cursors = [item for item in indexer.notes(home) if item["type"] == "cursor" and item["status"] != "retired"]
    except OSError:
        return ""
    cursors = sorted(cursors, key=indexer.by_priority)[:limit]
    rels = {f"memory/{item['file']}": item for item in cursors}
    try:
        moved = watch.last_moved(home, set(rels))
    except OSError:
        moved = {}
    lines = []
    for rel, item in rels.items():
        line = f"- {item['name']}: {item['description']}"
        last = moved.get(rel) or {}
        if last.get("time"):
            line += f"  [moved {watch._ago(last['time'])}]"
        lines.append(line)
    return "\n".join(lines)


def _rules_block(home):
    """AGENTS.md as a session receives it, truncated to its byte budget."""
    agents = home / "AGENTS.md"
    if not agents.exists():
        return ""
    raw = agents.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if len(raw) > config.AGENTS_BUDGET_BYTES:
        cut = raw[: config.AGENTS_BUDGET_BYTES].decode("utf-8", errors="ignore")
        if "\n" in cut:
            cut = cut[: cut.rfind("\n")]
        text = cut + f"\n\n[receipts-wiki loaded only the first {config.AGENTS_BUDGET_BYTES} of {len(raw)} bytes of AGENTS.md; shorten it.]"
    return f"Rules from {agents}, loaded by receipts-wiki:\n\n{text}"


def _stand_block(home):
    """The cursor pointers, under the heading a session sees them under."""
    pointers = _cursor_pointers(home)
    if not pointers:
        return ""
    return "Where things stand (open the cursor note for the area you're working in):\n" + pointers


def _area_block(home, cwd):
    """The memory index for a working directory, as a session receives it."""
    index = area_index_for(home, cwd)
    if not index:
        return ""
    text = index.read_text(encoding="utf-8", errors="replace")
    note = ""
    if len(text) > config.AREA_INDEX_CHARS:
        cut = text[: config.AREA_INDEX_CHARS]
        cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
        note = f"\n\n[receipts-wiki loaded the first {len(cut)} of {len(text)} characters of this index; open {index} for the rest.]"
        text = cut
    return (f"Memory index for this working directory, {index}, loaded by receipts-wiki. "
            f"Open only the notes the task needs.\n\n{text.rstrip()}{note}")


def render_preamble(home, cwd):
    """Every block a session is given at start, in the order the two SessionStart hooks emit them.

    Returns a list of (name, text) pairs in emission order; the names are for reporting, the text is
    what lands in the session. Pure: it reads memory and git and writes nothing. The hooks below render the same blocks through
    the same functions, so what `rw.py preamble` prints cannot drift from what a session receives.

    Three things a session also gets are deliberately absent, because they are not context: the
    catch-up commits and the sweep (side effects), the notices that go to the user as a
    systemMessage, and the per-prompt notice of what another session changed (`rw.py watch`).
    """
    if not home.exists():
        return [("diagnostic", NO_HOME.format(home=home))]
    blocks = [("rules", _rules_block(home))]
    if not gitlog.is_repo(home):
        blocks.append(("diagnostic", NOT_REPO.format(home=home)))
    blocks += [("where things stand", _stand_block(home)),
               ("read or changed lately", warm.block(home)),
               ("area index", _area_block(home, cwd))]
    return [(name, block) for name, block in blocks if block]


def hook_session_area(payload):
    """SessionStart: load the memory index for the working directory, within its own output budget."""
    if not config.attended():
        return
    block = _area_block(config.home(), payload.get("cwd") or os.getcwd())
    if block:
        _emit(_context("SessionStart", block))


def hook_session_start(payload):
    home = config.home()
    session = payload.get("session_id")
    parts, notices = [], []
    rules = _rules_block(home)
    if rules:
        parts.append(rules)

    # A session keeps the code it started with. On 2026-09-30 a session several releases behind
    # rewrote 29 of 33 generated indexes on one turn, and an earlier one filed notes under a type
    # scheme that had already been replaced. Neither announced itself; both looked like ordinary work.
    newer = config.newer_installed()
    if newer:
        build = config.installed_build()
        notices.append(f"receipts-wiki: this session is running {config.ROOT} but {newer} is installed"
                       f"{' at commit ' + build['commit'][:12] if build.get('commit') else ''}. "
                       "A session keeps the code it started with, so its rules, generators and gate are the older ones "
                       "— regenerating indexes from here can undo work a newer session did. Restart to pick up the new version, "
                       "or avoid `build-index` and memory-wide rewrites until you do.")

    if not home.exists():
        parts.append(NO_HOME.format(home=home))
    else:
        data = state.load(session)
        if not gitlog.is_repo(home):
            parts.append(NOT_REPO.format(home=home))
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
        state.save(session, data)
        for block in (_stand_block(home), warm.block(home)):
            if block:
                parts.append(block)

    if not config.attended():
        parts = []
    output = _context("SessionStart", "\n\n".join(parts)) if parts else {}
    if notices:
        output["systemMessage"] = " ".join(notices)
    if output:
        _emit(output)
