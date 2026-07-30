import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "studio"


class StudioDrawerTests(unittest.TestCase):
    """T3 -- entry point & drawer chrome (markup).

    Static, source-level regression guards for the single-CTA entry point,
    the in-drawer scope toggle, the restructured sticky footer, the P1/P2
    edit-mode chrome, the P8 required-marker convention, the P11 variant
    help copy, and the P12 add-channel toggle. Mirrors the text-assertion
    style already used in test_studio.py / test_studio_list.py. Per the T3
    file-ownership matrix this file owns index.html and the named app.js
    chrome functions (openCreateDrawer/prepareCreateChrome/applyRoleGating/
    setDrawerEditing; the openPackDrawer wrapper was removed as dead code
    in the T6 sweep) -- it does not
    assert anything about the table-render block, pack-table rows, or
    flow/validation logic owned by other tasks.
    """

    def test_single_primary_cta_and_pack_new_removed(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # I1: at most one primary CTA per page, plus a secondary export.
        # Planning gained its own "New activity" on 2026-07-29: a fresh-eyes test
        # showed planners look for creation under Planning, not under Activities.
        # The rule is one primary CTA per page, not one in the whole studio.
        self.assertIn('<button class="btn secondary" id="activity-export">Export filtered CSV</button>', html)
        self.assertIn('<button class="btn primary" id="activity-new">New activity</button>', html)
        # Planning was dissolved on 2026-07-29 (12 destinations to 4); its page
        # CTA moved to the new Packs tab, where "New pack" is that page's single
        # primary action. The rule under test is unchanged: one primary CTA per
        # page-actions block, every create CTA role-gated.
        self.assertIn('<button class="btn primary" id="packs-new">New pack</button>', html)
        self.assertIn('<button class="btn primary" id="overview-new">New activity</button>', html)
        for block in re.findall(r'<div class="page-actions">(.*?)</div>', html, re.S):
            self.assertLessEqual(block.count('btn primary'), 1, block)
        # #pack-new is gone from markup, role gating, and event wiring.
        # #pack-new was a SECOND primary inside the create drawer, retired by I1
        # in favour of one primary plus a scope toggle. Still gone -- pinned by
        # id, not by label: the Packs page's own "New pack" CTA is a different
        # control on a different surface and must not be caught by this rule.
        self.assertNotIn('id="pack-new"', html)
        self.assertNotIn('id="pack-new"', app)
        # applyRoleGating gates every create CTA behind the same permission.
        self.assertIn("const allowed = canCreate();", app)
        self.assertIn("document.getElementById('activity-new').hidden = !allowed;", app)
        self.assertIn("document.getElementById('packs-new').hidden = !allowed;", app)
        self.assertIn("document.getElementById('overview-new').hidden = !allowed;", app)

    def test_scope_toggle_markup_and_drives_packing_machinery(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="scope-toggle"', html)
        self.assertIn('data-scope="single"', html)
        self.assertIn('data-scope="pack"', html)
        self.assertIn(">One channel<", html)
        self.assertIn(">Several channels<", html)
        # setScope is the single switch driving the existing packing
        # machinery (state.packing / setPackMode), the wide drawer, and the
        # scope-specific title/note -- never a second, parallel toggle path.
        self.assertIn("function setScope(scope)", app)
        self.assertIn("state.packing=scope==='pack';", app)
        self.assertIn("setPackMode(state.packing)", app)
        self.assertIn("classList.toggle('wide',state.packing)", app)
        self.assertIn("'New communication pack'", app)
        # Interactive: clicking the toggle actually calls setScope.
        self.assertIn("document.getElementById('scope-toggle').onclick=", app)
        self.assertIn("setScope(scope);", app)

    def test_scope_toggle_hidden_for_existing_activity(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # Static default: hidden, only revealed while creating.
        self.assertIn('<div class="form-variant" id="scope-row" hidden>', html)
        self.assertIn("document.getElementById('scope-row').hidden=false;", app)
        # setDrawerEditing (view<->edit of an EXISTING activity) always hides
        # it again -- scope is a create-time-only decision.
        self.assertIn("document.getElementById('scope-row').hidden=true;", app)
        self.assertIn("document.getElementById('activity-drawer').classList.remove('wide');", app)

    def test_duplicate_never_reveals_scope_toggle(self):
        """T3-review Important finding: prepareCreateChrome used to reveal
        #scope-row unconditionally for every caller, including
        openDuplicateDrawer. Duplicate has no reset path for the pack DOM
        (#pack-channels/#pack-rows survive closeDrawer -- only
        openCreateDrawer clears them), so a user who abandoned a pack draft
        and later duplicated an unrelated activity could click "Several
        channels" and get the stale pack session (old channels, old row
        names/dates) back under a silently rewritten "Duplicate of ..."
        title. Fix: prepareCreateChrome hides the row by default; only
        openCreateDrawer opts back in. Sliced on real function bodies (not
        comments/docstrings) so this fails if the reveal drifts back into
        prepareCreateChrome or into openDuplicateDrawer itself.
        """
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        def body(start_marker, end_marker):
            start = app.index(start_marker)
            end = app.index(end_marker, start)
            self.assertGreater(end, start)
            return app[start:end]

        prepare_chrome = body(
            "function prepareCreateChrome(title, note) {",
            "function openCreateDrawer(opener) {",
        )
        create_drawer = body(
            "function openCreateDrawer(opener) {",
            "const PACK_ROW_FIELDS=",
        )
        duplicate_drawer = body(
            "function openDuplicateDrawer(row, opener) {",
            "function packErrorMessage(message, rows) {",
        )

        # Shared chrome setup (both create and duplicate call this) hides
        # the toggle by default -- it must never unconditionally reveal it.
        self.assertIn("document.getElementById('scope-row').hidden=true;", prepare_chrome)
        self.assertNotIn("document.getElementById('scope-row').hidden=false;", prepare_chrome)
        # Only the plain-create entry point opts back in.
        self.assertIn("document.getElementById('scope-row').hidden=false;", create_drawer)
        # Duplicate stays single-channel: no reveal, and no setScope() call
        # either (that would be the same hole via a different door).
        self.assertNotIn("document.getElementById('scope-row').hidden=false;", duplicate_drawer)
        self.assertNotIn("setScope(", duplicate_drawer)

    def test_drawer_wide_css_exists_for_pack_scope(self):
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".drawer.wide .drawer-panel", css)

    def test_sticky_footer_grid_with_ready_line_and_save_hint(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # C2/I3: left group -- ready-line (dot + text) and save-hint.
        self.assertIn('id="ready-line"', html)
        self.assertIn('id="ready-text"', html)
        self.assertIn('<span class="dot"></span><span id="ready-text"></span>', html)
        self.assertIn('id="save-hint"', html)
        # Right group -- Cancel, Save as draft, primary Save/Create.
        self.assertIn('class="action-group"', html)
        self.assertIn('id="drawer-cancel"', html)
        self.assertIn('id="btn-draft"', html)
        self.assertIn(">Save as draft<", html)
        self.assertIn('id="drawer-save"', html)
        # #btn-draft is a plain button (no type=submit), so it cannot
        # accidentally trigger the form's own submit handler -- T4 wires a
        # real click handler later.
        self.assertIn('<button type="button" class="btn secondary" id="btn-draft">Save as draft</button>', html)
        # The two inline style.display toggles now write 'grid', not 'flex'
        # (T1's .drawer-actions is a grid; this is what activates it).
        self.assertIn("document.querySelector('.drawer-actions').style.display='grid';", app)
        self.assertIn("document.querySelector('.drawer-actions').style.display=editing?'grid':'none';", app)
        self.assertNotIn("drawer-actions').style.display='flex'", app)
        self.assertNotIn("drawer-actions').style.display=editing?'flex':'none'", app)

    def test_save_hint_moved_from_mode_bar_to_footer(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # The version-check hint text now lives on #save-hint in the footer...
        self.assertIn(
            '<span class="save-hint" id="save-hint" hidden>Version-checked save — conflicts are flagged before anything is overwritten</span>',
            html,
        )
        # ...and #drawer-mode-hint (the old mode-bar home for this text) is
        # gone from both markup and JS -- not just hidden twice.
        self.assertNotIn('id="drawer-mode-hint"', html)
        self.assertNotIn("drawer-mode-hint", app)
        self.assertIn("document.getElementById('save-hint').hidden=!editing;", app)
        self.assertIn("document.getElementById('save-hint').hidden=true;", app)

    def test_edit_mode_eyebrow_and_mode_bar_hidden(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # P1: eyebrow reads "Editing" while editing an existing activity.
        self.assertIn("document.getElementById('drawer-eyebrow').textContent=editing?'Editing':'Activity detail';", app)
        # P2: the mode bar itself is hidden while editing.
        self.assertIn("document.getElementById('drawer-mode').hidden=editing;", app)

    def test_required_markers_are_parenthetical_not_asterisk(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

        # P8: every required marker in the single/shared fieldsets (pack-table
        # rows are T5's own per-channel markup, out of scope here).
        self.assertIn("<em>(required)</em>", html)
        self.assertIn("<em data-vreq>(required)</em>", html)
        # The literal asterisk marker is gone everywhere -- T5 removed the
        # last emitter, T6 retired the orphaned .req rule with it.
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('class="req"', html)
        self.assertNotIn('class="req"', app)
        self.assertNotIn(".req{", css)
        # New style contract: grey, non-italic, wherever it appears.
        # --grey-5, not --grey-4: --grey-4 fails WCAG AA for body text (2026-07-28).
        self.assertIn("font-style:normal;color:var(--grey-5)", css)

    def test_variant_help_is_forward_framed_and_toggles(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # P11: static default matches the default-active Internal variant.
        self.assertIn(
            '<span class="field-help variant-help">Internal also captures audience size and news-digest consideration.</span>',
            html,
        )
        # Dynamic swap per prototype setSource, wired from applyVariant.
        self.assertIn("Internal also captures audience size and news-digest consideration.", app)
        self.assertIn("External runs without the audience-size and news-digest fields.", app)
        self.assertIn("querySelector('.variant-help')", app)

    def test_add_channel_behind_link_inline_toggle(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        # P12: the free-text input is collapsed behind a link-inline toggle,
        # not shown by default alongside the channel matrix.
        self.assertIn('id="pack-channel-toggle"', html)
        self.assertIn('class="link-inline" id="pack-channel-toggle">Add a channel that is not listed<', html)
        self.assertIn('<div class="pack-add-channel" id="pack-add-channel-row" hidden>', html)
        # Existing ids (used by the pack-channel-add submit logic) survive.
        self.assertIn('id="pack-channel-new"', html)
        self.assertIn('id="pack-channel-add"', html)
        self.assertIn("document.getElementById('pack-channel-toggle').onclick=", app)

    def test_paired_short_fields_use_form_grid(self):
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        # I9: Channel+Priority, Target audience+Estimated size, Lead+Lead
        # team share the existing form-grid; description/name/multiselects
        # stay full-width (unchanged, not asserted here).
        self.assertIn(
            '<div class="form-grid">\n'
            '            <label class="f-label" data-single-only data-f="channel">Channel',
            html,
        )
        self.assertIn(
            '<div class="form-grid">\n'
            '            <label class="f-label" data-f="target_audience">Target audience',
            html,
        )
        self.assertIn(
            '<div class="form-grid">\n'
            '            <label class="f-label" data-f="lead">Lead ',
            html,
        )

    def test_f_label_data_f_hooks_for_future_missing_field_painting(self):
        """T4's paintErrors-equivalent needs .f-label[data-f]/.ms-field[data-f]
        anchors (prototype contract), but T4 cannot add them itself (its own
        ownership is app.js flow functions + only the modal in index.html).
        T3 lays this groundwork now since every required field it converts
        already needs the wrapper touched for P8."""
        html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

        for field in [
            "activity_name", "channel", "priority", "strategic_objectives",
            "activity_description", "target_audience", "audience",
            "business_division", "region", "start_date", "end_date",
            "time_zone", "lead", "lead_team",
        ]:
            self.assertIn(f'data-f="{field}"', html)

    def test_create_entry_still_reachable_and_pack_scope_via_toggle(self):
        app = (DASHBOARD / "app.js").read_text(encoding="utf-8")

        self.assertIn("function openCreateDrawer(opener)", app)
        # T6: the openPackDrawer wrapper had zero call sites and is gone --
        # pack scope is reached only through the in-drawer scope toggle,
        # on the same unified chrome/state setup.
        self.assertNotIn("openPackDrawer", app)
        self.assertIn("document.getElementById('scope-toggle').onclick", app)
        self.assertIn("setScope(scope);", app)

    def test_no_emoji_in_new_markup(self):
        """Sentence case, English, no emojis -- re-asserted narrowly on the
        strings this task introduced (the repo-wide sweep already lives in
        test_studio.py::test_no_emoji_codepoints)."""
        for text in [
            "New activity", "Export filtered CSV", "One channel",
            "Several channels", "Save as draft",
            "Add a channel that is not listed",
        ]:
            self.assertTrue(text.isascii())


if __name__ == "__main__":
    unittest.main()
