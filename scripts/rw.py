#!/usr/bin/env python3
"""receipts-wiki command line.

Hooks (called by Claude Code; read the payload on stdin, print at most one JSON object, always exit 0):
    rw.py hook session-start  inject AGENTS.md within budget; catch up on missed commits; mention proposals
    rw.py hook session-area   load the memory index that matches the working directory
    rw.py hook prompt        UserPromptSubmit: commit an interrupted turn; periodic catch-up
    rw.py hook read           PostToolUse on Read: remember the hash of a memory file this session read
    rw.py hook gate           PreToolUse on Write/Edit: block stale, secret-bearing or malformed memory writes
    rw.py hook history        PreToolUse on Bash: block git commands that rewrite the memory repository's history
    rw.py hook shell          PreToolUse on Bash: block shell commands that write into the memory home
    rw.py hook capture        PostToolUse on Write/Edit: note the file in this session's log
    rw.py hook stop           Stop and StopFailure: one commit for the turn, indexes, conversation archive
    rw.py hook session-end    same as stop, for the last turn

Commands:
    rw.py build-index [--no-commit]
    rw.py record [--agent NAME]
    rw.py precommit                 (run by the git pre-commit hook)
    rw.py install-git-hook
    rw.py history <note> [--patch]
    rw.py recall <query...> [--limit N]
    rw.py lint [--stale-days N] [--unread-days N]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rwlib import cli, config, hooks  # noqa: E402

HOOKS = {
    "session-start": hooks.hook_session_start,
    "session-area": hooks.hook_session_area,
    "prompt": hooks.hook_prompt,
    "read": hooks.hook_read,
    "gate": hooks.hook_gate,
    "history": hooks.hook_history,
    "shell": hooks.hook_shell,
    "capture": hooks.hook_capture,
    "stop": hooks.hook_stop,
    "session-end": hooks.hook_session_end,
}


def main(argv):
    if len(argv) == 2 and argv[0] == "hook":
        handler = HOOKS.get(argv[1])
        if handler is None:
            return 0
        payload = hooks.read_payload()
        try:
            handler(payload)
        except Exception as exc:  # a failing hook must never break the session; the tool call proceeds
            sys.stdout.write(json.dumps({"systemMessage": f"receipts-wiki {argv[1]} hook failed: {exc}"}))
        return 0

    parser = argparse.ArgumentParser(prog="rw.py", description="receipts-wiki maintenance commands")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-index", help="regenerate area indexes from note frontmatter")
    build.add_argument("--no-commit", action="store_true")
    rec = commands.add_parser("record", help="commit every uncommitted memory change as external.change")
    rec.add_argument("--agent", default="unknown")
    commands.add_parser("precommit", help="git pre-commit check of staged memory files; exit 1 blocks the commit")
    commands.add_parser("install-git-hook", help="install the pre-commit check in the memory repository")
    show = commands.add_parser("history", help="show the commits of one note")
    show.add_argument("note")
    show.add_argument("--patch", action="store_true")
    search = commands.add_parser("recall", help="search archived conversations")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=5)
    check = commands.add_parser("lint", help="report problems, forgetting candidates and pending proposals")
    check.add_argument("--stale-days", type=int, default=90)
    check.add_argument("--unread-days", type=int, default=60)
    args = parser.parse_args(argv)

    home = config.home()
    if args.command == "build-index":
        return cli.build_index(home, commit=not args.no_commit)
    if args.command == "record":
        return cli.record(home, agent=args.agent)
    if args.command == "precommit":
        return cli.precommit(home)
    if args.command == "install-git-hook":
        return cli.install_git_hook(home, Path(__file__).resolve())
    if args.command == "history":
        return cli.history(home, args.note, patch=args.patch)
    if args.command == "recall":
        return cli.recall(home, " ".join(args.query), limit=args.limit)
    return cli.lint(home, stale_days=args.stale_days, unread_days=args.unread_days)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
