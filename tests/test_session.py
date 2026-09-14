"""Tests for rules injection, the append-only conversation archive, lesson candidates and notices."""
import json
import unittest

from test_hooks import HookTestCase, note

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

    def test_lesson_candidates_quote_the_user_and_touch_no_memory(self):
        path = self.transcript(BASE)
        self.end_turn(path)
        files = list((self.home / "proposals").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text()
        self.assertIn("From now on never cache quotes", text)
        self.assertIn("session:s-end#L2", text)
        self.assertNotIn("hunter2value", text)
        self.assertEqual([p for p in (self.home / "memory").glob("*.md")], [])

    def test_lesson_candidates_come_from_paragraphs_of_long_messages(self):
        long_message = "From now on always run the linter before committing.\n\n" + "Background detail without any rule in it. " * 40
        self.end_turn(self.transcript([{"type": "user", "timestamp": "2026-09-14T12:00:00Z",
                                        "message": {"role": "user", "content": long_message}}]), session="s-long")
        text = (self.home / "proposals" / "s-long.md").read_text()
        self.assertIn("always run the linter before committing", text)
        self.assertNotIn("Background detail", text)

    def test_session_start_injects_rules_within_budget(self):
        (self.home / "AGENTS.md").write_text("# AGENTS.md\n\n- Never store secrets.\n")
        context = self.hook("session-start", {"session_id": "s1", "source": "startup"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Never store secrets", context)
        (self.home / "AGENTS.md").write_text("# AGENTS.md\n" + "- a rule line long enough to add up quickly\n" * 400)
        context = self.hook("session-start", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertLess(len(context.encode()), 9000)
        self.assertIn("shorten it", context)

    def test_proposals_are_mentioned_at_session_start_and_once_a_day_in_long_sessions(self):
        self.end_turn(self.transcript(BASE))
        context = self.hook("session-start", {"session_id": "s2"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("lesson proposal", context)
        self.assertIsNone(self.hook("prompt", {"session_id": "s2", "prompt_id": "p1"}))
        first = self.hook("prompt", {"session_id": "long-running", "prompt_id": "p1"})
        self.assertIn("lesson proposal", first["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.hook("prompt", {"session_id": "long-running", "prompt_id": "p2"}))


if __name__ == "__main__":
    unittest.main()
