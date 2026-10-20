#!/usr/bin/env python3
"""Cache policy + run-writing policy tests. Offline: the GitHub API is mocked.

Run:  python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "generate-lang-stats.py")

REPOS = [
    {"name": f"repo{i}", "owner": {"login": "someone"}, "private": False,
     "stargazers_count": 1, "forks_count": 0, "open_issues_count": 0}
    for i in range(4)
]
LANGS = {"Python": 1000, "Go": 500}


def load_module():
    spec = importlib.util.spec_from_file_location("lang_stats_cache", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CachePolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mod = load_module()
        self.mod.DB_PATH = os.path.join(self.tmp.name, "lang-stats.db")
        self.mod.CACHE_PATH = os.path.join(self.tmp.name, "lang-cache.json")
        self.calls = 0
        self.empty_repos = set()
        self._orig_fetch_all = self.mod.fetch_all_repos
        self._orig_fetch_langs = self.mod.fetch_repo_languages
        self.mod.fetch_all_repos = lambda username, token: [dict(r) for r in REPOS]

        def fake_langs(owner, repo, token):
            self.calls += 1
            return {} if repo in self.empty_repos else dict(LANGS)

        self.mod.fetch_repo_languages = fake_langs

    def tearDown(self):
        self.mod.fetch_all_repos = self._orig_fetch_all
        self.mod.fetch_repo_languages = self._orig_fetch_langs
        self.tmp.cleanup()

    # ── helpers ──────────────────────────────────────────────────
    def seed_cache(self, age_minutes, names=None):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
        cache = {n: {"_ts": ts, **LANGS} for n in (names or [r["name"] for r in REPOS])}
        with open(self.mod.CACHE_PATH, "w") as f:
            json.dump(cache, f)
        return cache

    def collect(self, cache, **kw):
        self.calls = 0
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            result = self.mod.collect_and_store(
                "someone", "tok", cache, kw.get("no_cache", False),
                kw.get("reuse_missing", False), cache_ttl=kw.get("cache_ttl", None))
        return result, buf.getvalue()

    def run_count(self):
        conn = sqlite3.connect(self.mod.DB_PATH)
        try:
            return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            conn.close()

    # ── tests ────────────────────────────────────────────────────
    def test_fresh_cache_makes_no_api_calls(self):
        cache = self.seed_cache(5)
        (run_id, langs, total, collected_at), _ = self.collect(cache)
        self.assertEqual(self.calls, 0)
        self.assertEqual(dict(langs)["Python"], len(REPOS) * 1000)
        self.assertEqual(self.run_count(), 1)
        self.assertTrue(collected_at and collected_at[:2] == "20")

    def test_expired_cache_refetches(self):
        cache = self.seed_cache(40)   # older than the 30-minute default TTL
        (run_id, _, _, _), _ = self.collect(cache)
        self.assertEqual(self.calls, len(REPOS), "expired entries must be refetched")

    def test_rerender_does_not_add_a_run(self):
        """Re-rendering with only display options changed must not touch history."""
        cache = self.seed_cache(5)
        first, _ = self.collect(cache)          # writes run 1
        second, out = self.collect(cache)       # same data, no API call
        self.assertEqual(first[0], 1)
        self.assertEqual(second[0], 1, "run id must be reused, not a new row")
        self.assertEqual(second[3], first[3],
                         "reused run must keep its own collection timestamp")
        self.assertEqual(self.run_count(), 1)
        self.assertIn("no new run written", out)

    def test_new_repo_in_list_writes_a_run_even_without_api_calls(self):
        cache = self.seed_cache(5)
        self.collect(cache)
        extra = {"name": "repo-new", "owner": {"login": "someone"},
                 "private": False, "stargazers_count": 0, "forks_count": 0,
                 "open_issues_count": 0}
        self.mod.fetch_all_repos = lambda username, token: [dict(r) for r in REPOS] + [extra]
        cache["repo-new"] = {"_ts": datetime.now(timezone.utc).isoformat(), **LANGS}
        self.collect(cache)
        self.assertEqual(self.run_count(), 2, "changed repo set must be recorded")

    def test_known_empty_repo_is_not_refetched(self):
        self.empty_repos = {"repo0"}
        cache = {}
        self.collect(cache)
        self.assertEqual(self.calls, len(REPOS))
        self.assertTrue(cache["repo0"].get("_empty"), "empty result must be cached")

        # Age every normal entry past the TTL but leave the negative entry fresh:
        # only the known-empty repo should be spared a request.
        old = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
        for entry in cache.values():
            if not entry.get("_empty"):
                entry["_ts"] = old

        self.collect(cache)
        self.assertEqual(self.calls, len(REPOS) - 1,
                         "known-empty repo must be served from cache")

    def test_cache_ttl_zero_disables_cache(self):
        cache = self.seed_cache(1)
        (_, _, _, _), out = self.collect(cache, cache_ttl=0)
        self.assertEqual(self.calls, len(REPOS))
        self.assertIn("Cache: disabled", out)

    def test_custom_ttl_can_be_shorter_than_entry_age(self):
        cache = self.seed_cache(10)
        (_, _, _, _), _ = self.collect(cache, cache_ttl=5)   # 10 min old > 5 min TTL
        self.assertEqual(self.calls, len(REPOS))

    def test_cache_summary_counts_fresh_and_empty(self):
        cache = self.seed_cache(5, names=["repo0", "repo1"])
        cache["repo2"] = {"_ts": datetime.now(timezone.utc).isoformat(), "_empty": True}
        cache["repo3"] = {"_ts": (datetime.now(timezone.utc)
                                  - timedelta(minutes=90)).isoformat(), **LANGS}
        self.mod.save_cache(cache)
        entries, fresh, empties, oldest = self.mod.cache_summary(cache, 30)
        self.assertEqual(entries, 4)
        self.assertEqual(fresh, 3)     # two normal + one known-empty
        self.assertEqual(empties, 1)
        self.assertGreater(oldest, 89)


if __name__ == "__main__":
    unittest.main(verbosity=2)
