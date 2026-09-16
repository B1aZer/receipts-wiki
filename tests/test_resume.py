"""Tests for resume: mining a dead session's archive for un-promoted decisions and next actions."""
import subprocess
import unittest

from test_hooks import RW, HookTestCase, note

ARCHIVE = """---
session: deadsess
title: PostHog push
cwd: /work/posthog
branch: main
transcript: /x.jsonl
---
## 2026-09-16T06:00:00Z assistant (line 120)

We decided the next step is to build the person-merge anon_distinct_id guard as PR3; it is proven live but not yet coded.

## 2026-09-16T06:05:00Z user (line 124)

ok

## 2026-09-16T06:10:00Z assistant (line 130)

The quotes response cache ttl is five minutes to avoid stale prices.
"""


class ResumeTests(HookTestCase):
    def cli(self, *args):
        result = subprocess.run(["python3", str(RW), *args], capture_output=True, text=True, env=self.env(), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def seed(self):
        folder = self.home / "sessions" / "2026" / "09"
        folder.mkdir(parents=True)
        (folder / "deadsess.md").write_text(ARCHIVE)
        # an existing note that already covers the cache-ttl block, so that block is filtered out
        (self.home / "memory" / "n.md").write_text(
            note("quotes-cache-ttl", "quotes cache ttl five minutes stale prices",
                 "The quotes response cache ttl is five minutes to avoid stale prices."))

    def test_resume_surfaces_uncovered_decisions_and_filters_covered(self):
        self.seed()
        out = self.cli("resume", "deadsess")
        self.assertIn("person-merge anon_distinct_id guard as PR3", out)
        self.assertIn("Receipt: session:deadsess#L120", out)
        self.assertNotIn("five minutes to avoid stale prices", out)  # covered by an existing note
        self.assertNotIn("line 124", out)  # too short and no decision signal

    def test_resume_by_cwd_picks_the_session(self):
        self.seed()
        out = self.cli("resume", "--cwd", "/work/posthog")
        self.assertIn("session deadsess", out)

    def test_resume_with_no_archive_is_graceful(self):
        out = self.cli("resume", "whatever")
        self.assertIn("Nothing to resume", out)

    def test_resume_no_match_reports_it(self):
        self.seed()
        out = self.cli("resume", "does-not-exist")
        self.assertIn("No archived session matches", out)


if __name__ == "__main__":
    unittest.main()
