"""T4 create/edit flow logic — static source markers against pipeline/studio/app.js.

Scope: ready-line (I3), draft flow (C2/I4), stay-open + create another (I5),
prefill (I2), unified dismissal guard (C3), detail-view field edits (P13).
Pack-scope flow logic is T5's file (tests/test_studio_pack.py).
"""

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


class StudioFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        cls.html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

    # ---------------------------------------------------------------- I3
    def test_ready_line_derives_from_required_lists_and_updates_live(self):
        self.assertIn("function updateReady()", self.app)
        ready = _slice(self.app, "function updateReady()", "\n  function ")
        self.assertIn("missingRequiredFields()", ready)
        # Single source of truth: the variant-specific required list, computed
        # in one helper, with the missingExtra() seam T5 extends for pack rows.
        helper = _slice(self.app, "function missingRequiredFields()", "\n  function ")
        self.assertIn("REQUIRED_INTERNAL", helper)
        self.assertIn("REQUIRED_EXTERNAL", helper)
        self.assertIn("missingExtra()", helper)
        self.assertIn("Ready to create", self.app)
        self.assertIn("Ready to save", self.app)
        self.assertIn("required field", self.app)  # "N required fields left"

    def test_source_toggle_can_never_diverge_from_applied_variant(self):
        # Review C1: missingRequiredFields()/attemptSave() read the (hidden)
        # source toggle even while editing, so every variant application must
        # sync the toggle -- otherwise editing an external row validates
        # against the internal required list and full save is impossible.
        variant = _slice(self.app, "function applyVariant(", "\n  function ")
        self.assertIn("setSourceToggle(sourceType)", variant)
        # openDrawer (edit path) and revertToViewFromEdit rely on that fold:
        # neither may grow its own toggle handling again.
        for fn in ("function openDrawer(", "function revertToViewFromEdit("):
            body = _slice(self.app, fn, "\n  function ")
            self.assertIn("applyVariant(sourceType)", body)

    def test_submit_paints_missing_and_hints_the_draft_path(self):
        # Failed submit paints .missing via the data-f attributes and points
        # at the always-visible draft escape hatch.
        self.assertIn('or use "Save as draft"', self.app)
        self.assertIn(".missing", self.app)
        self.assertIn("data-f", self.app)

    # ------------------------------------------------------------- C2/I4
    def test_draft_button_wired_and_modal_inverted_with_jump_links(self):
        self.assertIn("document.getElementById('btn-draft').onclick", self.app)
        # Each missing field is an actionable jump link, not a dead list item.
        self.assertIn("data-jump", self.app)
        self.assertIn("Fill it in", self.app)
        # Draft modal primary is Save as draft (markup order/classes).
        self.assertIn("Save as draft", self.html)

    def test_draft_still_requires_a_name(self):
        self.assertIn("still needs a name", self.app)

    def test_draft_modal_focus_trap_includes_jump_links(self):
        # Review I1: Tab must cycle over every button in the modal (the
        # "Fill it in" links included), not just the two footer buttons.
        modal = _slice(self.app, "function confirmDraftSave(", "\n  function ")
        self.assertIn("modal.querySelectorAll('button')", modal)

    # ---------------------------------------------------------------- I5
    def test_create_stays_open_with_copyable_id_and_create_another(self):
        self.assertIn("Save and create another", self.app)
        # Toast grows a Copy-ID action when a tracking id is passed.
        self.assertIn("Copy ID", self.app)
        toast_sig = re.search(r"function toast\(message, copyValue\)", self.app)
        self.assertIsNotNone(toast_sig)

    # ---------------------------------------------------------------- I2
    def test_prefill_from_own_newest_row_with_start_blank(self):
        self.assertIn("function applyPrefill()", self.app)
        prefill = _slice(self.app, "function applyPrefill()", "\n  function ")
        self.assertIn("newestOwnRow()", prefill)
        # Own rows only (legacy solo mode falls back to 'studio'), newest first.
        source = _slice(self.app, "function newestOwnRow()", "\n  function ")
        self.assertIn("created_by===username", source.replace(" ", ""))
        self.assertIn("created_at", source)
        self.assertIn("'studio'", source)
        self.assertIn("Prefilled from your last activity", self.app)
        self.assertIn('id="prefill-clear"', self.html)
        self.assertIn("Start blank", self.html)
        # Review M2: sparse source rows must not blank out create defaults.
        self.assertIn("if(!nonempty(last[key]))return;", prefill)

    def test_duplicate_note_not_overwritten_by_prefill(self):
        dup = _slice(self.app, "function openDuplicateDrawer(", "\n  function ")
        self.assertIn("prefill-note", dup)  # duplicate uses the slot itself
        # applyPrefill has exactly one real call site, and it is the plain
        # create path -- never the duplicate path (comments mention it, so
        # count call statements rather than substrings).
        self.assertEqual(self.app.count("applyPrefill();"), 1)
        create = _slice(self.app, "function openCreateDrawer(", "\n  function ")
        self.assertIn("applyPrefill();", create)

    # ---------------------------------------------------------------- C3
    def test_all_dismissals_route_through_one_guard(self):
        self.assertIn("function requestClose(", self.app)
        guard = _slice(self.app, "function requestClose(", "\n  function ")
        self.assertIn("confirmDiscardIfDirty()", guard)
        confirm = _slice(self.app, "async function confirmDiscardIfDirty()", "\n  function ")
        self.assertIn("state.dirty", confirm)
        # Review M4: pin each dismissal route to the guard verbatim -- a count
        # would keep passing after unbinding any single route.
        self.assertIn(
            "document.querySelectorAll('[data-close-drawer]').forEach(el=>el.onclick=()=>requestClose());",
            self.app,
        )
        self.assertIn("document.getElementById('drawer-cancel').onclick=()=>requestClose(", self.app)
        self.assertIn("if(isOpen)requestClose();", self.app)  # document-level Escape

    def test_escape_reaches_open_modal_even_when_focus_left_it(self):
        # Review M3: with a modal open but focus outside it (backdrop click),
        # the document-level Escape forwards to the modal instead of no-oping.
        self.assertIn(
            "openModal.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))",
            self.app,
        )

    # --------------------------------------------------------------- P13
    def test_detail_rows_offer_field_scoped_edit_and_add(self):
        self.assertIn('class="row-edit" data-edit-field=', self.app)
        self.assertIn('class="detail-add" data-edit-field=', self.app)
        # Both enter edit focused on that field via the shared mechanism.
        self.assertIn("data-edit-field]", self.app)


if __name__ == "__main__":
    unittest.main()
