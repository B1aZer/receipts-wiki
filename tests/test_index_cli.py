"""Tests for generated indexes and the record, history, recall and lint commands."""
import json
import os
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

    def test_hand_written_index_files_are_never_regenerated(self):
        hand = "# unrekt index\n\n- [bloomer](project_bloomer.md) · [curve](project_curve.md)\n"
        (self.home / "memory" / "index-unrekt.md").write_text(hand)
        self.git("add", "memory/index-unrekt.md")
        self.git("commit", "-q", "-m", "hand-written index")
        self.write_and_capture("memory/a.md", note("a-note", "api note", "Body."), turn="t1")
        self.write_and_capture("memory/b.md", note("b-note", "unrekt note", "Body.").replace("area: api", "area: unrekt"), turn="t2")
        self.hook("session-start", {"session_id": "s2"})
        self.assertEqual((self.home / "memory" / "index-unrekt.md").read_text(), hand)
        self.assertNotIn("index-unrekt.md", self.git("log", "--format=%B", "-3").stdout)
        self.assertIn("a-note", (self.home / "memory" / "index-api.md").read_text())

    def test_gate_and_capture_treat_hand_written_indexes_as_ordinary_files(self):
        hand = self.home / "memory" / "index-unrekt.md"
        hand.write_text("# unrekt index\n\n- [bloomer](project_bloomer.md)\n")
        self.git("add", "memory/index-unrekt.md")
        self.git("commit", "-q", "-m", "hand-written index")
        edited = hand.read_text() + "- [curve](project_curve.md)\n"
        self.assertIsNone(self.hook("gate", self.payload("Write", hand, content=edited)))
        self.write_and_capture("memory/index-unrekt.md", edited)
        self.assertIn("Change: fact.updated memory/index-unrekt.md", self.last_message())
        generated = self.home / "memory" / "index-api.md"
        self.write_and_capture("memory/api.md", note("api-note", "api note", "Body."), turn="t2")
        denied = self.hook("gate", self.payload("Write", generated, content="- [x](x.md)"))
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

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


class GitHookTests(HookTestCase):
    def env(self):
        return dict(super().env(), RECEIPTS_WIKI_RW=str(RW))

    def install(self):
        return subprocess.run(["python3", str(RW), "install-git-hook"], capture_output=True, text=True, env=self.env(), check=False)

    def run_git(self, *args):
        return subprocess.run(["git", "-C", str(self.home), *args], capture_output=True, text=True, env=self.env(), check=False)

    def test_install_is_repeatable_and_keeps_other_hooks(self):
        self.assertEqual(self.install().returncode, 0)
        hook = self.home / ".git" / "hooks" / "pre-commit"
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertEqual(self.install().returncode, 0)
        hook.write_text("#!/bin/sh\nexit 0\n")
        result = self.install()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not written by receipts-wiki", result.stdout)
        self.assertEqual(hook.read_text(), "#!/bin/sh\nexit 0\n")

    def test_hook_blocks_secrets_and_missing_frontmatter_in_commits_made_by_hand(self):
        self.install()
        leak = self.home / "memory" / "leak.md"
        leak.write_text(note("leak", "db access", "PGPASSWORD=hunter2value psql"))
        self.run_git("add", "memory/leak.md")
        blocked = self.run_git("commit", "-m", "by hand")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("contains a secret value", blocked.stderr)
        self.assertNotIn("hunter2value", blocked.stderr)
        self.run_git("rm", "-q", "--cached", "memory/leak.md")
        leak.unlink()
        bare = self.home / "memory" / "bare.md"
        bare.write_text("Just text.\n")
        self.run_git("add", "memory/bare.md")
        self.assertIn("has no frontmatter", self.run_git("commit", "-m", "by hand").stderr)
        bare.write_text(note("bare", "now with frontmatter", "Body."))
        self.run_git("add", "memory/bare.md")
        self.assertEqual(self.run_git("commit", "-q", "-m", "by hand").returncode, 0)

    def test_turn_commit_rejected_by_the_hook_is_reported(self):
        self.install()
        path = self.home / "memory" / "leak.md"
        path.write_text(note("leak", "db access", "PGPASSWORD=hunter2value psql"))
        self.hook("capture", self.payload("Write", path))
        output = self.stop()
        self.assertIn("contains a secret value", output["systemMessage"])
        self.assertNotIn("hunter2value", output["systemMessage"])
        self.assertEqual(self.commit_count(), 1)


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

    def test_lint_accepts_receipts_cited_in_the_text(self):
        (self.home / ".gitignore").write_text("sessions/\nproposals/\n.state/\n")
        cited = {
            "commit.md": "Fixed in commit a1b2c3d on 2026-09-02.",
            "path.md": "The gate lives in `scripts/rwlib/hooks.py`.",
            "ticket.md": "Raised under ticket PARTNER-812.",
            "query.md": "Measured with query q_8812: 14 of 200 stale.",
            "statement.md": "The game is called Hateg Island.\n\nReceipts: user statement",
        }
        for name, body in cited.items():
            (self.home / "memory" / name).write_text(note(name[:-3], "cited", body))
        (self.home / "memory" / "bare.md").write_text(note("bare", "no evidence", "Run the numbers again sometime, dated 2026-09-02."))
        output = self.cli("lint")
        for name in cited:
            self.assertNotIn(f"memory/{name} is a project note without receipts", output)
        self.assertIn("memory/bare.md is a project note without receipts", output)

    def test_lint_flags_missing_gitignore_and_broken_links(self):
        self.write_and_capture("memory/a.md", note("a", "cache", "See [missing](gone.md)."))
        output = self.cli("lint")
        self.assertIn(".gitignore does not exclude sessions/, proposals/, .state/", output)
        self.assertIn("memory/a.md links to missing gone.md", output)


if __name__ == "__main__":
    unittest.main()
