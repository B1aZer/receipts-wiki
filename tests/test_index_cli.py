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


    def test_cursor_note_is_fenced_out_of_area_indexes_into_its_own_block(self):
        self.write_and_capture("memory/project_ttl.md", note("quotes-cache-ttl", "quotes cache TTL is 5 minutes", "Body."))
        cursor = note("cursor-posthog", "next: send the intro", "Body.").replace("type: project", "type: cursor").replace("area: api", "area: posthog")
        self.write_and_capture("memory/cursor_posthog.md", cursor)
        root = (self.home / "memory" / "MEMORY.md").read_text()
        self.assertIn("## Where things stand", root)
        self.assertIn("- [cursor-posthog](cursor_posthog.md): next: send the intro", root)
        self.assertFalse((self.home / "memory" / "index-posthog.md").exists(), "cursor must not create or populate an area index")
        self.assertNotIn("cursor_posthog.md", (self.home / "memory" / "index-api.md").read_text())
        self.assertIn("project_ttl.md", (self.home / "memory" / "index-api.md").read_text())


class CommandTests(HookTestCase):
    def cli(self, *args):
        result = subprocess.run(["python3", str(RW), *args], capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_record_commits_everything_uncommitted_under_the_given_agent(self):
        (self.home / "memory" / "imported.md").write_text(note("imported", "copied from an old project", "Body."))
        (self.home / ".gitignore").write_text("sessions/\n.state/\n")
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

    def test_find_ranks_notes_across_areas_and_names_the_cursor(self):
        memory = self.home / "memory"
        (memory / "project_ingest.md").write_text(note("posthog-ingestion", "PostHog ingestion consumer crash", "Kafka partition stalls on a poison pill.").replace("area: api", "area: general"))
        (memory / "project_ttl.md").write_text(note("quotes-cache-ttl", "quotes cache TTL", "Five minutes."))
        (memory / "cursor_posthog.md").write_text("---\nname: cursor-posthog\ndescription: PR open; NEXT = find a reviewer\n"
                                                 "metadata:\n  type: cursor\n  area: general\n---\n\nSee [[posthog-ingestion]].\n")
        output = self.cli("find", "kafka", "poison", "pill")
        memory = memory.resolve()
        self.assertIn(str(memory / "project_ingest.md"), output)
        self.assertIn("area general, matched: kafka, pill, poison", output)
        self.assertNotIn("project_ttl.md", output)
        self.assertIn(f"Cursor for this work: {memory / 'cursor_posthog.md'}: PR open; NEXT = find a reviewer", output)
        self.assertIn("no note matches", self.cli("find", "zebra"))

    def test_lint_sweeps_every_note_with_named_rules_and_speaks_json(self):
        memory = self.home / "memory"
        (memory / "project_big.md").write_text(note("big-note", "a log", "x" * 13000 + "\n\nSee [[other-note]]."))
        (memory / "project_other.md").write_text(note("other-note", "linked", "Body. See [[big-note]]."))
        (memory / "project_lonely.md").write_text(note("lonely-note", "nothing links it", "Body."))
        output = self.cli("lint")
        self.assertIn("## Rules over every note", output)
        self.assertIn("**note-too-big**", output)
        self.assertIn("memory/project_big.md is 13 KB", output)
        self.assertIn("**orphan-note**", output)
        self.assertIn("memory/project_lonely.md has no [[link]] in or out", output)
        self.assertNotIn("project_other.md has no", output)

        report = json.loads(self.cli("lint", "--json"))
        self.assertEqual(report["counts"]["rules"], len(report["rules"]))
        rules = {hit["rule"] for hit in report["rules"]}
        # None of the three was committed, so no index lists them either.
        self.assertEqual(rules, {"note-too-big", "orphan-note", "index-unlisted"})
        self.assertIn("orphan-note", report["rule_descriptions"])
        self.assertEqual({hit["file"] for hit in report["rules"] if hit["rule"] == "orphan-note"}, {"memory/project_lonely.md"})

    def test_orphan_findings_suggest_the_notes_they_belong_with(self):
        memory = self.home / "memory"
        # Word statistics need a corpus: in a three-note home every word looks rare.
        for i, topic in enumerate(["tls renewal", "disk quota", "cdn cache", "queue depth", "vpn tunnel",
                                   "image registry", "canary share", "sso session", "backup window", "cron drift"]):
            (memory / f"project_ops{i}.md").write_text(note(f"ops-{i}", f"{topic} setting for service {i}", "Body."))
        (memory / "project_dune_credits.md").write_text(note("dune-credits", "Dune credits: download is the killer, not execution", "Body."))
        (memory / "project_dune_download.md").write_text(note("dune-download", "Dune download costs credits per megabyte, not per execution", "Body."))
        (memory / "project_pager.md").write_text(note("pager-rota", "who is on call and how the rota rotates", "Body."))
        report = json.loads(self.cli("lint", "--json"))
        suggested = {hit["file"]: hit.get("candidates") for hit in report["rules"] if hit["rule"] == "orphan-note"}
        self.assertEqual(suggested["memory/project_dune_credits.md"], ["dune-download"])
        # Scores are asymmetric near the bar, so only the confident direction is asserted.
        self.assertIsNone(suggested["memory/project_pager.md"])
        self.assertIsNone(suggested["memory/project_ops3.md"])
        self.assertIn("Closest notes by wording: [[dune-download]]", self.cli("lint"))

    def test_docs_sweep_reports_documents_in_folders_memory_names(self):
        docs = self.tmp / "project" / "career"
        docs.mkdir(parents=True)
        for name in ("plan.md", "orphan-doc.md", "README.md", "committed.md"):
            (docs / name).write_text(f"# {name}\n")
        self.git("init", "-q", "-b", "main", cwd=docs)
        self.git("add", "committed.md", cwd=docs)
        (self.home / "memory" / "project_plan.md").write_text(
            note("career-plan", "the plan", f"The plan lives in {docs}/plan.md."))

        self.assertNotIn("doc-unnamed", self.cli("lint"))
        output = self.cli("lint", "--docs")
        self.assertIn("**doc-unnamed**", output)
        self.assertIn("orphan-doc.md", output)
        for skipped in ("plan.md,", "README.md", "committed.md"):
            self.assertNotIn(skipped, output)

        report = json.loads(self.cli("lint", "--docs", "--json"))
        files = [hit["file"] for hit in report["rules"] if hit["rule"] == "doc-unnamed"]
        self.assertEqual(files, [str((docs / "orphan-doc.md").resolve())])

    def test_find_json_lists_results_and_cursors(self):
        memory = self.home / "memory"
        (memory / "project_ingest.md").write_text(note("posthog-ingestion", "PostHog ingestion consumer crash", "Kafka poison pill."))
        (memory / "cursor_posthog.md").write_text("---\nname: cursor-posthog\ndescription: PR open; NEXT = reviewer\n"
                                                  "metadata:\n  type: cursor\n  area: general\n---\n\nSee [[posthog-ingestion]].\n")
        report = json.loads(self.cli("find", "kafka", "poison", "--json"))
        self.assertEqual(report["query"], "kafka poison")
        first = report["results"][0]
        self.assertEqual(first["file"], "project_ingest.md")
        self.assertEqual(sorted(first["matched"]), ["kafka", "poison"])
        self.assertEqual([c["name"] for c in report["cursors"]], ["cursor-posthog"])
        self.assertEqual(json.loads(self.cli("find", "zebra", "--json"))["results"], [])

    def test_recall_finds_archived_message(self):
        path = self.tmp / "t.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in BASE))
        self.hook("stop", {"session_id": "s-recall", "prompt_id": "t1", "transcript_path": str(path), "cwd": "/work/api"})
        output = self.cli("recall", "cache", "quotes")
        self.assertIn("never cache quotes", output)
        self.assertIn("session s-recall", output)
        self.assertNotIn("hunter2value", output)

    def test_lint_reports_secrets_receipts_and_forgetting_without_echoing_secrets(self):
        (self.home / ".gitignore").write_text("sessions/\n.state/\n")
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
        (self.home / ".gitignore").write_text("sessions/\n.state/\n")
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
        self.assertIn(".gitignore does not exclude sessions/, .state/", output)
        self.assertIn("memory/a.md links to missing gone.md", output)


if __name__ == "__main__":
    unittest.main()


class IndexAuditTests(HookTestCase):
    """indexer.audit: the standing conditions of the index FILES, which lint reports (nothing else did)."""

    def audit(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from rwlib import indexer
        return indexer.audit(self.home)

    def record_session_cwd(self, session, cwd):
        """Write the session state directly: state.save() resolves the home from the environment."""
        import json as _json
        folder = self.home / ".state" / "sessions"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{session}.json").write_text(_json.dumps({"session": session, "cwd": cwd,
                                                             "reads": {}, "pending": {}}))

    def big_index(self, area, size=9600):
        """Past AREA_INDEX_CHARS. No markdown links in the padding: only the byte count matters here,
        and fake links would raise unrelated "links to missing" problems."""
        path = self.home / "memory" / f"index-{area}.md"
        body = f"# {area} index\n\n"
        path.write_text(body + "padding line, no links\n" * ((size - len(body)) // 23 + 1))
        return path

    def test_reports_an_index_a_session_actually_loads_and_is_truncated(self):
        self.big_index("api")
        self.record_session_cwd("s9", "/work/api")
        found = " ".join(self.audit())
        self.assertIn("index-api.md", found)
        self.assertIn("/work/api", found)
        self.assertIn("silently dropped", found)

    def test_stays_quiet_about_a_big_index_no_session_loads(self):
        """A sub-index nothing auto-loads may be long; warning about it would be noise."""
        self.big_index("api")
        found = " ".join(self.audit())
        self.assertNotIn("silently dropped", found)

    def test_reports_a_hand_written_index_that_holds_real_notes(self):
        (self.home / "memory" / "index-api.md").write_text("# api index\n\n- [a-note](a.md) — by hand\n")
        self.write_and_capture("memory/a.md", note("a-note", "api note", "Body."))
        found = " ".join(self.audit())
        self.assertIn("written by hand", found)
        self.assertIn("area 'api'", found)

    def test_says_nothing_about_a_generated_index(self):
        self.write_and_capture("memory/a.md", note("a-note", "api note", "Body."))
        self.assertEqual([w for w in self.audit() if "written by hand" in w], [])

    def test_lint_surfaces_them_as_warnings(self):
        self.big_index("api")
        self.record_session_cwd("s9", "/work/api")
        out = subprocess.run(["python3", str(RW), "lint"], capture_output=True, text=True,
                             env=self.env(), check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("index-api.md", out.stdout)
        self.assertIn("silently dropped", out.stdout)


class CursorStatusRuleTests(HookTestCase):
    """cursor-ended-in-prose: a cursor saying the work ended while its status still says active."""

    def cursor(self, name, description, status=None):
        extra = f"  status: {status}\n" if status else ""
        return (f"---\nname: {name}\ndescription: {description}\nmetadata:\n"
                f"  type: cursor\n  area: api\n{extra}---\n\nBody.\n")

    def lint(self):
        out = subprocess.run(["python3", str(RW), "lint"], capture_output=True, text=True,
                             env=self.env(), check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_flags_a_closed_cursor_still_marked_active(self):
        self.write_and_capture("memory/cursor_gone.md", self.cursor("cursor-gone", "REJECTED at the screen; CLOSED"))
        out = self.lint()
        self.assertIn("cursor-ended-in-prose", out)
        self.assertIn("cursor_gone.md", out)

    def test_says_nothing_once_the_cursor_is_retired(self):
        self.write_and_capture("memory/cursor_gone.md",
                               self.cursor("cursor-gone", "REJECTED at the screen; CLOSED", status="retired"))
        self.assertNotIn("cursor-ended-in-prose", self.lint())

    def test_says_nothing_about_a_live_cursor(self):
        self.write_and_capture("memory/cursor_live.md", self.cursor("cursor-live", "PR open; NEXT = find a reviewer"))
        self.assertNotIn("cursor-ended-in-prose", self.lint())

    def test_does_not_fire_on_an_ordinary_note(self):
        self.write_and_capture("memory/project_x.md", note("project-x", "the bid was REJECTED and the lane CLOSED", "Body."))
        self.assertNotIn("cursor-ended-in-prose", self.lint())


class DuplicateFieldRuleTests(HookTestCase):
    """field-duplicated: a note restating name/description inside metadata, where nothing reads it."""

    def lint(self):
        out = subprocess.run(["python3", str(RW), "lint"], capture_output=True, text=True,
                             env=self.env(), check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_flags_a_metadata_description_that_differs(self):
        self.write_and_capture("memory/a.md", note("a-note", "the real one", "Body.",
                                                   extra='  description: a different one\n'))
        out = self.lint()
        self.assertIn("field-duplicated", out)
        self.assertIn("a different one", out)

    def test_ignores_an_identical_copy(self):
        self.write_and_capture("memory/a.md", note("a-note", "the same", "Body.",
                                                   extra='  description: the same\n'))
        self.assertNotIn("field-duplicated", self.lint())

    def test_ignores_a_note_without_the_duplicate(self):
        self.write_and_capture("memory/a.md", note("a-note", "only one", "Body."))
        self.assertNotIn("field-duplicated", self.lint())
