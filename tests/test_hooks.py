"""Tests for the write path: read tracker, write gate, capture, and one commit per turn.

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path

RW = Path(__file__).resolve().parents[1] / "scripts" / "rw.py"


def note(name, description, body, extra=""):
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  type: project\n"
        "  area: api\n"
        f"{extra}"
        "---\n\n"
        f"{body}\n"
    )


class HookTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "agents"
        (self.home / "memory").mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.com")
        self.git("commit", "-q", "--allow-empty", "-m", "init")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.home), *args], capture_output=True, text=True, check=False)

    def env(self):
        return dict(os.environ, RECEIPTS_WIKI_HOME=str(self.home), RECEIPTS_WIKI_CLAUDE_SETTINGS=str(self.tmp / "no-settings.json"),
                    RECEIPTS_WIKI_ATTENDED="1")

    def hook(self, name, payload):
        result = subprocess.run(
            ["python3", str(RW), "hook", name], input=json.dumps(payload),
            capture_output=True, text=True, env=self.env(), check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def payload(self, tool, path, session="s1", turn="t1", **tool_input):
        return {
            "session_id": session, "prompt_id": turn, "cwd": "/work/api", "transcript_path": "",
            "tool_name": tool, "tool_input": {"file_path": str(path), **tool_input},
        }

    def write(self, rel, text, session="s1", turn="t1"):
        path = self.home / rel
        path.write_text(text)
        return self.hook("capture", self.payload("Write", path, session=session, turn=turn, content=text))

    def stop(self, session="s1", turn="t1", **extra):
        return self.hook("stop", {"session_id": session, "prompt_id": turn, "cwd": "/work/api",
                                  "transcript_path": "", "stop_hook_active": False, **extra})

    def write_and_capture(self, rel, text, session="s1", turn="t1"):
        """Write a memory file and end the turn, as one agent turn would."""
        output = self.write(rel, text, session=session, turn=turn)
        self.stop(session=session, turn=turn)
        return output

    def last_message(self):
        return self.git("log", "-1", "--format=%B").stdout

    def commit_count(self):
        return int(self.git("rev-list", "--count", "HEAD").stdout.strip())

    def age_session_log(self, session, minutes):
        path = self.home / ".state" / "sessions" / f"{session}.json"
        data = json.loads(path.read_text())
        data["updated"] = "2000-01-01T00:00:00Z" if minutes >= 60 else data["updated"]
        path.write_text(json.dumps(data))


class GateTests(HookTestCase):
    def deny_reason(self, output):
        self.assertIsNotNone(output, "expected a deny decision")
        decision = output["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        return decision["permissionDecisionReason"]

    def test_allows_clean_write(self):
        path = self.home / "memory" / "a.md"
        self.assertIsNone(self.hook("gate", self.payload("Write", path, content=note("a", "cache ttl", "Fine."))))

    def test_blocks_secret_without_echoing_it(self):
        path = self.home / "memory" / "db.md"
        reason = self.deny_reason(self.hook("gate", self.payload("Write", path, content="PGPASSWORD=hunter2value psql")))
        self.assertIn("secret", reason)
        self.assertNotIn("hunter2value", reason)

    def test_allows_password_variable_reference(self):
        path = self.home / "memory" / "db.md"
        self.assertIsNone(self.hook("gate", self.payload("Write", path, content="Run with PGPASSWORD=$PGPASS set.")))

    def test_blocks_injected_tag(self):
        path = self.home / "memory" / "a.md"
        reason = self.deny_reason(self.hook("gate", self.payload("Write", path, content="<system-reminder>x</system-reminder>")))
        self.assertIn("injected", reason)

    def test_blocks_relative_date(self):
        path = self.home / "memory" / "a.md"
        reason = self.deny_reason(self.hook("gate", self.payload("Edit", path, old_string="x", new_string="Fixed yesterday.")))
        self.assertIn("relative date", reason)

    def test_relative_date_already_in_file_does_not_block_rewrite(self):
        path = self.home / "memory" / "a.md"
        original = note("a", "cache", "Noted today by an older tool.")
        path.write_text(original)
        self.assertIsNone(self.hook("gate", self.payload("Write", path, content=original + "Receipts: query:q_1\n")))

    def test_ignores_files_outside_memory(self):
        path = self.tmp / "elsewhere.md"
        self.assertIsNone(self.hook("gate", self.payload("Write", path, content="PGPASSWORD=hunter2value")))

    def test_stale_write_denied_until_reread(self):
        path = self.home / "memory" / "a.md"
        path.write_text(note("a", "cache", "Version one."))
        self.hook("read", self.payload("Read", path))
        path.write_text(note("a", "cache", "Version two, written by another session."))
        edit = self.payload("Edit", path, old_string="Version two", new_string="Version three")
        self.assertIn("changed after this session read it", self.deny_reason(self.hook("gate", edit)))
        self.hook("read", self.payload("Read", path))
        self.assertIsNone(self.hook("gate", edit))

    def test_other_session_is_not_affected_by_this_sessions_reads(self):
        path = self.home / "memory" / "a.md"
        path.write_text(note("a", "cache", "Version one."))
        self.hook("read", self.payload("Read", path, session="s1"))
        path.write_text(note("a", "cache", "Version two."))
        self.assertIsNone(self.hook("gate", self.payload("Edit", path, session="s2", old_string="two", new_string="three")))

    def test_generated_block_change_does_not_make_memory_md_stale(self):
        path = self.home / "memory" / "MEMORY.md"
        path.write_text("# Memory map\n\nMine.\n")
        self.hook("read", self.payload("Read", path))
        path.write_text("# Memory map\n\nMine.\n\n<!-- receipts-wiki:areas:start -->\n## Areas\n<!-- receipts-wiki:areas:end -->\n")
        self.assertIsNone(self.hook("gate", self.payload("Edit", path, old_string="Mine.", new_string="Mine, edited.")))

    def test_blocks_edits_to_generated_index(self):
        path = self.home / "memory" / "index-api.md"
        self.assertIn("generated", self.deny_reason(self.hook("gate", self.payload("Write", path, content="- [x](x.md)"))))


class HistoryGuardTests(HookTestCase):
    def bash(self, command, cwd="/work/api"):
        return self.hook("history", {"session_id": "s1", "cwd": cwd, "tool_name": "Bash", "tool_input": {"command": command}})

    def assertDenied(self, command, cwd="/work/api"):
        output = self.bash(command, cwd)
        self.assertIsNotNone(output, command)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("append-only", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_blocks_history_rewrites_in_the_memory_home(self):
        home = str(self.home)
        self.assertDenied(f"git -C {home} reset --hard HEAD~1")
        self.assertDenied(f"cd {home} && git rebase -i HEAD~3")
        self.assertDenied("git commit --amend -m fix", cwd=home)
        self.assertDenied(f"git -C {home}/memory reset HEAD~2")
        self.assertDenied(f"git --git-dir={home}/.git update-ref refs/heads/main HEAD~1")
        self.assertDenied(f"echo start; git -C '{home}' push --force origin main")
        self.assertDenied(f"GIT_EDITOR=true git -C {home} reflog expire --expire=now --all")

    def test_allows_forward_and_read_only_commands(self):
        home = str(self.home)
        for command in (f"git -C {home} log --oneline -5", f"git -C {home} revert --no-edit HEAD",
                        f"git -C {home} show HEAD:memory/a.md", "ls -la", f"git -C {home} reset -- memory/a.md",
                        f"git -C {home} commit -m 'fix; reset --hard is not run'"):
            self.assertIsNone(self.bash(command), command)

    def test_ignores_other_repositories(self):
        other = self.tmp / "project"
        other.mkdir()
        self.assertIsNone(self.bash(f"git -C {other} reset --hard HEAD~1"))
        self.assertIsNone(self.bash("git reset --hard HEAD~1", cwd=str(other)))


class ShellWriteTests(HookTestCase):
    def shell(self, command):
        return self.hook("shell", {"session_id": "s1", "cwd": "/work/api", "tool_name": "Bash", "tool_input": {"command": command}})

    def prompt(self, session="s1", turn="t1"):
        return self.hook("prompt", {"session_id": session, "prompt_id": turn, "cwd": "/work/api"})

    def test_blocks_shell_writes_into_memory(self):
        memory = f"{self.home}/memory"
        for command in (f"echo 'x' >> {memory}/a.md",
                        f"python3 - <<'PY'\nopen('{memory}/MEMORY.md', 'w').write('x')\nPY",
                        f"sed -i '' 's/a/b/' {memory}/a.md",
                        f"rm {memory}/a.md",
                        f"cp /tmp/draft.md {memory}/a.md",
                        f"cat /tmp/draft.md | tee {memory}/a.md",
                        f"MEM={memory}/a.md; printf 'x' > {memory}/b.md"):
            output = self.shell(command)
            self.assertIsNotNone(output, command)
            self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIn("Write or Edit tool", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_guard_script_starts_python_only_for_commands_that_mention_memory(self):
        guard = RW.parent / "shell-guard.sh"
        def run(command):
            payload = json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command}})
            return subprocess.run(["sh", str(guard)], input=payload, capture_output=True, text=True, env=self.env(), check=False)
        quiet = run("ls -la /tmp")
        self.assertEqual((quiet.returncode, quiet.stdout), (0, ""))
        denied = run(f"python3 - <<'PY'\nopen('{self.home}/memory/MEMORY.md', 'w').write('x')\nPY")
        self.assertEqual(denied.returncode, 0)
        self.assertEqual(json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allows_reading_memory_and_unrelated_commands(self):
        memory = f"{self.home}/memory"
        for command in (f"cat {memory}/a.md", f"grep -rn cache {memory}", f"git -C {self.home} log --oneline",
                        f"cat {memory}/a.md > /tmp/copy.md", f"RECEIPTS_WIKI_HOME={self.home} python3 rw.py lint",
                        "echo hi > /tmp/x.md", f"python3 -c \"print(open('{memory}/a.md').read())\""):
            self.assertIsNone(self.shell(command), command)

    def test_shell_write_during_a_turn_is_credited_to_it(self):
        self.prompt(turn="t1")
        (self.home / "memory" / "a.md").write_text(note("a-note", "written by a shell command", "Body, fixed yesterday."))
        self.assertIsNone(self.stop(turn="t1"))
        message = self.last_message()
        for line in ("Change: fact.added memory/a.md", "Shell-write: memory/a.md", "Session: s1", "Turn: t1"):
            self.assertIn(line, message)
        context = self.prompt(turn="t2")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("with a shell command instead of Write or Edit", context)
        self.assertIn("relative date", context)
        self.assertIsNone(self.prompt(turn="t2"))

    def test_file_changed_before_the_turn_is_left_to_catch_up(self):
        path = self.home / "memory" / "old.md"
        path.write_text(note("old-note", "changed before this turn", "Body."))
        old = time.time() - 600
        os.utime(path, (old, old))
        self.prompt(turn="t1")
        self.stop(turn="t1")
        self.assertNotIn("Shell-write", self.git("log", "--format=%B").stdout)
        self.assertIn("Change: external.change memory/old.md", self.last_message())

    def test_another_session_mid_turn_makes_credit_ambiguous(self):
        self.prompt(session="s2", turn="u1")
        self.prompt(session="s1", turn="t1")
        (self.home / "memory" / "a.md").write_text(note("a-note", "who wrote this", "Body."))
        self.stop(session="s1", turn="t1")
        self.assertEqual(self.commit_count(), 1)

    def test_shell_written_secret_is_not_committed(self):
        self.prompt(turn="t1")
        (self.home / "memory" / "db.md").write_text(note("db", "database access", "PGPASSWORD=hunter2value psql"))
        output = self.stop(turn="t1")
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("contains a secret value", output["systemMessage"])
        self.assertNotIn("hunter2value", output["systemMessage"])


class TurnTests(HookTestCase):
    def test_capture_alone_does_not_commit_or_talk(self):
        output = self.write("memory/a.md", note("a", "cache", "Body."))
        self.assertIsNone(output)
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("memory/a.md", self.git("status", "--porcelain", "--untracked-files=all").stdout)

    def test_one_commit_per_turn_with_change_trailers(self):
        self.write("memory/project_ttl.md", note("quotes-cache-ttl", "quotes cache TTL", "The TTL is 5 minutes.\n\nWhy: 14 of 200 quotes were stale.", extra="  receipts: [query:q_8812]\n"))
        self.write("memory/project_rate.md", note("partner-rate-limit", "partner rate limit", "500 per minute."))
        (self.home / "memory" / "MEMORY.md").write_text("# Memory map\n\nPointers.\n")
        self.hook("capture", self.payload("Write", self.home / "memory" / "MEMORY.md", content="# Memory map\n\nPointers.\n"))
        self.assertIsNone(self.stop())
        self.assertEqual(self.commit_count(), 2)
        message = self.last_message()
        self.assertTrue(message.startswith("memory(api): add partner-rate-limit, add quotes-cache-ttl"), message)
        for line in ("intent(quotes-cache-ttl): 14 of 200 quotes were stale.",
                     "Change: fact.added memory/project_ttl.md", "Change: fact.added memory/project_rate.md",
                     "Change: index.rebuilt memory/index-api.md", "Agent: claude-code", "Session: s1", "Turn: t1",
                     "Cwd: /work/api", "Receipts: query:q_8812"):
            self.assertIn(line, message)
        self.assertEqual(self.git("status", "--porcelain", "--", "memory").stdout.strip(), "")

    def test_edits_within_a_turn_collapse_into_the_net_change(self):
        rel = "memory/project_ttl.md"
        base = note("quotes-cache-ttl", "ttl", "The API cache TTL caused stale quotes.")
        self.write_and_capture(rel, base, turn="t1")
        count = self.commit_count()
        self.write(rel, base.replace("caused stale quotes.", "caused stale quotes, maybe."), turn="t2")
        self.write(rel, base.replace("The API cache TTL caused stale quotes.",
                                     "The CDN edge cache.\n\nSupersedes (2026-09-16): the API cache TTL caused stale quotes. 12 of 200 still stale"), turn="t2")
        self.stop(turn="t2")
        self.assertEqual(self.commit_count(), count + 1)
        message = self.last_message()
        self.assertIn("Change: fact.superseded memory/project_ttl.md", message)
        self.assertIn("rejected(quotes-cache-ttl): the API cache TTL caused stale quotes; 12 of 200 still stale", message)

    def test_verify_and_retire_events(self):
        rel = "memory/project_ttl.md"
        base = note("quotes-cache-ttl", "ttl", "Body.", extra="  last_verified: 2026-09-10\n")
        self.write_and_capture(rel, base, turn="t1")
        verified = base.replace("last_verified: 2026-09-10", "last_verified: 2026-09-20")
        self.write_and_capture(rel, verified, turn="t2")
        self.assertIn("Change: fact.verified memory/project_ttl.md", self.last_message())
        self.write_and_capture(rel, verified.replace("  area: api\n", "  area: api\n  status: retired\n"), turn="t3")
        self.assertIn("Change: fact.retired memory/project_ttl.md", self.last_message())

    def test_stop_without_changes_commits_nothing(self):
        self.assertIsNone(self.stop())
        self.assertEqual(self.commit_count(), 1)

    def test_stop_while_a_stop_hook_is_continuing_does_nothing(self):
        self.write("memory/a.md", note("a", "cache", "Body."))
        self.stop(stop_hook_active=True)
        self.assertEqual(self.commit_count(), 1)

    def test_parallel_sessions_commit_only_their_own_files(self):
        self.write("memory/a.md", note("alpha-note", "alpha", "A."), session="s1", turn="t1")
        self.write("memory/b.md", note("beta-note", "beta", "B."), session="s2", turn="u1")
        self.stop(session="s2", turn="u1")
        message = self.last_message()
        self.assertIn("Change: fact.added memory/b.md", message)
        self.assertNotIn("memory/a.md", message)
        self.assertIn("Session: s2", message)
        self.assertNotIn("alpha-note", self.git("show", "HEAD:memory/index-api.md").stdout)
        self.stop(session="s1", turn="t1")
        message = self.last_message()
        self.assertIn("Change: fact.added memory/a.md", message)
        self.assertIn("Session: s1", message)

    def test_interrupted_turn_is_committed_at_the_next_prompt(self):
        self.write("memory/a.md", note("a", "cache", "Body."), turn="t1")
        self.hook("prompt", {"session_id": "s1", "prompt_id": "t2", "cwd": "/work/api"})
        message = self.last_message()
        self.assertIn("Turn: t1", message)
        self.assertIn("Recovered: true", message)

    def test_prompt_inside_the_running_turn_leaves_its_writes_pending(self):
        self.write("memory/a.md", note("a", "cache", "Body."), turn="t1")
        self.hook("prompt", {"session_id": "s1", "prompt_id": "t1", "cwd": "/work/api"})
        self.assertEqual(self.commit_count(), 1)
        self.write("memory/b.md", note("b", "queue", "Body."), turn="t1")
        self.stop(turn="t1")
        message = self.last_message()
        self.assertEqual(self.commit_count(), 2)
        self.assertIn("Change: fact.added memory/a.md", message)
        self.assertIn("Change: fact.added memory/b.md", message)
        self.assertNotIn("Recovered", message)

    def test_subagent_write_joins_the_parent_turn(self):
        path = self.home / "memory" / "a.md"
        text = note("a", "cache", "Body.")
        path.write_text(text)
        payload = self.payload("Write", path, content=text)
        payload["agent_id"] = "a8f4b7bb51dc1be46"
        self.hook("capture", payload)
        self.stop()
        self.assertIn("Change: fact.added memory/a.md", self.last_message())

    def test_stale_log_of_another_session_is_committed_under_that_session(self):
        self.write("memory/a.md", note("a", "cache", "Body."), session="crashed", turn="t9")
        self.age_session_log("crashed", minutes=120)
        self.hook("session-start", {"session_id": "s2", "source": "startup"})
        message = self.last_message()
        self.assertIn("Session: crashed", message)
        self.assertIn("Recovered: true", message)

    def test_fresh_log_of_another_session_is_left_alone(self):
        self.write("memory/a.md", note("a", "cache", "Body."), session="busy", turn="t1")
        self.hook("session-start", {"session_id": "s2", "source": "startup"})
        self.assertEqual(self.commit_count(), 1)

    def test_changes_without_hooks_are_recorded_as_external(self):
        (self.home / "memory" / "codex.md").write_text(note("codex-note", "written without hooks", "Body."))
        self.hook("session-start", {"session_id": "s2", "source": "startup"})
        message = self.last_message()
        self.assertIn("Change: external.change memory/codex.md", message)
        self.assertIn("Agent: unknown", message)

    def test_merge_in_progress_postpones_the_commit_and_says_so(self):
        self.write("memory/a.md", note("a", "cache", "Body."))
        merge_head = self.home / ".git" / "MERGE_HEAD"
        merge_head.write_text(self.git("rev-parse", "HEAD").stdout)
        output = self.stop()
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("merge, rebase", output["systemMessage"])
        merge_head.unlink()
        self.assertIsNone(self.stop())
        self.assertEqual(self.commit_count(), 2)

    def test_failed_commit_is_reported_every_turn_until_it_succeeds(self):
        hook = self.home / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\necho 'rejected by pre-commit' >&2\nexit 1\n")
        hook.chmod(0o755)
        self.write("memory/a.md", note("a", "cache", "Body."))
        first = self.stop()
        self.assertIn("could not commit 1 memory file(s)", first["systemMessage"])
        self.assertIn("rejected by pre-commit", first["systemMessage"])
        second = self.stop(turn="t2")
        self.assertIn("2 attempts since", second["systemMessage"])
        lint = subprocess.run(["python3", str(RW), "lint"], capture_output=True, text=True, env=self.env(), check=False).stdout
        self.assertIn("uncommitted memory write(s), failing since", lint)
        hook.unlink()
        self.assertIsNone(self.stop(turn="t3"))
        self.assertEqual(self.commit_count(), 2)
        self.assertNotIn("failing since", subprocess.run(["python3", str(RW), "lint"], capture_output=True, text=True, env=self.env(), check=False).stdout)

    def test_signing_failure_is_reported(self):
        self.git("config", "commit.gpgsign", "true")
        self.git("config", "gpg.format", "ssh")
        self.git("config", "user.signingkey", str(self.tmp / "no-such-key"))
        self.write("memory/a.md", note("a", "cache", "Body."))
        output = self.stop()
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("could not commit", output["systemMessage"])

    def test_session_start_reports_failed_catch_up_and_stale_files(self):
        hook = self.home / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        path = self.home / "memory" / "codex.md"
        path.write_text(note("codex-note", "written without hooks", "Body."))
        old = time.time() - 3600
        os.utime(path, (old, old))
        message = self.hook("session-start", {"session_id": "s2"})["systemMessage"]
        self.assertIn("could not commit memory changes made outside a session turn", message)
        self.assertIn("uncommitted for over 30 minutes: memory/codex.md", message)

    def test_related_hint_only_for_new_notes(self):
        self.write_and_capture("memory/project_quotes_cache.md", note("quotes-cache-ttl", "quotes cache ttl five minutes", "Old."), turn="t1")
        hint = self.write("memory/project_quotes_cache_v2.md", note("quotes-cache-ttl-cdn", "quotes cache ttl five minutes cdn", "New."), turn="t2")
        self.assertIn("memory/project_quotes_cache.md", hint["hookSpecificOutput"]["additionalContext"])
        self.stop(turn="t2")
        self.assertIsNone(self.write("memory/project_quotes_cache_v2.md", note("quotes-cache-ttl-cdn", "quotes cache ttl five minutes cdn", "Newer."), turn="t3"))

    def test_hint_names_a_note_on_the_same_topic_with_different_wording(self):
        memory = self.home / "memory"
        for i, topic in enumerate(["billing export", "search ranking", "login rate limit", "image resize"]):
            (memory / f"project_other{i}.md").write_text(note(f"other-{i}", topic, "Unrelated body."))
        self.write_and_capture("memory/feedback_plan_docs.md", note("plan-docs", "plans are markdown docs in the repo docs folder, not plan mode", "Body."), turn="t1")
        hint = self.write("memory/feedback_plan_as_doc.md", note("plan-as-doc", "write plans as markdown docs in docs folder", "Body."), turn="t2")
        self.assertIn("Existing notes on the same topic: memory/feedback_plan_docs.md", hint["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("project_other", hint["hookSpecificOutput"]["additionalContext"])

    def test_no_hint_for_weak_overlap(self):
        self.write_and_capture("memory/project_quotes_cache.md", note("quotes-cache-ttl", "quotes cache ttl five minutes", "Old."), turn="t1")
        self.assertIsNone(self.write("memory/project_cdn.md", note("cdn-edge", "quotes cdn edge purge", "New."), turn="t2"))

    def test_commits_leave_other_dirty_files_alone(self):
        (self.home / "memory" / "untouched.md").write_text(note("untouched", "left alone", "Dirty, written by nobody's hook."))
        self.write_and_capture("memory/a.md", note("a", "cache", "Body."))
        status = self.git("status", "--porcelain", "--untracked-files=all").stdout
        self.assertIn("untouched.md", status)
        self.assertNotIn("memory/a.md", status)

    def test_agents_md_change_is_rules_changed(self):
        self.write_and_capture("AGENTS.md", "# AGENTS.md\n\n- Never store secrets.\n")
        message = self.last_message()
        self.assertIn("rules(general): update AGENTS.md", message)
        self.assertIn("Change: rules.changed AGENTS.md", message)

    def test_own_write_does_not_make_the_file_stale(self):
        rel = "memory/a.md"
        self.write_and_capture(rel, note("a", "cache", "One."))
        self.assertIsNone(self.hook("gate", self.payload("Edit", self.home / rel, old_string="One.", new_string="Two.")))

    def test_first_commit_in_empty_repository(self):
        empty = self.tmp / "fresh"
        (empty / "memory").mkdir(parents=True)
        self.git("init", "-q", "-b", "main", cwd=empty)
        self.git("config", "user.name", "test", cwd=empty)
        self.git("config", "user.email", "test@example.com", cwd=empty)
        self.home = empty
        self.write_and_capture("memory/a.md", note("a", "cache", "Body."))
        self.assertEqual(self.commit_count(), 1)
        self.assertIn("Change: fact.added memory/a.md", self.last_message())

    def test_never_commits_into_an_enclosing_repository(self):
        parent = self.tmp / "project"
        nested_home = parent / "agents"
        (nested_home / "memory").mkdir(parents=True)
        self.git("init", "-q", "-b", "main", cwd=parent)
        self.home = nested_home
        self.write_and_capture("memory/a.md", note("a", "cache", "Body."))
        self.assertNotEqual(self.git("log", "-1", cwd=parent).returncode, 0)
        context = self.hook("session-start", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not the root of a git repository", context)


def cursor(name, description, body):
    return f"---\nname: {name}\ndescription: {description}\nmetadata:\n  type: cursor\n  area: api\n---\n\n{body}\n"


class WarmListTests(HookTestCase):
    """Warmth is use, not age: reads and edits inside the window, cursors and retired notes left out."""

    @staticmethod
    def warm_module():
        import sys
        sys.path.insert(0, str(RW.parent))
        from rwlib import warm
        return warm

    def recent(self, **kwargs):
        return self.warm_module().recent(self.home, today=date(2026, 9, 20), **kwargs)

    def seed_reads(self, stamps):
        (self.home / ".state").mkdir(exist_ok=True)
        (self.home / ".state" / "last_read.json").write_text(json.dumps(stamps))
        os.environ["RECEIPTS_WIKI_HOME"] = str(self.home)
        self.addCleanup(os.environ.pop, "RECEIPTS_WIKI_HOME", None)

    def test_read_recently_is_warm_and_an_old_read_is_not(self):
        memory = self.home / "memory"
        (memory / "project_hot.md").write_text(note("hot-note", "read this week", "Body."))
        (memory / "project_cold.md").write_text(note("cold-note", "read in August", "Body."))
        self.seed_reads({"memory/project_hot.md": "2026-09-19", "memory/project_cold.md": "2026-08-01"})
        self.assertEqual([item["name"] for _, item in self.recent()], ["hot-note"])

    def test_cursor_and_retired_notes_are_left_out(self):
        memory = self.home / "memory"
        (memory / "cursor_api.md").write_text(note("cursor-api", "next step", "Body.").replace("type: project", "type: cursor"))
        (memory / "project_done.md").write_text(note("done-note", "finished", "Body.", extra="  status: retired\n"))
        (memory / "project_live.md").write_text(note("live-note", "current", "Body."))
        self.seed_reads({f"memory/{name}": "2026-09-19" for name in ("cursor_api.md", "project_done.md", "project_live.md")})
        self.assertEqual([item["name"] for _, item in self.recent()], ["live-note"])

    def test_a_committed_note_is_warm_without_a_read_and_reaches_session_start(self):
        self.write_and_capture("memory/project_edited.md", note("edited-note", "changed in this turn", "Body."))
        self.seed_reads({})
        self.assertIn("edited-note", [item["name"] for _, item in self.recent()])
        context = self.hook("session-start", {"session_id": "s2"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Worked on lately", context)
        self.assertIn("edited-note", context)

    def test_block_stays_within_its_budget(self):
        for i in range(12):
            (self.home / "memory" / f"project_{i}.md").write_text(note(f"note-{i}", "d" * 120, "Body."))
        self.seed_reads({f"memory/project_{i}.md": "2026-09-19" for i in range(12)})
        warm = self.warm_module()
        self.assertEqual(len(warm.recent(self.home, today=date(2026, 9, 20), limit=5)), 5)
        block = warm.block(self.home, budget=400, today=date(2026, 9, 20))
        body = block.split(chr(10), 1)[1]
        self.assertLessEqual(len(body), 400 + 160)
        self.assertTrue(body.startswith("- [note-"))


class TurnCheckTests(HookTestCase):
    """Drift checks run after the turn's commit and reach the agent at its next prompt."""

    def notices(self, turn):
        output = self.hook("prompt", {"session_id": "s1", "prompt_id": turn, "cwd": "/work/api"})
        return output["hookSpecificOutput"]["additionalContext"] if output else ""

    def test_clean_turn_says_nothing(self):
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "Five minutes."))
        self.assertEqual(self.notices("t2"), "")

    def test_note_missing_from_a_hand_written_index(self):
        # A full MEMORY.md makes the generated block list areas instead of notes, as in a mature memory home.
        (self.home / "memory" / "MEMORY.md").write_text("# Memory map\n" + "- pointer\n" * 145)
        (self.home / "memory" / "index-api.md").write_text("# api\n\n- [other](other.md)\n")
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "Five minutes."))
        text = self.notices("t2")
        self.assertIn("memory/project_ttl.md is not linked from any index", text)
        self.assertIn("memory/index-api.md is written by hand", text)
        self.write("memory/index-api.md", "# api\n\n- [ttl](./project_ttl.md)\n", turn="t2")
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "Six minutes."), turn="t2")
        self.assertEqual(self.notices("t3"), "")

    def test_cursor_left_behind_by_a_linked_note(self):
        self.write_and_capture("memory/cursor_api.md", cursor("cursor-api", "PR not opened; NEXT = open it", "See [[quotes-cache-ttl]]."))
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "PR #12 opened."), turn="t2")
        self.assertIn('cursor note memory/cursor_api.md points to, but not the cursor. It still says: "PR not opened', self.notices("t3"))
        self.write("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "PR #12 merged."), turn="t3")
        self.write_and_capture("memory/cursor_api.md", cursor("cursor-api", "PR merged; NEXT = deploy", "See [[quotes-cache-ttl]]."), turn="t3")
        self.assertEqual(self.notices("t4"), "")

    def test_unlinked_cursor_is_not_mentioned(self):
        self.write_and_capture("memory/cursor_api.md", cursor("cursor-api", "next step", "Nothing linked."))
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "Five minutes."), turn="t2")
        self.assertEqual(self.notices("t3"), "")

    def test_oversized_note(self):
        self.write_and_capture("memory/project_log.md", note("deploy-log", "log", "Step done.\n" * 1200))
        self.assertIn("over the 12 KB note budget", self.notices("t2"))

    def test_misspelled_link_is_named_and_a_future_link_is_not(self):
        self.write_and_capture("memory/project_ttl.md", note("project-quotes-cache-ttl", "ttl", "Five minutes."))
        self.write_and_capture("memory/project_rate.md", note("partner-rate-limit", "rate",
                                                             "See [[quotes-cache-ttl]], [[project_quotes_cache_ttl]] and [[cdn-purge]]."), turn="t2")
        text = self.notices("t3")
        self.assertIn("[[quotes-cache-ttl]] should be [[project-quotes-cache-ttl]]", text)
        self.assertNotIn("project_quotes_cache_ttl]] should", text)
        self.assertNotIn("cdn-purge", text)

    def test_unattended_session_gets_no_notices(self):
        (self.home / "memory" / "index-api.md").write_text("# api\n")
        unattended = dict(HookTestCase.env(self), RECEIPTS_WIKI_ATTENDED="0")
        self.env = lambda: unattended
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "ttl", "Five minutes."))
        del self.env
        self.assertEqual(self.notices("t2"), "")


if __name__ == "__main__":
    unittest.main()
