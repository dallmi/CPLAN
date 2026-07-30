import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "studio"

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
# other plain symbols (e.g. the drawer's "x" close glyph, and the range-banner
# "Show everything" heavy-multiplication-x U+2715) already used as UI text.
EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FFFF\U00002600-\U00002714\U00002716-\U000027BF"
    "\U00002B00-\U00002BFF]"
)


class StudioTests(unittest.TestCase):
    def test_uses_postgres_api_without_duckdb_or_local_drafts(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("CPLAN Studio", html)
        self.assertIn("local snapshot", html)
        self.assertNotIn("duckdb", html.lower())
        self.assertNotIn("jsdelivr", html.lower())
        self.assertIn("/api/activities", app)
        self.assertIn("/api/health", app)
        self.assertIn("method:'PATCH'", app)
        self.assertNotIn("LocalDraftRepository", app)
        self.assertNotIn("localStorage", app)
        self.assertNotIn("PostgreSQL live data", app)

    def test_uses_stable_id_for_row_identity_and_guards_edits(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertNotIn('data-open-id="${esc(row.tracking_id', app)
        self.assertIn(
            "This activity changed since you opened it. Reload and review before saving.",
            app,
        )
        self.assertIn("version_conflict", app)
        self.assertIn("Discard unsaved changes?", app)

    def test_time_zone_select_and_local_time_labels(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('name="time_zone"', html)
        self.assertIn("(local time)", html)
        self.assertIn('<option value="">Not set</option>', html)
        for tz in TIME_ZONE_OPTIONS:
            self.assertIn(f'<option value="{tz}">{tz}</option>', html)

    def test_search_debounce_marker_and_collisions_left_on_ice(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        analytics = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")

        self.assertIn("function debounce(", app)
        self.assertIn("debounce(runActivityFilters,200)", app.replace(" ", ""))

        # Scheduling conflicts were withdrawn from the dashboard on 2026-07-30:
        # at the real portfolio's density the detector fires constantly and
        # nobody could say what to act on. The cache it fed went with it, so
        # the two assertions that pinned it have no subject any more.
        #
        # On ice, not deleted -- the detector and its own tests stay in
        # analytics.js so bringing the concept back is a wiring job rather than
        # a rebuild. Pinned in both directions so neither half drifts: no
        # caller in the dashboard, and the engine still present.
        self.assertNotIn("collisionsFor(", app)
        self.assertNotIn("collisionsCache", app)
        self.assertIn("function detectCollisions(", analytics)

    def test_empty_state_helper_present(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function emptyState(", app)
        self.assertIn("empty-icon", app)
        self.assertIn("empty-title", app)
        self.assertIn("empty-subtext", app)
        self.assertNotIn('"empty">No data available', app)

    def test_a11y_open_rows_and_focus_trap(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        # C4: the activity-name cell is a real <button> — the accessible,
        # keyboard-operable control (native button = Enter works with no
        # extra wiring). The <tr> keeps data-open-id only as a mouse-click
        # convenience and is no longer given role/tabindex.
        self.assertIn('class="name-btn"', app)
        self.assertIn("if (el.tagName !== 'TR')", app)
        # bindOpenRows still applies tabindex/role for the other
        # data-open-id surfaces (overview/board/calendar/conflicts) that
        # have no inner control of their own — those calls stay in source,
        # just no longer reachable for <tr>.
        self.assertIn("setAttribute('tabindex','0')", app)
        self.assertIn("setAttribute('role','button')", app)
        self.assertIn("'Enter'", app)
        self.assertIn('id="drawer-close"', html)

    def test_activities_nav_count_badge(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="activities-count"', html)
        self.assertIn("count-badge", html)
        self.assertIn("function updateActivitiesCount(", app)
        self.assertIn("updateActivitiesCount();", app)

    def test_no_emoji_codepoints(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIsNone(EMOJI_PATTERN.search(html))
        self.assertIsNone(EMOJI_PATTERN.search(app))

    def test_create_entry_point_and_export_demoted(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="activity-new"', html)
        self.assertIn("New activity", html)
        # Export filtered CSV keeps its label but is demoted to a secondary button.
        self.assertIn('class="btn secondary" id="activity-export"', html)

    def test_create_variant_segmented_control(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="source-toggle"', html)
        self.assertIn('data-source="internal"', html)
        self.assertIn('data-source="external"', html)
        # Create-mode header copy is applied dynamically in app.js: the
        # drawer eyebrow switches to "Create" (the mode badge is hidden
        # instead of showing a "New record" label) and the tracking-id
        # slot shows the generated-on-save placeholder.
        self.assertIn("New activity", app)
        self.assertIn("Generated on save", app)
        self.assertIn("drawer-eyebrow').textContent='Create'", app)

    def test_create_audience_bands_and_pillar_label(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        for band in ["< 1000", "1–10k", "10–50k", "50–100k", "> 100k"]:
            self.assertIn(band, app)
        self.assertIn("Estimated audience size", html)
        self.assertIn("Communications pillars", html)
        self.assertIn(
            "Pack membership links this activity to cross-channel reporting via the tracking ID",
            html,
        )

    def test_create_activity_repository_and_post(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("createActivity", app)
        self.assertIn("method:'POST'", app)
        self.assertIn("Activity created", app)

    def test_create_required_field_lists_per_variant(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("REQUIRED_INTERNAL", app)
        self.assertIn("REQUIRED_EXTERNAL", app)
        # Internal-only required extras must be present in the required-field logic.
        self.assertIn("target_audience", app)
        self.assertIn("business_division", app)
        self.assertIn("audience", app)
        # news_digest is internal-only and must be handled in app.js.
        self.assertIn("news_digest", app)

    def test_api_error_message_falls_back_on_empty_422_detail_array(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # An empty pydantic-422 `detail` array must not produce a blank
        # toast message ('joined' with nothing yields '').
        self.assertIn("return joined || `Request failed (${status})`;", app)

    def test_reusable_multiselect_control(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn("data-multiselect", html)
        self.assertIn('data-multiselect="strategic_objectives"', html)
        self.assertIn('data-multiselect="business_division"', html)
        self.assertIn('data-multiselect="region"', html)

    def test_campaign_label_hides_standalone_placeholder(self):
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
        # The item.left / item.right call sites lived in the conflict workbench,
        # retired 2026-07-30. The rule they enforced is unchanged and still
        # pinned by the three assertNotIn above: no surface may fall back to the
        # raw campaign||tracking_pack_id pair, because that leaks the generic
        # standalone prefix as if it were a campaign name.

    def test_multiselect_trigger_labels_are_field_specific(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function msUpdateTrigger(", app)
        # Empty-state placeholder must be derived per field from FIELD_LABELS,
        # not a single hardcoded "Select…" string shared by all multiselects.
        self.assertIn("FIELD_LABELS[container.dataset.multiselect]", app)
        self.assertIn("trigger.setAttribute('aria-label'", app)

    def test_discard_confirmation_modal_markup(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="discard-modal"', html)
        self.assertIn("Discard unsaved changes?", html)
        self.assertIn("Your edits in this activity will be lost.", html)
        self.assertIn('id="discard-keep"', html)
        self.assertIn('id="discard-confirm"', html)
        self.assertIn(">Keep editing<", html)
        self.assertIn(">Discard changes<", html)
        self.assertIn('class="btn danger"', html)

    def test_confirm_discard_is_async_and_no_window_confirm(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # window.confirm must be fully replaced by the in-app modal.
        self.assertNotIn("window.confirm(", app)
        self.assertIn("function confirmDiscardIfDirty", app)
        self.assertIn("await confirmDiscardIfDirty()", app)
        # Guard against a second modal opening from rapid repeated Escape presses.
        self.assertIn("discardModalOpen", app)
        # The pre-existing prompt string is retained (see
        # test_uses_stable_id_for_row_identity_and_guards_edits) — now as
        # the modal title, sourced from index.html rather than window.confirm.
        self.assertIn("Discard unsaved changes?", app)

    def test_danger_button_css_uses_corporate_danger_var(self):
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".btn.danger", css)
        self.assertIn("var(--danger)", css)
        # Modal overlay must sit above the drawer (z-index:100).
        self.assertIn(".modal-overlay", css)

    def test_lead_time_distribution_merges_colliding_labels(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function clusterLeadMarkers(", app)
        # The previous implementation rendered one unconditional label per
        # marker regardless of proximity, causing overlapping P25/Median/P75
        # text when values coincide (e.g. all lead times at 0d). Guard
        # against reverting to that naive per-marker rendering.
        self.assertNotIn("point=(v,label)=>v===null?'':", app)

    def test_sync_run_fetch_present_and_graceful_on_failure(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # Sync-runs status is fetched via the repository, alongside — not blocking —
        # the critical activities/health load, and a failure must resolve to null
        # rather than reject (so Promise.all([loadData(),loadSyncRun()]) never
        # throws just because sync status is unavailable).
        self.assertIn("latestSyncRun() { return this.request('/api/sync-runs/latest'); }", app)
        self.assertIn("async function loadSyncRun()", app)
        self.assertIn("return null;", app)
        self.assertIn("Promise.all([loadData(),loadSyncRun()])", app)
        self.assertIn("state.syncRun=syncRun", app)

    def test_sync_run_reconciliation_card_markup(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function syncRunSummaryHtml()", app)
        # Wired into the reconciliation card body, not just defined and unused.
        self.assertIn("${syncRunSummaryHtml()}", app)
        # never_synced and fetch-failure fallback copy.
        self.assertIn("No source sync yet", app)
        self.assertIn("Status unavailable", app)
        # Metric-line counts in the specified format.
        self.assertIn("new · ${fmtNum(sync.updated)} updated · ${fmtNum(sync.conflicts)} conflicts · ${fmtNum(sync.local_only)} local-only", app)
        # Conflict warning line: RAG amber carried by the .notice.warn class
        # (kit pass I11 removed the brand-colour tints and inline styles).
        self.assertIn("source conflicts overrode local edits (source wins).", app)
        self.assertIn("sync.conflicts > 0", app)
        self.assertIn('class="notice warn"', app)
        # Reuses the existing metric-line/notice design-system classes, no new ones.
        self.assertIn('class="metric-line"', app)
        self.assertIn('class="notice"', app)

    def test_drawer_history_section_markup(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="drawer-history"', html)
        self.assertIn('id="history-body"', html)
        self.assertIn(">History<", html)

    def test_drawer_history_fetch_is_lazy_and_reads_the_changes_endpoint(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("getActivityChanges(id) { return this.request(`/api/activities/${encodeURIComponent(id)}/changes`); }", app)
        self.assertIn("async function loadHistory(", app)
        # Fetched from openDrawer (existing-activity read mode), not from create mode.
        self.assertIn("if (row.id) loadHistory(row.id);", app)
        self.assertIn("document.getElementById('drawer-history').hidden=true;", app)
        # Never shown/fetched while editing -- setDrawerEditing hides the panel.
        self.assertIn("document.getElementById('drawer-history').hidden=editing;", app)

    def test_drawer_history_actor_labels_and_entry_formatting(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("HISTORY_ACTOR_LABELS = {studio:'You', sync:'Source sync', seed:'Initial import'}", app)
        self.assertIn("if (entry.change_type === 'created') return 'Created';", app)
        # Em-dash for NULL old/new values.
        self.assertIn("(value===null||value===undefined) ? '—' : String(value)", app)
        self.assertIn('${label}: ${historyValue(entry.old_value)} → ${historyValue(entry.new_value)}', app)

    def test_drawer_history_shows_latest_30_with_a_muted_overflow_line(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("HISTORY_LIMIT = 30", app)
        self.assertIn("items.slice(0, HISTORY_LIMIT)", app)
        self.assertIn("earlier changes not shown", app)

    def test_drawer_history_uses_the_shared_empty_state_helper(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("emptyState(EMPTY_ICONS.layers, 'No history yet'", app)

    def test_drawer_history_refetches_when_returning_to_read_only_after_editing(self):
        """Regression guard: editing an activity (e.g. Edit -> save hits 409
        -> Cancel) must not leave the History panel showing the stale
        pre-edit snapshot -- the panel must refetch on the transition back to
        read-only, not just on the initial openDrawer fetch."""
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("const wasEditing=state.editing;", app)
        self.assertIn(
            "if (!editing && wasEditing && state.selected && state.selected.id) loadHistory(state.selected.id);",
            app,
        )

    def test_pack_drawer_markup_and_batch_flow(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # I1: pack scope is reached in-drawer via #scope-toggle, not a
        # dedicated "New pack" button (see test_studio_drawer.py for the
        # single-CTA/scope-toggle markers this superseded).
        self.assertIn('id="pack-section"', html)
        self.assertIn('id="pack-channels"', html)
        self.assertIn('id="pack-rows"', html)
        self.assertIn('id="pack-channel-new"', html)
        self.assertIn('id="pack-channel-add"', html)
        # Per-activity fields are hidden in pack mode via this marker.
        self.assertIn("data-single-only", html)
        self.assertIn("/api/activities/batch", app)
        self.assertIn("createActivitiesBatch", app)
        self.assertIn("async function submitPack(", app)
        # T6: no dedicated pack entry point survives -- the scope toggle is
        # the only way in (openPackDrawer was dead code, removed).
        self.assertNotIn("openPackDrawer", app)
        self.assertIn("function setScope(", app)
        self.assertIn("function setPackMode(", app)
        self.assertIn("state.packing", app)
        self.assertIn("activities created", app)
        # Batch API item indices are translated to channel-row names.
        self.assertIn("function packErrorMessage(", app)

    def test_duplicate_entry_points(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="drawer-duplicate"', html)
        self.assertIn(">Duplicate<", html)
        self.assertIn("function openDuplicateDrawer(", app)
        self.assertIn("data-duplicate-id", app)
        self.assertIn("Duplicate of ", app)
        # Row button must not bubble into the row's open-drawer handler.
        self.assertIn("stopPropagation", app)
        # Name is focused and pre-selected for quick overwrite.
        self.assertIn("nameEl.select()", app)

    def test_campaign_pack_filter(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="activity-campaign"', html)
        self.assertIn("All campaigns / packs", html)
        # Wired into populate, apply, clear, and change-listener paths.
        self.assertIn("'activity-campaign'", app)
        self.assertIn("campaignLabel(row)===campaign", app.replace(" ", ""))

    def test_inline_svg_favicon_no_network(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn('rel="icon"', html)
        self.assertIn("data:image/svg+xml", html)
        self.assertIn("E60000", html)
        self.assertNotIn("favicon.ico", html)

    def test_login_overlay_and_session_bootstrap(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="login-overlay"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn("/api/login", app)
        self.assertIn("/api/me", app)
        self.assertIn("/api/logout", app)
        self.assertIn("function apiFetch", app)
        self.assertNotIn("Anmelden", html)  # UI copy is English, matching the studio
        self.assertIn(".login-overlay", css)

    def test_role_gating_helpers_and_delete_action(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        self.assertIn("function canCreate", app)
        self.assertIn("function canEditActivity", app)
        self.assertIn("function canDelete", app)
        self.assertIn("created_by", app)
        self.assertIn('id="user-chip"', html)
        self.assertIn("Sign out", app)
        self.assertIn("Delete activity", app)
        # DELETE verb actually used against the API
        self.assertIn('method: "DELETE"', app)

    def test_kit_compliance_pass(self):
        """Design-system pass: no ALL CAPS, grey eyebrows/asterisks, palette focus ring, neutral KPI tones."""
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # Kit: "No ALL CAPS. No exceptions." — labels are sentence case via markup.
        self.assertNotIn("text-transform:uppercase", css)
        # Eyebrows and required-field markers are grey, not red (red stays a scarce accent).
        # Grey level is --grey-5: --grey-4 only reaches 4.42:1 on white and fails WCAG AA
        # for body text, so secondary text moved one step darker (2026-07-28).
        self.assertIn(".eyebrow{font-size:10px!important;font-weight:600!important;letter-spacing:.02em;color:var(--grey-5)!important", css)
        self.assertIn(".f-label em,.ms-field em,legend em{font-style:normal;color:var(--grey-5)}", css)
        # Form fields get a palette focus ring (never the browser's off-palette blue).
        self.assertIn("input:focus,select:focus,textarea:focus,.ms-trigger:focus{outline:2px solid var(--info)", css)
        # KPI bars: category colouring removed; RAG only where data-driven.
        self.assertNotIn("'highlight'", app)
        # The priority ring came back on 2026-07-30. Its removal a day earlier
        # was reasoned from the demo portfolio, where the levels sat at
        # 35/34/31% and a ring of three equal thirds genuinely says nothing;
        # production runs about 65/18/16/1 across four levels, where the same
        # ring shows that the urgent work is a small identifiable slice of a
        # large pool. The absence assertion was mine and it did not survive the
        # real data, so it is withdrawn rather than worked around.
        #
        # What that assertion protected is still protected: a donut centre must
        # carry its unit, so two rings on one screen can never be silently
        # compared. That is the rule -- pinned directly instead of by proxy.
        self.assertIn("function donutHtml", app)
        self.assertIn("centerSub", app)
        self.assertIn("'activities')", app)

        # I11: no brand-colour tint tokens survive anywhere in the kit --
        # status is carried by the 3px left rule or a badge dot, never a tint.
        self.assertNotIn("-tint", css)
        # I11's badge-dot pattern was the Activities table's Readiness badge.
        # This feature replaced that badge with the Issue column's chips
        # (see test_studio_list.py's Issue-column coverage) and the dot
        # rules were its last consumer -- retired along with it. Pinned as
        # an absence now so the dead rule cannot quietly come back.
        self.assertNotIn(".badge .dot", css)
        # P4 / kit: "No underlines. No ALL CAPS. No exceptions."
        self.assertNotIn("text-decoration:underline", css)
        # New class contract (T3-T5): the drawer's live-ready indicator.
        self.assertIn(".ready-line", css)
        # P5: flat cards on white -- no drop shadow (drawer/modal keep theirs).
        self.assertNotIn("box-shadow", css.split(".card{", 1)[1].split("}", 1)[0])
        self.assertIn("box-shadow", css.split(".drawer-panel", 1)[1].split("}", 1)[0])
        # I10: focus rings never use the scarce red accent.
        self.assertIn("[data-open-id]:focus-visible{outline:2px solid var(--info)", css)
        self.assertNotIn("outline:2px solid var(--primary)", css)


if __name__ == "__main__":
    unittest.main()


class StudioStaticIntegrityTests(unittest.TestCase):
    """Guards against references that survive `node --check` but die at runtime.

    app.js is a DOM IIFE: it cannot be imported into node, so nothing in the
    suite ever executes it. Syntax checking passes happily over an identifier
    that has no declaration -- the failure only appears in a browser, and only
    on the code path that touches it. This bit twice on 2026-07-29/30, both
    times because an edit removed a line that also happened to hold something
    still in use: the `state` object (its literal contained a key being
    deleted) and `RANGE_LABELS` (the range presets stopped re-rendering, so
    every tab kept showing pre-filter data with no error visible on screen).
    """

    def test_every_constant_used_is_also_declared(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        # Strip comments and strings so prose and copy cannot trip the scan.
        body = re.sub(r"/\*.*?\*/", " ", app, flags=re.S)
        body = re.sub(r"(?m)//.*$", " ", body)
        body = re.sub(r"`(?:[^`\\]|\\.)*`", " ", body)
        body = re.sub(r"'(?:[^'\\\n]|\\.)*'", " ", body)
        body = re.sub(r'"(?:[^"\\\n]|\\.)*"', " ", body)

        declared = set(re.findall(r"\b(?:const|let|var|function)\s+([A-Z][A-Z0-9_]{2,})\b", body))
        # Only uses in a position a constant is actually consumed from --
        # indexed, called, or a member read. app.js nests template literals
        # several deep, which defeats naive string stripping and leaves prose
        # like "API refresh" exposed; requiring a following bracket or dot
        # keeps the scan on code and off copy. RANGE_LABELS[...] is exactly
        # the shape that failed.
        used = set(re.findall(r"(?<![.\w$])([A-Z][A-Z0-9_]{2,})\s*[\[(.]", body))
        # Browser globals that are legitimately not declared here.
        ambient = {"JSON", "URL", "MAP", "SET"}

        undeclared = sorted(used - declared - ambient)
        self.assertEqual(
            undeclared, [],
            "CONSTANT_CASE identifiers used but never declared in app.js -- "
            "node --check cannot see this, only a browser can: " + str(undeclared),
        )


class StudioExportTests(unittest.TestCase):
    """Exports are workbooks, not CSV handed to Excel to guess at."""

    def test_exports_are_xlsx_and_csv_is_gone(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('<script src="xlsx.js"></script>', html)
        self.assertIn('id="activity-export">Export to Excel<', html)
        self.assertIn('id="packs-export">Export to Excel<', html)

        self.assertIn(".xlsx", app)
        self.assertIn("CplanXlsx", app)
        # The CSV path is gone from the studio, not merely unused: a second
        # export shape is a second thing to keep in step with the columns.
        self.assertNotIn("exportFilteredCsv", app)
        self.assertNotIn("text/csv", app)
        self.assertNotIn(".csv", app)

    def test_a_missing_workbook_writer_says_so_instead_of_going_quiet(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # xlsx.js is the only file the studio gained rather than changed, so a
        # deployment updated by hand is exactly the one that misses it -- and
        # the first version of this failed in silence: the button rendered, the
        # click threw into the console, and the reader saw nothing at all. Read
        # the module at call time and name the file in the message.
        self.assertIn("function workbookWriter()", app)
        self.assertIn("xlsx.js did not load", app)
        # Never hoisted to load time again, where the check cannot help.
        self.assertNotIn("const X = window.CplanXlsx", app)
        for export in ("function exportActivities()", "function exportPacks()"):
            start = app.index(export)
            self.assertIn(
                "const X = workbookWriter();\n    if (!X) return;",
                app[start:start + 400],
                f"{export} must bail out before touching the writer",
            )

    def test_pack_export_places_summary_cells_by_column_name(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # The first attempt filled the pack summary row positionally and put
        # "11 activities" under Start, the first date under End and the last
        # under Priority -- every value plausible on its own, so nothing looked
        # wrong until the file was opened. Placement by header name cannot
        # drift when a column is added or moved.
        self.assertIn("const summaryRow = values => {", app)
        self.assertIn("if (header in at) cells[at[header]] = value;", app)
        self.assertIn("'Pack / activity':", app)

        # Grouping is the reason this export exists: one row per pack, its
        # activities one level deeper, collapsed on open.
        self.assertIn("level: 0, bold: true", app)
        self.assertIn("level: 1,", app)
        self.assertIn("collapsed: true", app)
