"""Tests for generated indexes and the record, history, recall and lint commands."""
import json
import subprocess
import unittest

from test_hooks import RW, HookTestCase, note
from test_session import BASE


class IndexTests(HookTestCase):
    def test_turn_commit_includes_area_index_and_root_block(self):
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "quotes cache TTL is 5 minutes", "Body."))
        line = "- [quotes-cache-ttl](project_ttl.md): quotes cache TTL is 5 minutes"
        self.assertIn(line, (self.home / "memory" / "index-api.md").read_text())
        root = (self.home / "memory" / "MEMORY.md").read_text()
        self.assertIn("## Notes", root)
        self.assertIn("api:\n" + line, root)
        message = self.last_message()
        self.assertIn("Change: index.rebuilt memory/index-api.md", message)
        self.assertIn("Change: index.rebuilt memory/MEMORY.md", message)
        self.assertEqual(self.commit_count(), 2)

    def test_large_memory_lists_areas_instead_of_notes(self):
        for index in range(160):
            area = ("api", "infra", "tooling")[index % 3]
            text = note(f"note-{index}", f"a description long enough to fill the budget, number {index}", "Body.").replace("area: api", f"area: {area}")
            (self.home / "memory" / f"note_{index}.md").write_text(text)
        subprocess.run(["python3", str(RW), "build-index", "--no-commit"], capture_output=True, text=True, env=self.env(), check=True)
        root = (self.home / "memory" / "MEMORY.md").read_text()
        self.assertIn("## Areas", root)
        self.assertIn("- [api](index-api.md): 54 notes", root)
        self.assertNotIn("note_1.md", root)
        self.assertLessEqual(root.count("\n"), 150)

    def test_retired_note_leaves_index_and_hand_written_root_text_survives(self):
        (self.home / "memory" / "MEMORY.md").write_text("# Memory map\n\nHand-written line.\n")
        self.git("add", "memory/MEMORY.md")
        self.git("commit", "-q", "-m", "hand-written map")
        rel = "memory/project_ttl.md"
        text = note("quotes-cache-ttl", "ttl", "Body.")
        self.write_and_capture(rel, text, turn="t1")
        self.write_and_capture(rel, text.replace("  area: api\n", "  area: api\n  status: retired\n"), turn="t2")
        self.assertNotIn("project_ttl.md", (self.home / "memory" / "index-api.md").read_text())
        self.assertIn("Hand-written line.", (self.home / "memory" / "MEMORY.md").read_text())


class CommandTests(HookTestCase):
    def cli(self, *args):
        result = subprocess.run(["python3", str(RW), *args], capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_record_commits_everything_uncommitted_under_the_given_agent(self):
        (self.home / "memory" / "imported.md").write_text(note("imported", "copied from an old project", "Body."))
        (self.home / ".gitignore").write_text("sessions/\nproposals/\n.state/\n")
        output = self.cli("record", "--agent", "receipts-wiki-setup")
        self.assertIn("committed 2 change(s)", output)
        message = self.last_message()
        self.assertIn("Change: external.change memory/imported.md", message)
        self.assertIn("Change: external.change .gitignore", message)
        self.assertIn("Change: index.rebuilt memory/index-api.md", message)
        self.assertIn("Agent: receipts-wiki-setup", message)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

    def test_record_on_an_empty_home_creates_memory_md(self):
        (self.home / "AGENTS.md").write_text("# AGENTS.md\n")
        self.cli("record", "--agent", "receipts-wiki-setup")
        self.assertIn("No notes yet.", (self.home / "memory" / "MEMORY.md").read_text())
        message = self.last_message()
        self.assertIn("Change: external.change AGENTS.md", message)
        self.assertIn("Change: index.rebuilt memory/MEMORY.md", message)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

    def test_hand_edit_of_memory_md_is_recorded_as_external(self):
        (self.home / "memory" / "MEMORY.md").write_text("# Memory map\n\nEdited by hand.\n")
        self.hook("session-start", {"session_id": "s9"})
        self.assertIn("Change: external.change memory/MEMORY.md", self.last_message())

    def test_history_shows_supersession_in_order(self):
        rel = "memory/project_ttl.md"
        text = note("quotes-cache-ttl", "ttl", "The API cache TTL caused stale quotes.")
        self.write_and_capture(rel, text, turn="t1")
        self.write_and_capture(rel, text.replace(
            "The API cache TTL caused stale quotes.",
            "CDN edge cache.\n\nSupersedes (2026-09-16): the API cache TTL caused stale quotes. 12 of 200 still stale"), turn="t2")
        output = self.cli("history", "quotes-cache-ttl")
        self.assertIn("add quotes-cache-ttl", output)
        self.assertIn("supersede quotes-cache-ttl", output)
        self.assertIn("rejected(quotes-cache-ttl): the API cache TTL caused stale quotes", output)
        self.assertLess(output.index("add quotes-cache-ttl"), output.index("supersede quotes-cache-ttl"))

    def test_recall_finds_archived_message(self):
        path = self.tmp / "t.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in BASE))
        self.hook("stop", {"session_id": "s-recall", "prompt_id": "t1", "transcript_path": str(path), "cwd": "/work/api"})
        output = self.cli("recall", "cache", "quotes")
        self.assertIn("never cache quotes", output)
        self.assertIn("session s-recall", output)
        self.assertNotIn("hunter2value", output)

    def test_lint_reports_secrets_receipts_and_forgetting_without_echoing_secrets(self):
        (self.home / ".gitignore").write_text("sessions/\nproposals/\n.state/\n")
        self.write_and_capture("memory/old.md", note("old-fact", "an old fact", "Body.", extra="  last_verified: 2025-01-01\n"))
        (self.home / "memory" / "leak.md").write_text(note("leak", "has a key", "token: abcdefghijklmnopqrstuvwxyz123456"))
        output = self.cli("lint")
        self.assertIn("memory/leak.md contains a secret value", output)
        self.assertIn("memory/old.md is a project note without receipts", output)
        self.assertIn("memory/old.md: last verified 2025-01-01", output)
        self.assertIn("uncommitted changes", output)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", output)
        self.assertNotIn(".gitignore does not exclude", output)

    def test_lint_flags_missing_gitignore_and_broken_links(self):
        self.write_and_capture("memory/a.md", note("a", "cache", "See [missing](gone.md)."))
        output = self.cli("lint")
        self.assertIn(".gitignore does not exclude sessions/, proposals/, .state/", output)
        self.assertIn("memory/a.md links to missing gone.md", output)


if __name__ == "__main__":
    unittest.main()
