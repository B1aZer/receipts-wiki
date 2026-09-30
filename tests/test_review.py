"""Tests for dependency invalidation (PLAN-log-first §3.4): a supersede marks the notes that depend on it.

Run: python3 -m unittest discover -s tests -v
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from test_hooks import RW, HookTestCase, note

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rwlib import review  # noqa: E402


def superseded(name, description, body):
    return note(name, description, body + "\n\nSupersedes (2026-09-29): the earlier claim. Evidence: a run.")


class ReviewTests(HookTestCase):
    def cli(self, *args):
        result = subprocess.run(["python3", str(RW), *args], capture_output=True, text=True,
                                env=self.env(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    # -- what counts as a named thing --------------------------------------

    def test_link_targets_issue_numbers_and_identifiers_are_named_things(self):
        found = dict(review.named_things("see [[cursor-work]] and #4821, run `pipeline/run.sh`"))
        self.assertEqual(found.get("cursor-work"), "link")
        self.assertEqual(found.get("#4821"), "issue")
        self.assertEqual(found.get("pipeline/run.sh"), "code")

    def test_a_plain_capitalised_word_is_not_a_named_thing(self):
        """"Rejected" opening a sentence matched half the home when it counted as a name."""
        names = [name for name, _ in review.named_things("Rejected the plan. Everything changed. Confirm later.")]
        self.assertEqual(names, [])

    def test_multi_word_and_internally_capitalised_names_are_kept(self):
        names = [name for name, _ in review.named_things("Dana Ruiz at PayFlow uses the API.")]
        self.assertIn("Dana Ruiz", names)
        self.assertIn("PayFlow", names)
        self.assertIn("API", names)

    def test_names_come_from_the_lines_an_edit_added(self):
        old = "The plan is [[alpha]].\n"
        new = "The plan is [[alpha]].\nSupersedes: now [[beta]].\n"
        names = [name for name, _ in review.changed_things(old, new)]
        self.assertIn("beta", names)
        self.assertNotIn("alpha", names)

    # -- the queue ---------------------------------------------------------

    def test_a_supersede_queues_the_notes_that_link_the_changed_note(self):
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[anchor]] we ship"),
                               turn="t2")
        self.write_and_capture("memory/anchor.md", superseded("anchor", "the anchor", "second"), turn="t3")
        rows = review.queue(self.home)
        self.assertEqual([row["note"] for row in rows], ["memory/dependent.md"])
        self.assertEqual(rows[0]["entries"][0]["event"], "fact.superseded")
        self.assertEqual(rows[0]["entries"][0]["because"], "memory/anchor.md")

    def test_an_ordinary_edit_queues_nothing(self):
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[anchor]] we ship"),
                               turn="t2")
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "reworded"), turn="t3")
        self.assertEqual(review.queue(self.home), [])

    def test_a_note_already_rewritten_after_the_event_is_not_queued(self):
        """The chronology gate: it has had its chance to take the change into account."""
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[anchor]] we ship"),
                               turn="t2")
        self.write_and_capture("memory/anchor.md", superseded("anchor", "the anchor", "second"), turn="t3")
        self.assertTrue(review.queue(self.home))
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[anchor]], updated"),
                               turn="t4")
        self.assertEqual(review.queue(self.home), [])

    def test_a_note_does_not_queue_itself(self):
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        self.write_and_capture("memory/anchor.md", superseded("anchor", "the anchor", "second"), turn="t2")
        self.assertEqual([row["note"] for row in review.queue(self.home)], [])

    def test_a_deleted_note_drops_out_of_the_queue(self):
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[anchor]] we ship"),
                               turn="t2")
        self.write_and_capture("memory/anchor.md", superseded("anchor", "the anchor", "second"), turn="t3")
        (self.home / "memory/dependent.md").unlink()
        self.assertEqual(review.queue(self.home), [])

    # -- the command -------------------------------------------------------

    def test_review_command_reports_the_queue_and_is_empty_by_default(self):
        self.assertIn("nothing waiting", self.cli("review"))
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[anchor]] we ship"),
                               turn="t2")
        self.write_and_capture("memory/anchor.md", superseded("anchor", "the anchor", "second"), turn="t3")
        out = self.cli("review")
        self.assertIn("dependent", out)
        self.assertIn("fact.superseded in anchor", out)
        rows = json.loads(self.cli("review", "--json"))
        self.assertEqual(rows[0]["note"], "memory/dependent.md")

    def test_a_failing_queue_never_blocks_the_commit(self):
        """The queue is derived state; losing it must not cost the change that was just recorded."""
        self.write_and_capture("memory/anchor.md", note("anchor", "the anchor", "first"), turn="t1")
        state_dir = self.home / ".state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "review.json").write_text("{ not json")
        self.write_and_capture("memory/anchor.md", superseded("anchor", "the anchor", "second"), turn="t2")
        self.assertIn("anchor", self.last_message())


if __name__ == "__main__":
    unittest.main()


class StatusEventTests(HookTestCase):
    """A workstream changing state or rank is an event dependents react to (§3.3 + §3.4)."""

    def cursor(self, name, description, body, priority=None, status=None):
        extra = (f"  priority: {priority}\n" if priority is not None else "")
        extra += (f"  status: {status}\n" if status else "")
        return (f"---\nname: {name}\ndescription: {description}\nmetadata:\n"
                f"  type: cursor\n  area: api\n{extra}---\n\n{body}\n")

    def test_a_rank_change_is_a_status_event(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from rwlib import gitlog
        old = self.cursor("cursor-a", "d", "b", priority=1)
        new = self.cursor("cursor-a", "d", "b", priority=2)
        self.assertEqual(gitlog.derive_event("memory/cursor_a.md", old, new), "fact.status")

    def test_a_rank_change_queues_the_notes_that_reference_it(self):
        self.write_and_capture("memory/cursor_a.md", self.cursor("cursor-a", "first", "b", priority=1), turn="t1")
        self.write_and_capture("memory/other.md", note("other", "restates the rank", "cursor-a is second"),
                               turn="t2")
        self.write_and_capture("memory/cursor_a.md", self.cursor("cursor-a", "first", "b", priority=2), turn="t3")
        self.assertEqual([r["note"] for r in review.queue(self.home)], ["memory/other.md"])
        self.assertEqual(review.queue(self.home)[0]["entries"][0]["event"], "fact.status")

    def test_a_rank_change_does_not_queue_notes_sharing_something_the_cursor_merely_mentions(self):
        """The edit is frontmatter only; falling back to every name in the note queued 21 notes for one
        rank change on the live home."""
        self.write_and_capture("memory/topic.md", note("shared-topic", "a topic", "Body."), turn="t1")
        self.write_and_capture("memory/cursor_a.md",
                               self.cursor("cursor-a", "first", "see [[shared-topic]]", priority=1), turn="t2")
        self.write_and_capture("memory/elsewhere.md", note("elsewhere", "unrelated", "also [[shared-topic]]"),
                               turn="t3")
        self.write_and_capture("memory/cursor_a.md",
                               self.cursor("cursor-a", "first", "see [[shared-topic]]", priority=2), turn="t4")
        self.assertEqual(review.queue(self.home), [])

    def test_retiring_still_uses_the_wider_scope(self):
        self.write_and_capture("memory/cursor_a.md", self.cursor("cursor-a", "live", "b"), turn="t1")
        self.write_and_capture("memory/dependent.md", note("dependent", "leans on it", "per [[cursor-a]]"),
                               turn="t2")
        self.write_and_capture("memory/cursor_a.md", self.cursor("cursor-a", "live", "b", status="retired"),
                               turn="t3")
        self.assertEqual([r["note"] for r in review.queue(self.home)], ["memory/dependent.md"])
