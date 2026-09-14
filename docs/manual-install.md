# Installing without the plugin system

Use this when you want the receipts-wiki hooks but do not install Claude Code plugins. Do not combine it with the plugin: the hooks would run twice.

## 1. Get the code

```bash
git clone https://github.com/B1aZer/receipts-wiki ~/src/receipts-wiki
```

The rest of this page uses `~/src/receipts-wiki`; replace it with your path.

## 2. Create the memory home

```bash
mkdir -p ~/.agents/memory
git -C ~/.agents init -b main
printf 'sessions/\nproposals/\n.state/\n' >> ~/.agents/.gitignore
[ -f ~/.agents/AGENTS.md ] || cp ~/src/receipts-wiki/templates/AGENTS.md ~/.agents/AGENTS.md
python3 ~/src/receipts-wiki/scripts/rw.py install-git-hook
```

The last line installs a git pre-commit check in `~/.agents`. It blocks commits that stage a secret value or a note without a name and description, whoever makes them.

Edit `~/.agents/AGENTS.md` and replace the example rules with yours.

## 3. Add settings and hooks

Merge this into `~/.claude/settings.json`, keeping your other keys. If you already have hooks for these events, add the entries to the existing arrays.

```json
{
  "autoMemoryDirectory": "~/.agents/memory",
  "cleanupPeriodDays": 90,
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook session-start", "timeout": 20}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook prompt", "timeout": 20}]}
    ],
    "PreToolUse": [
      {"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook gate", "timeout": 10}]},
      {"matcher": "Bash", "hooks": [{"type": "command", "if": "Bash(git *)", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook history", "timeout": 10}]}
    ],
    "PostToolUse": [
      {"matcher": "Read", "hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook read", "timeout": 10}]},
      {"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook capture", "timeout": 10}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook stop", "timeout": 30}]}
    ],
    "StopFailure": [
      {"hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook stop", "timeout": 30}]}
    ],
    "SessionEnd": [
      {"hooks": [{"type": "command", "command": "python3 ~/src/receipts-wiki/scripts/rw.py hook session-end", "timeout": 10}]}
    ]
  }
}
```

`cleanupPeriodDays` is how many days Claude Code keeps full transcripts; pick your own value. A malformed settings file disables every setting in it, so check the result:

```bash
python3 -m json.tool ~/.claude/settings.json > /dev/null && echo valid
```

## 4. Verify

Start a new session and check the rules arrived, then write a note and look at the commit:

```bash
cd /tmp && claude -p "Use no tools. Reply with the first markdown heading of the AGENTS.md content in your instructions, or NONE."
git -C ~/.agents log -3 --format='%h %s | %(trailers:key=Change,valueonly,separator=%x2C )'
python3 ~/src/receipts-wiki/scripts/rw.py lint
```

## Other agents

Point the agent's global instructions at `~/.agents/AGENTS.md` (Codex: `ln -s ~/.agents/AGENTS.md ~/.codex/AGENTS.md`). The template tells agents without hooks to commit their memory writes; anything left uncommitted is recorded as `external.change` at the next catch-up in a Claude Code session (session start, or a prompt at most every 10 minutes).
