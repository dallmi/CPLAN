import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "dashboard-v6-postgres"

TIME_ZONE_OPTIONS = [
    "Europe/Zurich",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Asia/Singapore",
    "Asia/Hong_Kong",
    "Asia/Tokyo",
    "Australia/Sydney",
    "UTC",
]

# Actual emoji ranges only — deliberately excludes arrows (U+2190-U+21FF) and
# other plain symbols (e.g. the drawer's "x" close glyph) already used as UI text.
EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U00002B00-\U00002BFF]"
)


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

    def test_v6_uses_stable_id_for_row_identity_and_guards_edits(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('data-open-id="${esc(row.tracking_id', app)
        self.assertIn(
            "This activity changed in the database since you opened it. "
            "Your entries are kept — review them, then save again to apply, "
            "or cancel to discard.",
            app,
        )
        self.assertIn("Discard unsaved changes?", app)

    def test_v6_time_zone_select_and_local_time_labels(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('name="time_zone"', html)
        self.assertIn("(local time)", html)
        self.assertIn('<option value="">Not set</option>', html)
        for tz in TIME_ZONE_OPTIONS:
            self.assertIn(f'<option value="{tz}">{tz}</option>', html)

    def test_v6_collision_cache_and_search_debounce_markers(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function collisionsFor(", app)
        self.assertIn("state.collisionsCache", app)
        self.assertIn("function debounce(", app)
        self.assertIn("debounce(runActivityFilters,200)", app.replace(" ", ""))

    def test_v6_empty_state_helper_present(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function emptyState(", app)
        self.assertIn("empty-icon", app)
        self.assertIn("empty-title", app)
        self.assertIn("empty-subtext", app)
        self.assertNotIn('"empty">No data available', app)

    def test_v6_a11y_open_rows_and_focus_trap(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn("setAttribute('tabindex','0')", app)
        self.assertIn("setAttribute('role','button')", app)
        self.assertIn("'Enter'", app)
        self.assertIn('id="drawer-close"', html)

    def test_v6_activities_nav_count_badge(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="activities-count"', html)
        self.assertIn("count-badge", html)
        self.assertIn("function updateActivitiesCount(", app)
        self.assertIn("updateActivitiesCount();", app)

    def test_v6_no_emoji_codepoints(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIsNone(EMOJI_PATTERN.search(html))
        self.assertIsNone(EMOJI_PATTERN.search(app))


if __name__ == "__main__":
    unittest.main()
