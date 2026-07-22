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

    def test_v6_analytics_js_is_byte_identical_to_v4(self):
        # Divergence guard: analytics.js is shared, unforked logic between V4
        # (static snapshot) and V6 (live API). Any schema gap between the two
        # must be closed in the API layer (e.g. the `planning_lead_days` and
        # `tracking_pack_id` computed fields) rather than by editing this copy
        # — a fork here would silently split V4/V6 analytics behaviour.
        v6_bytes = (DASHBOARD / "analytics.js").read_bytes()
        v4_bytes = (ROOT / "pipeline" / "dashboard-v4" / "analytics.js").read_bytes()
        self.assertEqual(
            v6_bytes,
            v4_bytes,
            "dashboard-v6-postgres/analytics.js has diverged from dashboard-v4/analytics.js; "
            "resolve any schema gap in pipeline/api_v6/app.py instead of forking this file",
        )

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

    def test_v6_create_entry_point_and_export_demoted(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="activity-new"', html)
        self.assertIn("New activity", html)
        # Export filtered CSV keeps its label but is demoted to a secondary button.
        self.assertIn('class="btn secondary" id="activity-export"', html)

    def test_v6_create_variant_segmented_control(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="source-toggle"', html)
        self.assertIn('data-source="internal"', html)
        self.assertIn('data-source="external"', html)
        # Create-mode header copy is applied dynamically in app.js.
        self.assertIn("New activity", app)
        self.assertIn("Tracking ID is generated on save", app)
        self.assertIn("New record", app)

    def test_v6_create_audience_bands_and_pillar_label(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        for band in ["< 1000", "1–10k", "10–50k", "50–100k", "> 100k"]:
            self.assertIn(band, app)
        self.assertIn("Estimated audience size", html)
        self.assertIn("Communications pillars", html)
        self.assertIn(
            "Select an existing pack only when this activity is known to belong to it",
            html,
        )

    def test_v6_create_activity_repository_and_post(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("createActivity", app)
        self.assertIn("method:'POST'", app)
        self.assertIn("Activity created", app)

    def test_v6_create_required_field_lists_per_variant(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("REQUIRED_INTERNAL", app)
        self.assertIn("REQUIRED_EXTERNAL", app)
        # Internal-only required extras must be present in the required-field logic.
        self.assertIn("target_audience", app)
        self.assertIn("business_division", app)
        self.assertIn("audience", app)
        # news_digest is internal-only and must be handled in app.js.
        self.assertIn("news_digest", app)

    def test_v6_api_error_message_falls_back_on_empty_422_detail_array(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # An empty pydantic-422 `detail` array must not produce a blank
        # toast message ('joined' with nothing yields '').
        self.assertIn("return joined || `Request failed (${status})`;", app)

    def test_v6_reusable_multiselect_control(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn("data-multiselect", html)
        self.assertIn('data-multiselect="strategic_objectives"', html)
        self.assertIn('data-multiselect="business_division"', html)
        self.assertIn('data-multiselect="region"', html)

    def test_v6_campaign_label_hides_standalone_placeholder(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("campaignLabel = row =>", app)
        self.assertIn("STA-0000000", app)
        # Both call sites must go through the shared helper, not the raw
        # campaign||tracking_pack_id fallback that leaks the generic
        # standalone-activity prefix as if it were a real campaign name.
        self.assertNotIn("row.campaign||row.tracking_pack_id", app)
        self.assertNotIn("item.left.campaign||item.left.tracking_pack_id", app)
        self.assertNotIn("item.right.campaign||item.right.tracking_pack_id", app)
        self.assertIn("campaignLabel(row)", app)
        self.assertIn("campaignLabel(item.left)", app)
        self.assertIn("campaignLabel(item.right)", app)

    def test_v6_multiselect_trigger_labels_are_field_specific(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function msUpdateTrigger(", app)
        # Empty-state placeholder must be derived per field from FIELD_LABELS,
        # not a single hardcoded "Select…" string shared by all multiselects.
        self.assertIn("FIELD_LABELS[container.dataset.multiselect]", app)
        self.assertIn("trigger.setAttribute('aria-label'", app)


if __name__ == "__main__":
    unittest.main()
