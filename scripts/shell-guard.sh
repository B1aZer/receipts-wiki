#!/bin/sh
# Pre-filter for the shell-write hook (PreToolUse on Bash). It runs on every shell command, so it only
# starts Python when the command mentions the memory home. Claude Code's `if: "Bash(...)"` filter cannot
# be used here: it does not see redirect targets or heredoc bodies, which is where memory writes appear.
input=$(cat)
home="${RECEIPTS_WIKI_HOME:-$HOME/.agents}"
name=$(basename "$home")
case "$input" in
  *"$name"*) printf '%s' "$input" | python3 "$(dirname "$0")/rw.py" hook shell ;;
esac
exit 0
