#!/bin/sh
# Pre-filter for the shell-write hook (PreToolUse on Bash). It runs on every shell command, so it only
# starts Python when the command mentions the memory home. Claude Code's `if: "Bash(...)"` filter cannot
# be used here: it does not see redirect targets or heredoc bodies, which is where memory writes appear.
# It matches the WHOLE payload and not just tool_input.command, which matters since 2026-10-15:
# the hook now resolves a relative write target against the session's working directory, so a
# command with no mention of memory at all can still land in it. Those payloads reach Python
# because the payload's own `cwd` field carries the path. Narrowing this to the command text,
# which looks like the obvious optimisation, would restore the hole.
input=$(cat)
home="${RECEIPTS_WIKI_HOME:-$HOME/.agents}"
name=$(basename "$home")
case "$input" in
  *"$name"*) printf '%s' "$input" | python3 "$(dirname "$0")/rw.py" hook shell ;;
esac
exit 0
