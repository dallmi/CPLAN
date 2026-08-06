import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "studio"


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    """Source between two verbatim markers; fails loudly if either is missing."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


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

    def test_every_zone_the_etl_maps_to_can_be_chosen_here(self):
        """The two halves of one decision: the ETL translates the source's
        display names to IANA zones, and this is where a person picks one.

        A target with no option is a synced activity whose drawer shows "Not
        set" for a field that is filled, and whose next save clears it.
        """
        from pipeline.scripts.process_cplan import TIME_ZONE_MAP

        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        for zone in sorted(set(TIME_ZONE_MAP.values())):
            self.assertIn(f'<option value="{zone}">{zone}</option>', html, zone)

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

    def test_leadership_fields_are_present_end_to_end(self):
        """Neither leadership field used to appear in the studio at all: the
        database had a column for GEB/GEB-1, the source filled it, and nobody
        could see it. Both are now a form field, a detail row, editable, and
        counted among the fields the create form collects.
        """
        app_js = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        index_html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        for field in ("bod_geb", "other_executives"):
            self.assertIn(f'name="{field}"', index_html, f"{field}: no form input")
            self.assertIn(f"'{field}'", app_js, f"{field}: not wired in app.js")

        detail = _slice(app_js, "const DETAIL_SECTIONS", "];")
        self.assertIn("Leadership", detail)
        self.assertIn("'bod_geb','GEB/GEB-1'", detail.replace(" ", ""))

        editable = _slice(app_js, "const EDITABLE_DETAIL_FIELDS", ");")
        for field in ("bod_geb", "other_executives"):
            self.assertIn(f"'{field}'", editable, f"{field}: not editable")

        create = _slice(app_js, "const CREATE_FIELDS", "];")
        for field in ("bod_geb", "other_executives"):
            self.assertIn(f"'{field}'", create, f"{field}: not collected on create")

    def test_the_two_leadership_fields_are_never_merged(self):
        """They are two separate source lists, and neither label may overclaim:
        `bod_geb` mixes GEB and GEB-1 without saying which, and
        `other_executives` is its own list rather than the complement. A label
        or section that ran them together would invite exactly the confusion
        the source already causes.
        """
        app_js = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        labels = _slice(app_js, "const FIELD_LABELS", "};")

        self.assertIn("bod_geb:'GEB/GEB-1'", labels.replace(" ", ""))
        self.assertIn("other_executives:'Otherseniorexecutives'",
                      labels.replace(" ", ""))

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


class StudioSignInMessageTests(unittest.TestCase):
    """A throttled sign-in must not be reported as a wrong password.

    The login throttle (pipeline/api/login_guard.py) answers `429`, and a
    database whose counters could not be consulted answers `503`. Neither says
    anything about the password. A person told "invalid username or password"
    for either one does the obvious thing and changes their password, which
    does not lift the block, does not fix the server, and costs them the one
    credential that was working. The portal was corrected for exactly this; the
    studio is the larger of the two sign-in surfaces and answers the same
    server, so it has to say the same thing -- asserted here against the
    portal's own file rather than against a copy of it, so the two cannot
    drift apart quietly.
    """

    STATUS_MESSAGES = {
        "429": "Too many failed sign-in attempts. Wait a few minutes and try again.",
        "503": "Sign-in is temporarily unavailable. Ask an administrator to check the server.",
    }

    def test_the_studio_words_a_throttled_sign_in_the_way_the_portal_does(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        portal_api = (ROOT / "pipeline" / "portal" / "static" / "js" / "api.js").read_text(encoding="utf-8")

        table = _slice(app, "const LOGIN_ERRORS={", "function showLoginError")
        mapping = dict(re.findall(r"(\d{3}):'([^']*)'", table))
        for status, message in self.STATUS_MESSAGES.items():
            self.assertEqual(mapping.get(status), message, f"studio wording for {status}")
            self.assertIn(
                f"'{message}'", portal_api,
                f"the portal's {status} wording moved; the studio's is now a stale copy of it",
            )

    def test_the_sign_in_form_routes_every_refusal_through_that_table(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        submit = _slice(app, "document.getElementById('login-form').addEventListener", "hideLoginOverlay();")
        self.assertIn("showLoginError(response.status)", submit)
        # The old shape -- unhide an element whose text is fixed in the markup
        # -- is what made every refusal read as a wrong password.
        self.assertNotIn("login-error').classList.remove('hidden')", submit)
        self.assertNotIn("Invalid username or password", html)


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


class OverviewCardsTests(unittest.TestCase):
    """The Overview KPI row is four themed collection cards, display only.

    Reverses the six-flat-tiles decision recorded in app.js. These guards pin
    the parts that a well-meaning refactor would quietly undo: that the cards
    carry no navigation and no deltas, and that the comparison window is gone
    from the Overview but still live on Health.
    """

    def setUp(self):
        self.app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        self.html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        self.css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    def _overview_kpi_block(self) -> str:
        return _slice(self.app, "const cardsHtml = [", "document.getElementById('overview-kpis')")

    def test_overview_renders_four_named_collection_cards(self):
        self.assertIn('class="kpi-groups" id="overview-kpis"', self.html)
        self.assertNotIn('kpi-grid five', self.html)
        block = self._overview_kpi_block()
        for title in ("Portfolio", "In flight", "Readiness", "Lead time"):
            self.assertIn(f"'{title}'", block)

    def test_collection_cards_carry_no_route_and_no_delta(self):
        block = self._overview_kpi_block()
        self.assertNotIn("data-goto", block)
        self.assertNotIn("kpi-trend", block)
        self.assertNotIn("trend(", block)
        # The cardsHtml slice only proves the four kpiGroup(...) call sites
        # are route-free -- it says nothing about kpiGroup() itself. A future
        # change could teach the builder to emit a <button data-goto> from a
        # row object and this assertion would not see it. Slice the function
        # body directly.
        builder = _slice(self.app, "function kpiGroup(", "// Channel colour.")
        self.assertNotIn("data-goto", builder)
        self.assertNotIn("<button", builder)

    def test_seven_day_rows_do_not_claim_to_be_a_calendar_week(self):
        block = self._overview_kpi_block()
        self.assertIn("Starts within 7 days", block)
        self.assertIn("Ends within 7 days", block)
        self.assertNotIn("this week", block.lower())

    def test_empty_portfolio_shows_a_dash_not_a_zero_percent(self):
        block = self._overview_kpi_block()
        # Both rates go through dash(value, guard). Without the guard an empty
        # filter reports "0% complete", which is false: nothing is incomplete
        # when nothing exists. Pin the helper body and both call sites --
        # `const dash = (value, guard) => value` and `dash(x, true)` at either
        # call site both satisfy a bare occurrence count without exercising
        # the guard at all.
        self.assertEqual(block.count("dash("), 2)
        self.assertIn("const dash = (value, guard) => (guard ? value : '—')", self.app)
        self.assertIn("dash(`${quality.completenessRate}%`, rows.length)", block)
        # lead.shortNoticeRate is computed over rows with a usable
        # planning_lead_days, not over all rows (lead.valid is the right
        # denominator) -- rows.length here would render a false "0%" when the
        # filter selects only rows without a usable lead time.
        self.assertIn("dash(`${lead.shortNoticeRate}%`, lead.valid)", block)

    def test_comparison_window_leaves_the_overview_but_stays_on_health(self):
        overview = _slice(self.app, "function renderOverview(", "function renderTrend(")
        self.assertNotIn("comparisonWindow", overview)
        self.assertNotIn("renderMovements", self.app)
        self.assertNotIn("windowNoun", self.app)
        # Still wired where it earns its keep.
        self.assertIn("A.comparisonWindow", self.app)

    def test_readiness_accent_is_conditional_not_permanently_amber(self):
        block = self._overview_kpi_block()
        self.assertIn("readinessTone", block)
        # The slice above starts at cardsHtml, so it only proves the variable is
        # passed to the card. Hardcoding it amber would still pass that. Pin the
        # ternary and what drives it, which is the regression the name promises.
        setup = _slice(self.app, "const readinessFindings", "const cardsHtml = [")
        self.assertIn("incompleteRows.length + quality.invalidDateRanges", setup)
        self.assertIn("readinessFindings ? 'readiness' : 'clean'", setup)

    def test_five_column_kpi_grid_is_gone(self):
        self.assertNotIn(".kpi-grid.five", self.css)
        self.assertIn(".kpi-groups{", self.css)

    def test_kpi_groups_responsive_override_wins_the_cascade(self):
        """Regression: the four-column .kpi-groups base rule used to sit below
        the shared max-width:1000px media block, so a same-specificity
        override placed up there lost and the cards never collapsed below
        four columns, overflowing the viewport on narrow windows. A mere
        assertIn on the override text passed even while it was dead, since
        the string existed either way. Pin that the override actually
        appears *after* the base rule in the file, which is what makes it
        win.
        """
        base = self.css.index(
            ".kpi-groups{display:grid;grid-template-columns:repeat(4,minmax(210px,1fr))"
        )
        override = self.css.index(
            "@media(max-width:1000px){.kpi-groups{grid-template-columns:repeat(2,1fr)}}"
        )
        self.assertGreater(
            override, base,
            "the .kpi-groups max-width:1000px override must come after the "
            "four-column base rule, or it loses the cascade and the cards "
            "never collapse to 2 columns"
        )


class ComingUpCardTests(unittest.TestCase):
    """Coming up: a seven-day date-box list that scrolls inside its card.

    The eight-row cap it replaces existed only to bound the card's height. The
    scroll container bounds it directly, so these guards pin the parts that
    make the container actually work — and that a keyboard can reach it.
    """

    def setUp(self):
        self.app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        self.html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        self.css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    def _upcoming_block(self) -> str:
        return _slice(self.app, "// Upcoming: a rolling seven days", "document.getElementById('priority-donut')")

    def test_window_is_seven_rolling_days_and_the_row_cap_is_gone(self):
        # comingUpRows is computed once, above the cardsHtml array, and
        # reused both by the "In flight" card's "Starts within 7 days" figure
        # and by this list -- so the A.comingUp(...) call itself no longer
        # lives inside this block. What this block still owns is consuming
        # that shared row list.
        #
        # Regression guard folded in here rather than as a separate test:
        # A.comingUp(rows, now, 7) used to be called twice per render (once
        # per card/list), duplicating the work and leaving the two windows
        # free to drift apart if only one call site was edited. There must be
        # exactly one call, hoisted above both users.
        self.assertEqual(self.app.count("A.comingUp(rows, now, 7)"), 1)
        self.assertIn("const comingUpRows = A.comingUp(rows, now, 7);", self.app)
        cards_block = _slice(self.app, "const cardsHtml = [", "document.getElementById('overview-kpis')")
        self.assertIn("comingUpRows.length", cards_block)
        block = self._upcoming_block()
        self.assertIn("comingUpRows.length", block)
        self.assertIn("comingUpRows.map(row =>", block)
        self.assertNotIn("UPCOMING_SHOWN", self.app)
        self.assertNotIn("weekKey", self.app)
        self.assertNotIn("week-heading", self.app)
        self.assertNotIn(".week-heading{", self.css)

    def test_row_carries_a_channel_edge_and_a_source_tinted_date_box(self):
        block = self._upcoming_block()
        self.assertIn("event-channel-edge", block)
        self.assertIn("channelColor(row.channel)", block)
        self.assertIn("event-date-box", block)
        self.assertIn("relativeDayLabel", block)
        # The drawer route survives the redesign.
        self.assertIn("data-open-id", block)
        # event-date-box carries a source-tint (`.external`), not a priority
        # one -- an implementation tinting by priority instead would still
        # satisfy a bare "event-date-box" assertion, so pin what drives it.
        self.assertIn("row.source_type === 'external'", block)

    def test_scroll_region_is_reachable_by_keyboard(self):
        card = _slice(self.html, 'id="upcoming-list"', "</article>")
        opening = _slice(self.html, '<div class="card-body flush scroll-y" id="upcoming-list"', ">")
        self.assertIn('tabindex="0"', opening)
        self.assertIn('role="region"', opening)
        self.assertIn("aria-label=", opening)
        # The footer is a sibling of the scroll body, or it scrolls away.
        self.assertIn('id="upcoming-more"', card)

    def test_flex_column_card_can_actually_scroll(self):
        rule = _slice(self.css, "#view-list .grid.two>.card", ".event-row{")
        # min-height:0 is load-bearing: without it the flex child grows to its
        # content instead of scrolling, and the card silently returns to the
        # 988px problem the row cap was invented for.
        self.assertIn("min-height:0", rule)
        self.assertIn("overflow-y:auto", rule)
        # The floor stops the card collapsing when the queue beside it is empty.
        self.assertIn("min-height:360px", rule)
        # Only Coming up scrolls; the queue keeps its own height.
        self.assertIn(".scroll-y", rule)
        # A grid row's auto track sizes to its tallest content, so a shorter
        # neighbour can never hand this card a definite height to scroll
        # within. Only the viewport can put a ceiling on it. The max(280px, …)
        # floor is what stops that calc clamping to 0 below a ~500px viewport
        # (extreme browser zoom is a real, WCAG-supported condition).
        self.assertIn("max-height:max(280px,calc(100vh", rule)
        # The two assertions above ("min-height:0" and ".scroll-y") are also
        # both satisfied by the long explanatory comment directly above the
        # declaration -- it literally contains the strings "min-height:0 is
        # load-bearing" and "Scoped to .scroll-y so this cap lands on". A
        # regression that deletes the whole declaration but keeps the comment
        # (exactly the silent-scroll-loss failure this test exists to catch)
        # would still pass every assertion above it. Pin the entire
        # declaration as one string against the full stylesheet instead, the
        # way the stretch override just below is already asserted.
        self.assertIn(
            "#view-list .grid.two>.card>.card-body.scroll-y{min-height:0;"
            "max-height:max(280px,calc(100vh - 500px));overflow-y:auto}",
            self.css,
        )
        # The #page-overview .grid.two{align-items:start} rule (near the top
        # of the file) turns off stretch for every two-column row on the
        # Overview. Without a more specific override scoped back to
        # #view-list, the two cards never come out equal height and the whole
        # fix is inert -- measured headless: 1479px vs 360px, not equal, and
        # no scrollbar.
        self.assertIn("#page-overview #view-list .grid.two{align-items:stretch}", self.css)

    def test_empty_state_names_the_seven_day_window(self):
        block = self._upcoming_block()
        self.assertIn("No activities in the next 7 days", block)
