"""Tests for the memory log with reasons: turn ids in the archive and `changes` joining commits to their turn."""
import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_hooks import RW, HookTestCase, note

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rwlib import resume  # noqa: E402


def ts(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def user(text, turn, when):
    return {"type": "user", "promptId": turn, "timestamp": when, "message": {"role": "user", "content": text}}


def assistant(text, when):
    return {"type": "assistant", "timestamp": when, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def tool_result(turn, when):
    return {"type": "user", "promptId": turn, "timestamp": when,
            "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


class ChangesTests(HookTestCase):
    def cli(self, *args):
        result = subprocess.run(["python3", str(RW), *args], capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def transcript(self, records):
        path = self.tmp / "t.jsonl"
        with path.open("a") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return path

    def turn(self, path, session, turn, rel=None, text=None):
        """One agent turn: optionally write a memory note, then end the turn (commit + archive)."""
        if rel:
            (self.home / rel).write_text(text)
            self.hook("capture", {**self.payload("Write", self.home / rel, session=session, turn=turn, content=text),
                                  "transcript_path": str(path)})
        self.hook("stop", {"session_id": session, "prompt_id": turn, "cwd": "/work/api", "transcript_path": str(path)})

    def archive_text(self, session):
        return "".join(p.read_text() for p in sorted((self.home / "sessions").rglob(f"{session}.md")))

    def test_archive_headers_carry_the_turn_across_incremental_reads(self):
        path = self.transcript([user("Cap the quotes cache at five minutes.", "p1", ts(10)),
                                assistant("Setting the cap now.", ts(9))])
        self.turn(path, "s1", "p1")
        # the next read starts at an assistant record: it must still belong to the turn of the last user record
        self.transcript([tool_result("p1", ts(8)), assistant("Done, the cap is five minutes.", ts(7)),
                         user("Now the CDN.", "p2", ts(5))])
        self.turn(path, "s1", "p2")
        text = self.archive_text("s1")
        self.assertRegex(text, r"user \(line 1, turn p1\)\n\nCap the quotes cache")
        self.assertRegex(text, r"assistant \(line 4, turn p1\)\n\nDone, the cap")
        self.assertRegex(text, r"user \(line 5, turn p2\)\n\nNow the CDN")

    def test_resume_reads_headers_with_and_without_turn(self):
        blocks = list(resume._blocks("## 2026-09-16T06:00:00Z assistant (line 120, turn p9)\n\nWith turn.\n\n"
                                     "## 2026-09-16T06:01:00Z user (line 121)\n\nWithout turn.\n"))
        self.assertEqual([(b["line"], b["text"]) for b in blocks], [(120, "With turn."), (121, "Without turn.")])

    def test_changes_joins_a_commit_to_its_turn(self):
        path = self.transcript([
            user("Where should the quotes cache limit live?", "p1", ts(30)),
            assistant("Option 1 keeps it in the note; option 2 moves it to config. Should I do option 1?", ts(29)),
            user("yes do option 1", "p2", ts(20)),
            tool_result("p2", ts(19)),
            assistant("Recorded: the quotes cache limit is five minutes, in the note.", ts(18)),
        ])
        self.turn(path, "s1", "p2", "memory/cache.md", note("quotes-cache", "quotes cache ttl", "Five minutes."))
        rows = json.loads(self.cli("changes", "--json"))
        row = rows[0]
        self.assertEqual((row["session"], row["turn"], row["joined_by"]), ("s1", "p2", "turn"))
        self.assertEqual(row["prompt"], "yes do option 1")
        self.assertIn("Should I do option 1?", row["answered"])
        self.assertIn("in the note", row["result"])
        text = self.cli("changes")
        self.assertIn('prompt:   "yes do option 1"', text)
        self.assertIn('answered: "', text)
        self.assertNotIn("joined by time", text)

    def test_long_prompt_needs_no_answered_quote(self):
        path = self.transcript([
            assistant("Anything else?", ts(30)),
            user("Please record that the quotes cache must never hold prices longer than five minutes, "
                 "because the exchange rejects stale quotes.", "p1", ts(20)),
            assistant("Recorded.", ts(19)),
        ])
        self.turn(path, "s1", "p1", "memory/cache.md", note("quotes-cache", "quotes cache ttl", "Five minutes."))
        row = json.loads(self.cli("changes", "--json"))[0]
        self.assertIsNone(row["answered"])
        self.assertEqual(row["result"], "Recorded.")

    def test_archive_without_turn_ids_is_joined_by_time(self):
        self.write_and_capture("memory/cache.md", note("quotes-cache", "quotes cache ttl", "Five minutes."), session="old")
        folder = self.home / "sessions" / ts(0)[:4] / ts(0)[5:7]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "old.md").write_text(
            "---\nsession: old\n---\n\n"
            f"## {ts(10)} user (line 3)\n\nCap the quotes cache at five minutes.\n\n"
            f"## {ts(9)} assistant (line 5)\n\nCapped and recorded.\n")
        row = json.loads(self.cli("changes", "--json"))[0]
        self.assertEqual(row["joined_by"], "time")
        self.assertEqual(row["prompt"], "Cap the quotes cache at five minutes.")
        self.assertIn("joined by time", self.cli("changes"))

    def test_commit_made_outside_a_session_says_so(self):
        (self.home / "memory" / "x.md").write_text(note("x-note", "an external edit", "Body."))
        self.cli("record", "--agent", "codex")
        self.assertIn("changed outside a session (codex)", self.cli("changes"))

    def test_note_filter_accepts_the_file_style_name(self):
        path = self.transcript([user("Record the cache limit.", "p1", ts(10)), assistant("Done.", ts(9))])
        self.turn(path, "s1", "p1", "memory/project_quotes_cache.md", note("quotes-cache", "quotes cache ttl", "Five minutes."))
        self.write_and_capture("memory/other.md", note("other", "something else", "Body."), session="s2")
        text = self.cli("changes", "--note", "project-quotes-cache")
        self.assertIn("quotes-cache", text)
        self.assertNotIn("other", text)


if __name__ == "__main__":
    unittest.main()
