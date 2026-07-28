import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "studio"


class StudioListTests(unittest.TestCase):
    """T2 -- table semantics & chart polish (app.js list region).

    Static, source-level regression guards for the activities table
    (the table-render block in applyActivityFilters), the row-interactivity
    wiring (bindOpenRows), the priority donut palette, the strategic/
    coverage bar lists, and the "Attention required" card's status-driven
    top border. Mirrors the text-assertion style already used in
    test_studio.py. Per the T2 file-ownership matrix this file used to own
    only the app.js list region, leaving styles.css and index.html to other
    tasks -- but the Issue column's header cell (index.html) and its
    .issue-chip severity mapping (styles.css) are part of that same list
    region, so ownership now widens to cover both: a header-text regression
    or a chip recoloured off the RAG mapping must fail here, not only be
    caught by hand.
    """

    def test_name_btn_is_the_accessible_row_control(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # C4: the activity-name cell is a real <button>, not a styled span
        # -- native button semantics mean Enter opens the drawer with zero
        # extra keyboard wiring.
        self.assertIn(
            '<button type="button" class="name-btn" data-open-id="${esc(row.id||\'\')}"',
            app,
        )
        # The row keeps data-open-id too (mouse-click convenience only).
        self.assertIn('<tr data-open-id="${esc(row.id||\'\')}">', app)

    def test_rows_no_longer_get_role_button_or_tabindex(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        flat = app.replace(" ", "").replace("\n", "")

        # bindOpenRows still serves the other data-open-id surfaces
        # (overview/board/calendar/conflicts) that have no inner control of
        # their own, so the tabindex/role calls themselves must remain in
        # the source ...
        self.assertIn("setAttribute('tabindex','0')", app)
        self.assertIn("setAttribute('role','button')", app)
        # ... but are only reachable when the element is not a <tr> (C4:
        # the row itself is dropped from the tab order/AT tree -- the
        # name-btn is the real control now).
        self.assertIn("if(el.tagName!=='TR'){", flat)

    def test_name_btn_click_does_not_double_open_the_drawer(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        flat = app.replace(" ", "").replace("\n", "")

        # A click on the name-btn bubbles to its parent <tr>, which is also
        # bound by the same querySelectorAll('[data-open-id]') loop --
        # guard against opening the same drawer twice, mirroring the
        # existing bindDuplicateButtons stopPropagation pattern.
        self.assertIn("if(el.tagName==='BUTTON')event.stopPropagation();", flat)

    def test_issue_column_renders_chips_that_carry_a_fix_target(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # Every chip is a real button carrying the row id and the field it
        # fixes, so the existing delegated [data-fix-id] handler drives it
        # with no extra wiring.
        self.assertIn('class="issue-chip ${esc(issue.kind)}"', app)
        self.assertIn('data-fix-id="${esc(id||\'\')}"', app)
        self.assertIn('data-fix-field="${esc(issue.field)}"', app)
        # Overflow chip still points at a field rather than being inert.
        self.assertIn("if (rest.length) shown.push(chip(rest[0], `+${rest.length}`", app)
        # Clean rows keep the quiet em dash.
        self.assertIn('<span class="readiness-ok">—</span>', app)
        # The cell opts out of the table's nowrap so two chips plus overflow
        # are not clipped by the td ellipsis.
        self.assertIn('<td class="issue-cell">${issueCell}</td>', app)
        # A plain chip (not just the overflow one) carries a title, defaulted
        # to its own label -- max-width:150px can ellipsis a longer label
        # (e.g. "Communications pillars") with no other way to read it.
        self.assertIn('title="${esc(title||text)}"', app)

        # Retired: the count-only badge and its tooltip-as-only-detail.
        self.assertNotIn("${ready.missing.length} missing</button>", app)
        # Retired class from the pre-kit-pass markup.
        self.assertNotIn('class="missing-chip"', app)

    def test_issue_column_header_and_chip_severity_are_pinned(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

        # The column is named for the finding it shows, not for completeness.
        self.assertIn("<th>Issue</th>", html)
        self.assertNotIn("<th>Readiness</th>", html)

        # Severity mapping is the whole point of the chip: red is reserved for
        # the one finding that is a genuine error, so a chip recoloured to red
        # for missing fields or short notice must fail here.
        self.assertIn(".issue-chip{", css)
        self.assertIn("border-left:2px solid var(--bronze-1)", css)
        self.assertIn(".issue-chip.short-notice{border-left-color:var(--warning)}", css)
        self.assertIn(".issue-chip.invalid-date{border-left-color:var(--danger)", css)
        # The table's td rule is nowrap+ellipsis for every other column.
        self.assertIn("td.issue-cell{white-space:normal}", css)

    def test_issue_wording_lives_in_app_js_not_analytics(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        analytics = (DASHBOARD / "analytics.js").read_text(encoding="utf-8")

        # analytics.js returns descriptors only -- all copy is app.js's.
        self.assertIn("'End before start'", app)
        self.assertIn("${issue.leadDays}d lead", app)
        self.assertNotIn("End before start", analytics)
        # Match the interpolation, not the bare words: analytics.js:42 already
        # contains "and lead" in a prose comment, so a plain "d lead" needle
        # would fire on that.
        self.assertNotIn("}d lead", analytics)

    def test_date_predicates_are_called_not_reinlined(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # One rule, three call sites: overview queue groups and the workbench
        # queue filter both defer to analytics.js.
        self.assertIn("rows.filter(A.isShortNotice)", app)
        self.assertIn("rows.filter(A.hasInvalidDates)", app)
        self.assertIn("if (state.queueFilter==='short-notice') return A.isShortNotice(row);", app)
        self.assertIn("if (state.queueFilter==='invalid-date') return A.hasInvalidDates(row);", app)
        # The old inline copies are gone.
        self.assertNotIn("const l=Number(row.planning_lead_days);return Number.isFinite(l)", app)

    def test_duplicate_button_sits_in_a_row_actions_wrapper(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('<td class="action-cell"><div class="row-actions">', app)
        # Role gating is unchanged: Duplicate only renders for canCreate().
        self.assertIn("const duplicateBtn = canCreate() ?", app)

    def test_priority_donut_colors_updated_and_five_way_distinct(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn(
            "const PRIORITY_DONUT_COLORS = "
            "{critical: '#620004', high: '#B98E2C', medium: '#5A5D5C', "
            "normal: '#B8B3A2', low: '#8E8D83'};",
            app,
        )
        # Old Low value (too close to Normal's Gray family) is fully retired.
        self.assertNotIn("low: '#CCCABC'", app)

        match = re.search(r"const PRIORITY_DONUT_COLORS = \{(.*?)\};", app)
        self.assertIsNotNone(match)
        values = re.findall(r"#[0-9A-Fa-f]{6}", match.group(1))
        self.assertEqual(len(values), 5)
        self.assertEqual(
            len(values), len(set(values)), "priority colours must stay distinct"
        )

    def test_strategic_and_coverage_bar_lists_drop_the_bronze_flag(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("barList(countBy(future,'strategic_objectives'))", app)
        self.assertIn("barList(divisions);", app)
        # No remaining bronze-flagged call in either coverage chart.
        self.assertNotIn(
            "barList(countBy(future,'strategic_objectives'),true)", app
        )
        self.assertNotIn("barList(divisions,true)", app)

    def test_attention_card_border_is_status_driven(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        flat = app.replace(" ", "").replace("\n", "")

        # P10: red only while findings are outstanding; toggled from
        # renderOverview off the same totalIssues count used for the
        # attention badge, not a second, separately-maintained figure.
        self.assertIn("document.querySelector('.priority-card')", app)
        self.assertIn("classList.toggle('danger',totalIssues>0)", flat)

    def test_time_filter_marker_stays_neutral_and_is_still_toggled(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # I12(js): app.js only ever toggles the neutral 'filtering' marker
        # -- styles.css (T1, I12-css) maps it to a Grey VI segmented
        # treatment instead of red; app.js itself never names a red/danger
        # class for the time-filter segments.
        self.assertIn(
            "document.getElementById('time-filter').classList.toggle('filtering',filtering);",
            app,
        )
        self.assertNotIn("time-filter').classList.toggle('danger'", app)
        self.assertNotIn("time-presets').classList.toggle('danger'", app)


if __name__ == "__main__":
    unittest.main()
