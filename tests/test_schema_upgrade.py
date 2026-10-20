#!/usr/bin/env python3
"""Offline tests for the schema self-upgrade logic (no network, no token).

Run:  python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import sqlite3
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "generate-lang-stats.py")


def load_module():
    spec = importlib.util.spec_from_file_location("lang_stats", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Schema exactly as shipped before the star/fork/issue columns existed.
LEGACY_SCHEMA = """
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    total_repos INTEGER,
    public_repos INTEGER,
    private_repos INTEGER,
    total_bytes INTEGER,
    language_count INTEGER
);
CREATE TABLE repo_languages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    repo_name TEXT NOT NULL,
    language TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    UNIQUE(run_id, repo_name, language)
);
CREATE TABLE language_stats (
    run_id INTEGER PRIMARY KEY REFERENCES runs(id),
    stats_json TEXT NOT NULL
);
CREATE TABLE repo_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    repo_name TEXT NOT NULL,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    watchers INTEGER DEFAULT 0,
    size_kb INTEGER DEFAULT 0,
    is_fork INTEGER DEFAULT 0,
    is_private INTEGER DEFAULT 0,
    language TEXT,
    default_branch TEXT,
    created_at TEXT,
    updated_at TEXT,
    pushed_at TEXT,
    UNIQUE(run_id, repo_name)
);
"""


class SchemaUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "lang-stats.db")
        self.mod = load_module()
        self.mod.DB_PATH = self.db
        self.mod.CACHE_PATH = os.path.join(self.tmp.name, "lang-cache.json")

    def tearDown(self):
        self.tmp.cleanup()

    def make_legacy_db(self, with_metadata=False):
        conn = sqlite3.connect(self.db)
        conn.executescript(LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO runs (username, timestamp, total_repos, public_repos,"
            " private_repos, total_bytes, language_count)"
            " VALUES ('Someone','2026-01-01T00:00:00+00:00',3,2,1,1000,2)")
        conn.executemany(
            "INSERT INTO repo_languages (run_id, repo_name, language, bytes)"
            " VALUES (1,?,?,?)",
            [("a", "Python", 600), ("a", "Go", 200), ("b", "Go", 200)])
        conn.execute(
            "INSERT INTO language_stats (run_id, stats_json)"
            " VALUES (1, '{\"Python\": 600, \"Go\": 400}')")
        if with_metadata:
            conn.executemany(
                "INSERT INTO repo_metadata (run_id, repo_name, stars, forks,"
                " open_issues) VALUES (1,?,?,?,?)",
                [("a", 10, 2, 1), ("b", 5, 1, 0)])
        conn.commit()
        conn.close()

    def columns(self, table="runs"):
        conn = sqlite3.connect(self.db)
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        conn.close()
        return cols

    def scalar(self, sql):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()

    def test_legacy_db_is_upgraded_without_data_loss(self):
        self.make_legacy_db()
        before_bytes = self.scalar("SELECT SUM(bytes) FROM repo_languages")

        conn = self.mod.init_db()
        conn.close()

        self.assertIn("total_stars", self.columns())
        self.assertIn("total_forks", self.columns())
        self.assertIn("total_issues", self.columns())
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM runs"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM repo_languages"), 3)
        self.assertEqual(self.scalar("SELECT SUM(bytes) FROM repo_languages"),
                         before_bytes)
        self.assertEqual(self.scalar("SELECT stats_json FROM language_stats"),
                         '{"Python": 600, "Go": 400}')
        self.assertEqual(self.scalar("SELECT total_bytes FROM runs"), 1000)

    def test_upgrade_is_idempotent_and_backs_up_once(self):
        self.make_legacy_db()
        for _ in range(3):
            self.mod.init_db().close()
        backups = [f for f in os.listdir(self.tmp.name) if ".bak-migration-" in f]
        self.assertEqual(len(backups), 1, f"expected 1 backup, got {backups}")
        # The backup still holds the original 8-column schema.
        bconn = sqlite3.connect(os.path.join(self.tmp.name, backups[0]))
        bcols = [r[1] for r in bconn.execute("PRAGMA table_info(runs)")]
        bconn.close()
        self.assertNotIn("total_stars", bcols)

    def test_old_run_totals_backfilled_from_metadata(self):
        self.make_legacy_db(with_metadata=True)
        self.mod.init_db().close()
        self.assertEqual(self.scalar(
            "SELECT total_stars FROM runs WHERE id=1"), 15)
        self.assertEqual(self.scalar(
            "SELECT total_forks FROM runs WHERE id=1"), 3)
        self.assertEqual(self.scalar(
            "SELECT total_issues FROM runs WHERE id=1"), 1)

    def test_fresh_db_has_full_schema(self):
        conn = self.mod.init_db()
        conn.close()
        for col in ("total_stars", "total_forks", "total_issues"):
            self.assertIn(col, self.columns())
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM runs"), 0)

    def test_new_run_appends_and_keeps_history(self):
        self.make_legacy_db()
        conn = self.mod.init_db()
        run_id = self.mod.save_run(conn, "Someone", 3, 2, 1, 0, 0)
        self.mod.save_repo_languages(conn, run_id, "a", {"Rust": 900})
        self.mod.save_language_stats(conn, run_id, [("Rust", 900)])
        conn.execute("UPDATE runs SET total_bytes=900, language_count=1"
                     " WHERE id=?", (run_id,))
        conn.commit()
        conn.close()

        self.assertEqual(run_id, 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM repo_languages"
                                     " WHERE run_id=1"), 3)
        self.assertEqual(self.scalar("SELECT bytes FROM repo_languages"
                                     " WHERE run_id=2"), 900)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM language_stats"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
