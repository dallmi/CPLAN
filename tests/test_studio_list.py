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
    test_studio.py. Per the T2 file-ownership matrix this file owns only
    the app.js list region -- it does not assert anything about styles.css
    or index.html markup owned by other tasks.
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

    def test_readiness_badge_uses_the_pastel_dot_contract(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # Markup/classes only -- meaning is unchanged: still a button that
        # carries the fix-target id/field and the full missing-fields list
        # as its tooltip.
        self.assertIn('class="badge warn"', app)
        self.assertIn(
            '<span class="dot"></span>${ready.missing.length} missing</button>', app
        )
        self.assertIn('data-fix-id="${esc(row.id||\'\')}"', app)
        self.assertIn('data-fix-field="${esc(ready.missing[0]||\'\')}"', app)
        self.assertIn(
            "title=\"${esc(missingLabels(ready.missing).join(', '))}\"", app
        )
        # Retired class from the pre-kit-pass markup.
        self.assertNotIn('class="missing-chip"', app)

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
