"""Tests for cross-session visibility (PLAN-log-first §3.5): session B changes a note session A relies on.

Run: python3 -m unittest discover -s tests -v
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from test_changes import ts
from test_hooks import RW, HookTestCase, note

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rwlib import watch  # noqa: E402


def cursor(name, description, body):
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  type: cursor\n"
        "  area: api\n"
        "---\n\n"
        f"{body}\n"
    )


class WatchTestCase(HookTestCase):
    def prompt(self, session, turn):
        return self.hook("prompt", {"session_id": session, "prompt_id": turn, "cwd": "/work/api",
                                    "transcript_path": ""})

    def notice_for(self, session):
        """The notice text a session's next prompt would carry, as the hook emits it."""
        output = self.prompt(session, "t-probe")
        if not output:
            return ""
        return output["hookSpecificOutput"]["additionalContext"]

    def session_state(self, session):
        """Read this test home's state file directly: state.load() resolves the home from the
        environment, which is not set in the test process, so it would read the author's real home."""
        return json.loads((self.home / ".state" / "sessions" / f"{session}.json").read_text())

    def read_note(self, rel, session):
        path = self.home / rel
        self.hook("read", self.payload("Read", path, session=session, turn="t-read"))

    # -- the offset ---------------------------------------------------------

    def test_first_prompt_sets_the_offset_and_stays_silent(self):
        self.write_and_capture("memory/one.md", note("one", "first", "body"), session="b", turn="t1")
        self.assertEqual(self.notice_for("a"), "")
        self.assertTrue(self.session_state("a")["seen_commit"])

    def test_silent_when_nothing_changed_since_the_offset(self):
        self.write_and_capture("memory/one.md", note("one", "first", "body"), session="b", turn="t1")
        self.notice_for("a")
        self.assertEqual(self.notice_for("a"), "")

    def test_a_missing_offset_does_not_raise(self):
        self.write_and_capture("memory/one.md", note("one", "first", "body"), session="b", turn="t1")
        data = {"reads": {}, "seen_commit": "0" * 40}
        self.assertEqual(watch.notice(self.home, "a", data), "")

    # -- what reaches the session ------------------------------------------

    def test_reports_a_note_this_session_read(self):
        self.write_and_capture("memory/shared.md", note("shared", "a fact", "first"), session="b", turn="t1")
        self.read_note("memory/shared.md", "a")
        self.notice_for("a")
        self.write_and_capture("memory/shared.md", note("shared", "a fact", "second"), session="b", turn="t2")
        text = self.notice_for("a")
        self.assertIn("shared changed", text)
        self.assertIn("another session", text)

    def test_silent_about_a_note_this_session_never_touched(self):
        self.write_and_capture("memory/mine.md", note("mine", "mine", "body"), session="b", turn="t1")
        self.read_note("memory/mine.md", "a")
        self.notice_for("a")
        self.write_and_capture("memory/other.md", note("other", "unrelated", "body"), session="b", turn="t2")
        self.assertEqual(self.notice_for("a"), "")

    def test_its_own_changes_are_never_reported_back(self):
        self.write_and_capture("memory/mine.md", note("mine", "mine", "body"), session="a", turn="t1")
        self.read_note("memory/mine.md", "a")
        self.notice_for("a")
        self.write_and_capture("memory/mine.md", note("mine", "mine", "changed"), session="a", turn="t2")
        self.assertEqual(self.notice_for("a"), "")

    def test_a_cursor_change_reaches_every_session_but_ranks_below_a_read_note(self):
        self.write_and_capture("memory/cursor_work.md", cursor("cursor-work", "step one", "body"),
                               session="b", turn="t1")
        self.write_and_capture("memory/fact.md", note("fact", "a fact", "first"), session="b", turn="t2")
        self.read_note("memory/fact.md", "a")
        self.notice_for("a")
        self.write_and_capture("memory/cursor_work.md", cursor("cursor-work", "step two", "body"),
                               session="b", turn="t3")
        self.write_and_capture("memory/fact.md", note("fact", "a fact", "second"), session="b", turn="t4")
        lines = [line for line in self.notice_for("a").splitlines() if line.startswith("- ")]
        self.assertIn("fact changed", lines[0])
        self.assertIn("cursor-work changed", lines[1])
        self.assertIn("cursor you were shown", lines[1])

    def test_one_hop_reaches_a_note_linking_to_one_this_session_read(self):
        self.write_and_capture("memory/anchor.md", note("anchor", "anchor", "body"), session="b", turn="t1")
        self.read_note("memory/anchor.md", "a")
        self.notice_for("a")
        self.write_and_capture("memory/neighbour.md", note("neighbour", "next door", "see [[anchor]]"),
                               session="b", turn="t2")
        text = self.notice_for("a")
        self.assertIn("neighbour changed", text)
        self.assertIn("linked to notes you read", text)

    def test_hops_do_not_run_from_cursors(self):
        """Cursors are the most linked notes in a home; hopping from them would match most of memory."""
        self.write_and_capture("memory/cursor_work.md", cursor("cursor-work", "step one", "body"),
                               session="b", turn="t1")
        self.notice_for("a")
        self.write_and_capture("memory/far.md", note("far", "far away", "see [[cursor-work]]"),
                               session="b", turn="t2")
        self.assertEqual(self.notice_for("a"), "")

    # -- budget ------------------------------------------------------------

    def test_one_commit_touching_many_notes_costs_one_line(self):
        for i in range(4):
            self.write(f"memory/n{i}.md", note(f"n{i}", f"note {i}", "first"), session="b", turn="t1")
        self.stop(session="b", turn="t1")
        for i in range(4):
            self.read_note(f"memory/n{i}.md", "a")
        self.notice_for("a")
        for i in range(4):
            self.write(f"memory/n{i}.md", note(f"n{i}", f"note {i}", "second"), session="b", turn="t2")
        self.stop(session="b", turn="t2")
        lines = [line for line in self.notice_for("a").splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("4 notes changed", lines[0])

    def test_never_more_than_five_lines(self):
        for i in range(9):
            self.write_and_capture(f"memory/n{i}.md", note(f"n{i}", f"note {i}", "first"),
                                   session="b", turn=f"t{i}")
            self.read_note(f"memory/n{i}.md", "a")
        self.notice_for("a")
        for i in range(9):
            self.write_and_capture(f"memory/n{i}.md", note(f"n{i}", f"note {i}", "second"),
                                   session="b", turn=f"u{i}")
        lines = [line for line in self.notice_for("a").splitlines() if line.startswith("- ")]
        self.assertLessEqual(len(lines), watch.MAX_LINES + 1)  # +1 for the "and N more" line
        self.assertIn("more change", lines[-1])

    def test_watch_command_reports_a_session_offset_and_focus(self):
        """The CLI path: it broke once by unpacking focus() wrongly, which no hook test would catch."""
        self.write_and_capture("memory/cursor_work.md", cursor("cursor-work", "step one", "body"),
                               session="b", turn="t1")
        self.notice_for("a")
        out = subprocess.run(["python3", str(RW), "watch", "--session", "a"],
                             capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("session   a", out.stdout)
        self.assertIn("1 cursor(s)", out.stdout)

    # -- the session-start cursor block ------------------------------------

    def test_session_start_says_when_each_cursor_last_moved_and_why(self):
        """The reason is quoted from the conversation that moved the cursor, so a transcript is needed."""
        path = self.tmp / "t.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in [
            {"type": "user", "promptId": "t1", "timestamp": ts(10),
             "message": {"role": "user", "content": "move the work cursor to step two"}},
            {"type": "assistant", "timestamp": ts(9),
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Moved it."}]}},
        ]) + "\n")
        text_note = cursor("cursor-work", "step two", "body")
        (self.home / "memory/cursor_work.md").write_text(text_note)
        self.hook("capture", {**self.payload("Write", self.home / "memory/cursor_work.md",
                                             session="b", turn="t1", content=text_note),
                              "transcript_path": str(path)})
        self.hook("stop", {"session_id": "b", "prompt_id": "t1", "cwd": "/work/api",
                           "transcript_path": str(path)})
        output = self.hook("session-start", {"session_id": "a"})
        text = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("cursor-work: step two", text)
        self.assertIn("[moved", text)
        self.assertIn("move the work cursor to step two", text)

    def test_a_cursor_with_no_recorded_reason_still_lists_its_description(self):
        (self.home / "memory" / "cursor_work.md").write_text(cursor("cursor-work", "step one", "body"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "memory: add cursor by hand")
        output = self.hook("session-start", {"session_id": "a"})
        text = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("cursor-work: step one", text)
        self.assertNotIn("[moved", text)

    def test_generated_views_are_not_reported(self):
        self.write_and_capture("memory/one.md", note("one", "first", "body"), session="b", turn="t1")
        self.read_note("memory/MEMORY.md", "a")
        self.read_note("memory/index-api.md", "a")
        self.notice_for("a")
        self.write_and_capture("memory/two.md", note("two", "second", "body"), session="b", turn="t2")
        text = self.notice_for("a")
        self.assertNotIn("MEMORY", text)
        self.assertNotIn("index-api", text)


if __name__ == "__main__":
    unittest.main()
