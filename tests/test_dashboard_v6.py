import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "dashboard-v6-postgres"


class DashboardV6Tests(unittest.TestCase):
    def test_v6_uses_postgres_api_without_duckdb_or_local_drafts(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("CPLAN Planning Studio V6", html)
        self.assertIn("local database", html)
        self.assertNotIn("duckdb", html.lower())
        self.assertNotIn("jsdelivr", html.lower())
        self.assertIn("/api/activities", app)
        self.assertIn("/api/health", app)
        self.assertIn("method:'PATCH'", app)
        self.assertNotIn("LocalDraftRepository", app)
        self.assertNotIn("localStorage", app)
        self.assertNotIn("PostgreSQL live data", app)

    def test_v6_keeps_v4_analytics_and_is_separate(self):
        self.assertTrue((DASHBOARD / "analytics.js").exists())
        self.assertTrue((ROOT / "pipeline" / "dashboard-v4" / "index.html").exists())
        self.assertNotEqual(DASHBOARD, ROOT / "pipeline" / "dashboard-v4")


if __name__ == "__main__":
    unittest.main()
