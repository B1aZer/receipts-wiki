# Contributing

Thanks for looking. receipts-wiki is a small plugin with one rule: it must never lose or leak what someone asked it to remember.

## Run it before you change it

```bash
git clone https://github.com/B1aZer/receipts-wiki.git
cd receipts-wiki
python3 -m unittest discover -s tests     # git and Python 3.9+ are the only requirements
claude --plugin-dir .                     # try your copy without installing it
```

`RECEIPTS_WIKI_HOME=/tmp/demo-memory` points every command and hook at a throwaway memory home, so you can experiment without touching your own.

## What a change needs

- **A test.** `tests/test_hooks.py` covers the write path and the end-of-turn checks, `tests/test_index_cli.py` the indexes and commands, `tests/test_session.py` the archive. A test builds a temporary memory home and drives the real hooks through `rw.py`, so it exercises what Claude Code will run.
- **No new dependencies.** The plugin is the Python standard library plus git. That is what lets it run offline, with no build step and no vector database.
- **A line in `CHANGELOG.md`** saying what changed and, where there is one, the evidence that prompted it: a number, a date, an incident.
- **Docs that match.** A behaviour agents rely on belongs in `templates/AGENTS.md` (the short rules loaded into every session) or `templates/WRITING.md` (the longer guide), and a user-visible change belongs in `README.md`.

## The rules the code itself follows

- **Never print a secret value.** The gate names the kind of secret it found, never the value; the archive redacts before writing. Tests assert this — keep them passing.
- **Memory history is append-only.** Corrections are new commits with a `Supersedes` line. Nothing resets, rebases or amends.
- **Hooks fail open.** A crashing hook must never block a session: `rw.py hook` catches everything and exits 0.
- **Quiet during a turn.** Checks report at the next prompt, not mid-work, and each one names its rule (`checks.RULES`).
- **A check earns its place.** New checks come from a real failure, described in the changelog entry. Noisy rules that fire on healthy memory belong in the `lint` sweep (`checks.SWEEP_ONLY`), not in the turn notices.

## Evals

`evals/` holds paired runs against real Claude Code sessions: `update_correctness` (does a corrected fact win?) and `drift` (does memory stay findable and current across sessions and directories?). They cost money to run and need `claude` on your PATH:

```bash
python3 evals/drift/run.py --dry-run
python3 evals/drift/run.py --scenario cursor-follow --arm receipts-wiki
```

Report what the numbers say, including when a change makes no measurable difference. Several proposals have been dropped on exactly that evidence.

## Reporting a problem

Open an issue with the plugin version (`/plugin` or `.claude-plugin/plugin.json`), what you expected, what happened, and the commit or hook output if you have it. Never paste a secret, even a rotated one.
