"""Tests for the action log (PLAN-log-first §3.10): what a turn did, beside what it said.

Run: python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

from test_hooks import HookTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rwlib import actions  # noqa: E402


def call(tool, turn="t1", response=None, **tool_input):
    return {"tool_name": tool, "prompt_id": turn, "session_id": "s1",
            "tool_input": tool_input, "tool_response": {} if response is None else response}


class ActionLineTests(unittest.TestCase):
    def test_an_edit_records_its_target(self):
        row = actions.line(call("Edit", file_path="scripts/x.py"))
        self.assertIn("Edit", row)
        self.assertIn("scripts/x.py", row)
        self.assertTrue(row.endswith("ok"))

    def test_a_shell_call_records_the_command(self):
        self.assertIn("python3 -m unittest", actions.line(call("Bash", command="python3 -m unittest discover")))

    def test_a_read_is_not_recorded(self):
        """Reads are half of all calls and rarely explain an outcome."""
        self.assertIsNone(actions.line(call("Read", file_path="README.md")))
        self.assertIsNone(actions.line(call("Grep", pattern="x")))

    def test_failure_is_never_collapsed_to_ok(self):
        row = actions.line(call("Bash", command="false", response={"exit_code": 1, "stderr": "boom"}))
        self.assertIn("ERROR", row)
        row = actions.line(call("Bash", command="x", response={"error": "command not found"}))
        self.assertIn("ERROR: command not found", row)

    def test_stderr_on_a_successful_call_is_kept(self):
        row = actions.line(call("Bash", command="build", response={"exit_code": 0, "stderr": "1 warning"}))
        self.assertIn("ok, stderr: 1 warning", row)

    def test_a_secret_in_a_command_is_redacted(self):
        row = actions.line(call("Bash", command="export API_KEY=sk-live-abcdefghijklmnopqrstuvwx"))
        self.assertNotIn("sk-live-abcdefghijklmnopqrstuvwx", row)
        self.assertIn("REDACTED", row)

    def test_a_command_still_secret_after_redaction_is_withheld_but_recorded(self):
        real = actions.secrets.find_secret
        try:
            actions.secrets.find_secret = lambda text: "provider key"
            row = actions.line(call("Bash", command="something"))
        finally:
            actions.secrets.find_secret = real
        self.assertIn("withheld", row)
        self.assertIn("Bash", row)

    def test_a_long_target_is_truncated(self):
        row = actions.line(call("Bash", command="x " * 500))
        self.assertLessEqual(len(row.split("\t")[3]), actions.TARGET)


class ActionLogTests(HookTestCase):
    def test_the_log_lands_beside_the_conversation_archive(self):
        actions.append(self.home, "s1", call("Write", file_path="memory/a.md"))
        found = list((self.home / "sessions").glob("*/*/s1.actions.tsv"))
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].read_text().startswith("# when\tturn\ttool"))

    def test_it_appends_rather_than_replacing(self):
        for n in range(3):
            actions.append(self.home, "s1", call("Edit", file_path=f"f{n}.py"))
        body = list((self.home / "sessions").glob("*/*/s1.actions.tsv"))[0].read_text().splitlines()
        self.assertEqual(len(body), 4)  # header + three

    def test_actions_can_be_read_back_for_one_turn(self):
        actions.append(self.home, "s1", call("Edit", turn="t1", file_path="a.py"))
        actions.append(self.home, "s1", call("Edit", turn="t2", file_path="b.py"))
        got = actions.between(self.home, "s1", "t1")
        self.assertEqual([a["target"] for a in got], ["a.py"])

    def test_a_read_writes_no_file_at_all(self):
        actions.append(self.home, "s1", call("Read", file_path="README.md"))
        self.assertEqual(list((self.home / "sessions").glob("*/*/*.actions.tsv")), [])

    def test_an_unwritable_home_never_raises_into_the_hook(self):
        self.assertIsNone(actions.append(Path("/nonexistent/place"), "s1", call("Edit", file_path="a.py")))

    def test_the_hook_records_and_stays_silent(self):
        out = self.hook("action", {"session_id": "s1", "prompt_id": "t1", "tool_name": "Edit",
                                   "tool_input": {"file_path": "scripts/x.py"}, "tool_response": {}})
        self.assertIsNone(out, "the action hook must never speak to the agent")
        self.assertTrue(list((self.home / "sessions").glob("*/*/s1.actions.tsv")))


if __name__ == "__main__":
    unittest.main()
