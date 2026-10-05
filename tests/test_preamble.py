"""Tests for `rw.py preamble`: the orientation a session is given, printed on demand.

The point of the command is that it cannot disagree with the hooks, so the test that matters is the
one asserting both render the same bytes. Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import unittest

from test_hooks import RW, HookTestCase, note


class PreambleTests(HookTestCase):
    def setUp(self):
        super().setUp()
        (self.home / "AGENTS.md").write_text("# rules\n\nOne copy, edited here only.\n")
        (self.home / "memory" / "index-api.md").write_text("# api index\n\n- [one](project_one.md): a fact\n")
        (self.home / "memory" / "project_one.md").write_text(note("one", "a fact", "Body. commit:abc1234"))
        (self.home / "memory" / "cursor_api.md").write_text(
            "---\nname: cursor-api\ndescription: where the api work stands; NEXT = ship it\n"
            "metadata:\n  type: cursor\n  area: api\n---\n\nPosition.\n"
        )
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "seed")

    def preamble(self, *args):
        result = subprocess.run(
            ["python3", str(RW), "preamble", *args],
            capture_output=True, text=True, env=self.env(), check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, result.stderr

    def test_prints_the_blocks_a_session_receives(self):
        out, err = self.preamble("--cwd", str(self.tmp))
        self.assertIn("Rules from", out)
        self.assertIn("One copy, edited here only.", out)
        self.assertIn("Where things stand", out)
        self.assertIn("cursor-api: where the api work stands; NEXT = ship it", out)
        # stdout is the context only; the sizes are reporting and belong on stderr
        self.assertNotIn("characters in", out)
        self.assertIn("rules", err)
        self.assertIn("total", err)

    def test_cwd_selects_the_area_index(self):
        work = self.tmp / "work" / "api"
        work.mkdir(parents=True)
        out, _ = self.preamble("--cwd", str(work))
        self.assertIn("Memory index for this working directory", out)
        self.assertIn("# api index", out)
        # a directory with no matching index gets the rules and cursors, but no index block
        other = self.tmp / "work" / "unrelated"
        other.mkdir(parents=True)
        out, _ = self.preamble("--cwd", str(other))
        self.assertNotIn("# api index", out)
        self.assertIn("Rules from", out)

    def test_agrees_with_the_hooks_byte_for_byte(self):
        """The command and the two SessionStart hooks must render the same text."""
        work = self.tmp / "work" / "api"
        work.mkdir(parents=True)
        out, _ = self.preamble("--cwd", str(work))

        start = self.hook("session-start", {"session_id": "s9", "cwd": str(work), "transcript_path": ""})
        area = self.hook("session-area", {"session_id": "s9", "cwd": str(work), "transcript_path": ""})
        from_hooks = "\n\n".join([
            start["hookSpecificOutput"]["additionalContext"],
            area["hookSpecificOutput"]["additionalContext"],
        ])
        self.assertEqual(out.rstrip("\n"), from_hooks)

    def test_stable_makes_two_runs_identical(self):
        work = self.tmp / "work" / "api"
        work.mkdir(parents=True)
        # move the cursor so its line carries an elapsed time
        (self.home / "memory" / "cursor_api.md").write_text(
            "---\nname: cursor-api\ndescription: moved on; NEXT = ship it\n"
            "metadata:\n  type: cursor\n  area: api\n---\n\nPosition.\n"
        )
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "memory(api): update cursor-api")
        first, _ = self.preamble("--cwd", str(work), "--stable")
        second, _ = self.preamble("--cwd", str(work), "--stable")
        self.assertEqual(first, second)
        self.assertNotIn(" ago", first.replace("<elapsed> ago", ""))

    def test_writes_nothing(self):
        """Rendering is pure: no commit, no state, no index rebuild."""
        before = self.git("rev-parse", "HEAD").stdout.strip()
        tracked = sorted(p.name for p in (self.home / "memory").iterdir())
        self.preamble("--cwd", str(self.tmp))
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(sorted(p.name for p in (self.home / "memory").iterdir()), tracked)
        self.assertEqual(self.git("status", "--short").stdout, "")

    def test_reports_a_missing_home(self):
        env = dict(self.env(), RECEIPTS_WIKI_HOME=str(self.tmp / "nowhere"))
        result = subprocess.run(["python3", str(RW), "preamble"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("there is no memory home", result.stdout)


if __name__ == "__main__":
    unittest.main()
