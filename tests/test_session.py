"""Tests for rules and area-index injection, the append-only conversation archive, and unattended sessions."""
import json
import subprocess
import unittest

from test_hooks import RW, HookTestCase, note

BASE = [
    {"type": "ai-title", "aiTitle": "Quotes cache"},
    {"type": "user", "timestamp": "2026-09-14T10:00:00Z", "cwd": "/work/api", "gitBranch": "main",
     "message": {"role": "user", "content": "From now on never cache quotes longer than 5 minutes. PGPASSWORD=hunter2value is the db pass"}},
    {"type": "assistant", "timestamp": "2026-09-14T10:00:05Z",
     "message": {"role": "assistant", "content": [
         {"type": "text", "text": "Understood.<system-reminder>secret context</system-reminder>"},
         {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}},
    {"type": "user", "timestamp": "2026-09-14T10:00:06Z",
     "message": {"role": "user", "content": [{"type": "tool_result", "content": "file list"}]}},
]


class SessionTests(HookTestCase):
    def transcript(self, records, raw_tail=""):
        path = self.tmp / "t.jsonl"
        with path.open("a") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
            handle.write(raw_tail)
        return path

    def end_turn(self, path, session="s-end", turn="t1"):
        return self.hook("stop", {"session_id": session, "prompt_id": turn, "transcript_path": str(path), "cwd": "/work/api"})

    def archives(self):
        return sorted((self.home / "sessions").rglob("*.md"))

    def test_archive_keeps_conversation_text_only_and_redacts(self):
        self.end_turn(self.transcript(BASE))
        files = self.archives()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].relative_to(self.home / "sessions").as_posix(), "2026/09/s-end.md")
        text = files[0].read_text()
        self.assertIn("never cache quotes longer than 5 minutes", text)
        self.assertIn("title: Quotes cache", text)
        self.assertIn("user (line 2)", text)
        for leaked in ("hunter2value", "secret context", "file list"):
            self.assertNotIn(leaked, text)

    def test_archive_appends_only_new_messages_each_turn(self):
        path = self.transcript(BASE)
        self.end_turn(path, turn="t1")
        self.end_turn(path, turn="t2")
        self.transcript([{"type": "user", "timestamp": "2026-09-14T11:00:00Z",
                          "message": {"role": "user", "content": "Second question about the CDN."}}])
        self.end_turn(path, turn="t3")
        files = self.archives()
        self.assertEqual(len(files), 1)
        text = files[0].read_text()
        self.assertEqual(text.count("never cache quotes"), 1)
        self.assertIn("Second question about the CDN.", text)

    def test_incomplete_last_line_is_archived_on_the_next_turn(self):
        record = {"type": "user", "timestamp": "2026-09-14T12:00:00Z", "message": {"role": "user", "content": "Half written line."}}
        encoded = json.dumps(record)
        path = self.transcript([], raw_tail=encoded[:20])
        self.end_turn(path, turn="t1")
        self.assertEqual(self.archives(), [])
        with path.open("a") as handle:
            handle.write(encoded[20:] + "\n")
        self.end_turn(path, turn="t2")
        self.assertEqual(self.archives()[0].read_text().count("Half written line."), 1)

    def test_session_end_records_the_last_turn(self):
        self.write("memory/a.md", note("a", "cache", "Body."), session="s-last", turn="t1")
        self.hook("session-end", {"session_id": "s-last", "prompt_id": "t1", "transcript_path": "", "reason": "other"})
        self.assertIn("Change: fact.added memory/a.md", self.last_message())

    def test_summaries_and_task_notifications_are_not_the_users_words(self):
        records = [
            {"type": "user", "timestamp": "2026-09-14T09:00:00Z", "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
             "message": {"role": "user", "content": "This session is being continued. Never commit per session, always per turn."}},
            {"type": "user", "timestamp": "2026-09-14T09:01:00Z", "origin": {"kind": "task-notification"}, "promptSource": "system",
             "message": {"role": "user", "content": "<task-notification>Agent report: always stage only this session's paths.</task-notification>"}},
            {"type": "user", "timestamp": "2026-09-14T09:02:00Z",
             "message": {"role": "user", "content": "From now on always ask before pushing."}},
        ]
        self.end_turn(self.transcript(records), session="s-flags")
        archive = self.archives()[0].read_text()
        self.assertIn("always ask before pushing", archive)
        self.assertNotIn("being continued", archive)
        self.assertNotIn("Agent report", archive)

    def test_automated_sessions_keep_the_safety_checks_but_get_no_context(self):
        (self.home / "AGENTS.md").write_text("# AGENTS.md\n\n- Never store secrets.\n")
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "rules")
        (self.home / "memory" / "index-api.md").write_text("# api index\n\n- [cache](cache.md): cache TTL\n")
        project = self.tmp / "api"
        project.mkdir()
        env = dict(self.env(), RECEIPTS_WIKI_ATTENDED="0")
        def run(name, payload):
            return subprocess.run(["python3", str(RW), "hook", name], input=json.dumps(payload),
                                  capture_output=True, text=True, env=env, check=False)
        (self.home / "memory" / "codex.md").write_text(note("codex-note", "written outside the hooks", "Body."))
        self.assertEqual(run("session-start", {"session_id": "auto", "cwd": str(project)}).stdout.strip(), "")
        self.assertIn("Change: external.change memory/codex.md", self.last_message())
        self.assertEqual(run("session-area", {"session_id": "auto", "cwd": str(project)}).stdout.strip(), "")
        run("stop", {"session_id": "auto", "prompt_id": "t1", "transcript_path": str(self.transcript(BASE)), "cwd": str(project)})
        self.assertEqual(self.archives(), [])
        denied = run("gate", {"session_id": "auto", "tool_name": "Write",
                              "tool_input": {"file_path": str(self.home / "memory" / "db.md"), "content": "PGPASSWORD=hunter2value psql"}})
        self.assertEqual(json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_session_start_loads_the_index_for_the_working_directory(self):
        (self.home / "memory" / "index-api.md").write_text("# api index\n\n- [cache](cache.md): cache TTL is 5 minutes\n")
        (self.home / "memory" / "index-indexer-v2.md").write_text("# indexer index\n\n- [lag](lag.md): indexer lag note\n")
        project = self.tmp / "Sites" / "api" / "services" / "indexer-v2" / "src"
        project.mkdir(parents=True)
        nested = self.hook("session-area", {"session_id": "s1", "cwd": str(project)})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("indexer lag note", nested)
        self.assertNotIn("cache TTL", nested)
        parent = self.hook("session-area", {"session_id": "s1", "cwd": str(self.tmp / "Sites" / "api" / "services")})
        self.assertIn("cache TTL is 5 minutes", parent["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.hook("session-area", {"session_id": "s1", "cwd": str(self.tmp / "Sites")}))
        self.assertIsNone(self.hook("session-area", {"session_id": "s1", "cwd": str(self.home / "memory")}))

    def test_long_area_index_is_cut_at_a_line_with_a_pointer(self):
        lines = "".join(f"- [note-{i}](note_{i}.md): a description long enough to add up, number {i}\n" for i in range(400))
        (self.home / "memory" / "index-api.md").write_text("# api index\n\n" + lines)
        project = self.tmp / "api"
        project.mkdir()
        context = self.hook("session-area", {"session_id": "s1", "cwd": str(project)})["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(context), 9500)
        self.assertIn("for the rest", context)
        loaded = context.split("\n\n[receipts-wiki loaded")[0]
        self.assertRegex(loaded.splitlines()[-1], r"number \d+$")

    def test_session_start_injects_rules_within_budget(self):
        (self.home / "AGENTS.md").write_text("# AGENTS.md\n\n- Never store secrets.\n")
        context = self.hook("session-start", {"session_id": "s1", "source": "startup"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Never store secrets", context)
        (self.home / "AGENTS.md").write_text("# AGENTS.md\n" + "- a rule line long enough to add up quickly\n" * 400)
        context = self.hook("session-start", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(context.encode()), 9000)
        self.assertIn("shorten it", context)


if __name__ == "__main__":
    unittest.main()
