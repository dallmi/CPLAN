"""T5 pack flow — static source markers against pipeline/studio/*.

Scope: per-channel pack-table with live ID stubs and fill-down (I6), the
permanently visible atomic pre-save summary + count-labelled CTA (C1), the
pack-scope section order (I7), and the pack draft rule over the existing
batch endpoint. Single-scope flow logic is T4's file
(tests/test_studio_flows.py); drawer chrome is T3's
(tests/test_studio_drawer.py).
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pipeline" / "studio"


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    """Source between two verbatim markers; fails loudly if either is missing."""
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


class StudioPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (DASHBOARD / "app.js").read_text(encoding="utf-8")
        cls.html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        cls.css = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    # ---------------------------------------------------------------- I6
    def test_pack_rows_render_as_pack_table(self):
        rows = _slice(self.app, "function renderPackRows()", "\n  function ")
        self.assertIn('<table class="pack-table">', rows)
        # Column contract: Channel · Activity name · Start · End · ID stub,
        # required markers in the P8 parenthetical style (no red asterisks).
        self.assertIn("const required='<em>(required)</em>'", rows)
        for th in (">Channel</th>", "Activity name ${required}", "Start ${required}", "End ${required}", ">Tracking ID</th>"):
            self.assertIn(th, rows)
        # Per-row inputs keep the pre-wave data hooks (packRowValues/fill-down
        # depend on them) and are individually labelled for AT users.
        self.assertIn('class="pack-row" data-channel=', rows)
        self.assertIn('<td class="ch-name">', rows)
        self.assertIn('data-pack-name value="${esc(name)}" aria-label="Activity name for ${esc(channel)}"', rows)
        self.assertIn('data-pack-start value="${esc(start)}" aria-label="Start for ${esc(channel)}"', rows)
        self.assertIn('data-pack-end value="${esc(end)}" aria-label="End for ${esc(channel)}"', rows)
        self.assertIn('<td class="stub" data-pack-stub>', rows)
        # Re-renders (channel ticks) must never wipe what was already typed.
        self.assertIn("new Map(packRowValues().map(row=>[row.channel,row]))", rows)
        # An existing row keeps its own dates; only a channel ticked for the
        # first time inherits the pack dates. Both halves matter -- inheriting
        # unconditionally would silently overwrite a per-row exception on every
        # re-render, which is exactly what the previous-values Map exists to
        # prevent.
        self.assertIn("const start=prev?prev.start:packDefault('fill-start');", rows)
        self.assertIn("const end=prev?prev.end:packDefault('fill-end');", rows)

    def test_ticking_a_channel_seeds_row_name_from_pack_name(self):
        rows = _slice(self.app, "function renderPackRows()", "\n  function ")
        # "<pack name> — <channel>" only when a pack name exists; otherwise
        # the name stays open so the ready-line/draft rule chase it.
        self.assertIn("packName?`${packName} — ${channel}`:''", rows)

    def test_stubs_live_update_reusing_existing_stub_logic(self):
        stubs = _slice(self.app, "function updatePackStubs()", "\n  function ")
        # Existing stub logic reused, not re-derived: pack prefix, date part
        # and channel abbreviation all come from the pre-wave helpers.
        self.assertIn("packIdPrefix()", stubs)
        self.assertIn("stubDate(start)", stubs)
        self.assertIn("channelAbbr(channel)", stubs)
        self.assertIn("[data-pack-stub]", stubs)
        # Live: typing in a row (start date included) refreshes the stubs.
        self.assertIn(
            "document.getElementById('pack-rows').addEventListener('input',updatePackStubs);",
            self.app,
        )

    def test_fill_down_block_above_table_applies_to_every_row(self):
        # Markup: the fill-down block lives inside the per-channel fieldset,
        # above the rows container.
        self.assertIn('class="fill-down" id="pack-fill-down"', self.html)
        for marker in ('id="fill-start"', 'id="fill-end"', 'id="fill-apply"', ">Use for all channels<"):
            self.assertIn(marker, self.html)
        self.assertLess(self.html.index('id="pack-fill-down"'), self.html.index('<div id="pack-rows">'))
        # Behaviour: apply start/end to every channel row, rows stay editable.
        self.assertIn("document.getElementById('fill-apply').onclick=", self.app)
        self.assertIn("if(!start&&!end){toast('Set a pack start or end date first');return;}", self.app)
        self.assertIn("if(start)rowEl.querySelector('[data-pack-start]').value=start;", self.app)
        self.assertIn("if(end)rowEl.querySelector('[data-pack-end]').value=end;", self.app)
        self.assertIn("each row stays editable", self.app)
        # Reversed on 2026-07-29, deliberately. The block used to hide until a
        # channel was ticked ("no rows, nothing to fill"). But the dates belong
        # to the pack, not to the rows, and setting them before picking channels
        # is the faster order -- every channel then arrives already dated. The
        # old rule forced the slow order and made the button read as a
        # correction tool rather than the default. Pinned in the new direction
        # so it cannot drift back unnoticed.
        self.assertIn("document.getElementById('pack-fill-down').hidden=false;", self.app)
        self.assertNotIn("document.getElementById('pack-fill-down').hidden=!selected.length;", self.app)
        # Pressing it with no channel ticked is a dead end unless it says so.
        self.assertIn("Tick a channel first", self.app)
        # A fresh create session never inherits the previous session's fill dates.
        create = _slice(self.app, "function openCreateDrawer(opener)", "\n  const PACK_ROW_FIELDS")
        self.assertIn("document.getElementById('fill-start').value='';", create)
        self.assertIn("document.getElementById('fill-end').value='';", create)

    # ---------------------------------------------------------------- C1
    def test_summary_permanently_visible_with_empty_state_and_atomic_line(self):
        summary = _slice(self.app, "function renderPackSummary()", "\n  function ")
        # Permanent in pack scope: unhidden BEFORE the empty-state branch, so
        # zero channels shows the empty state instead of nothing.
        self.assertLess(summary.index("summary.hidden=false;"), summary.index("if(!rows.length)"))
        self.assertIn("Nothing will be created yet", summary)
        self.assertIn("Tick at least one channel to build the pack.", summary)
        # Per-channel name + ID stub, unnamed rows called out as such.
        self.assertIn("row.name.trim()||'unnamed'", summary)
        self.assertIn("channelAbbr(row.channel)", summary)
        # The atomicity promise closes the summary.
        self.assertIn('class="atomic"', summary)
        self.assertIn("created together, or none of them are.", summary)
        # Driven from the one updateReady funnel -- every input/change keeps
        # CTA count and summary in step with the ready-line.
        ready = _slice(self.app, "function updateReady()", "\n  function ")
        self.assertIn("if (state.packing){updatePackCta();renderPackSummary();}", ready)
        # ...and bounded to pack scope: leaving it hides the summary again.
        pack_mode = _slice(self.app, "function setPackMode(on)", "\n  function ")
        self.assertIn("if(!on)document.getElementById('pack-summary').hidden=true;", pack_mode)

    def test_primary_cta_is_count_labelled_and_disabled_at_zero(self):
        cta = _slice(self.app, "function updatePackCta()", "\n  function ")
        self.assertIn("save.disabled=count===0;", cta)
        self.assertIn("'Select a channel to continue'", cta)
        self.assertIn("`Create ${count} ${count===1?'activity':'activities'}`", cta)

    def test_disabled_pack_cta_never_leaks_into_other_modes(self):
        # The zero-channel disable must be re-armed on every exit from pack
        # scope: fresh create/duplicate chrome, the scope flip back to
        # single, and the view<->edit path of an existing record.
        for fn in (
            "function prepareCreateChrome(title, note) {",
            "function setScope(scope) {",
            "function setDrawerEditing(",
        ):
            body = _slice(self.app, fn, "\n  function ")
            self.assertIn(".disabled=false;", body, fn)

    # ---------------------------------------------------------------- I7
    def test_pack_scope_section_order_via_css_order_rules(self):
        # #pack-section stays the one show/hide unit but dissolves into the
        # form's flex order so its two fieldsets can be ordered apart.
        self.assertIn('<fieldset id="fs-channels">', self.html)
        self.assertIn('<fieldset id="fs-pack-rows">', self.html)
        self.assertIn("#activity-form.pack-mode #pack-section{display:contents}", self.css)
        # Order chain: Type/Scope → Identity → Channels → per-channel rows →
        # shared heading → shared fieldsets → summary.
        #
        # Rows moved ahead of the shared block on 2026-07-29. Measured before
        # the move: the channel picker rendered at 462px and its own date table
        # at 1740px, seven unrelated fieldsets apart, so ticking a channel and
        # saying when it goes out could not be done without scrolling past
        # Classification, Content, Audience, Organisation, Schedule, Ownership
        # and Visibility. Picking a channel and dating it is one thought. The
        # pinned order is the point of the rule, so it is restated rather than
        # loosened.
        rules = [
            "#activity-form.pack-mode .form-variant{order:1}",
            "#activity-form.pack-mode .prefill-note{order:2}",
            "#activity-form.pack-mode #fs-identity{order:3}",
            "#activity-form.pack-mode #fs-channels{order:4}",
            "#activity-form.pack-mode #fs-pack-rows{order:5}",
            "#activity-form.pack-mode .pack-shared-heading{order:6}",
            "#activity-form.pack-mode fieldset:not(#fs-identity):not(#fs-channels):not(#fs-pack-rows){order:7}",
            "#activity-form.pack-mode .pack-summary{order:8}",
        ]
        for rule in rules:
            self.assertIn(rule, self.css)
        # Single scope keeps pure DOM order: every order rule for the form
        # is scoped to .pack-mode (none may apply outside it).
        for line in self.css.splitlines():
            if "#activity-form" in line and "{order:" in line:
                self.assertIn("#activity-form.pack-mode", line)

    def test_pack_controls_live_inside_the_gated_drawer_form(self):
        # Role gating: pack create is create-shaped and inherits the
        # #activity-new gate -- everything new sits inside #activity-form.
        form_start = self.html.index('<form id="activity-form"')
        form_end = self.html.index("</form>", form_start)
        for marker in ('id="fs-channels"', 'id="fs-pack-rows"', 'id="pack-fill-down"', 'id="pack-summary"'):
            self.assertTrue(form_start < self.html.index(marker) < form_end, marker)

    # ------------------------------------------------------- draft rule
    def test_missing_extra_returns_pack_gaps_through_the_one_funnel(self):
        extra = _slice(self.app, "function missingExtra()", "\n  function ")
        # Inert outside pack scope -- single scope is untouched by the seam.
        self.assertIn("if (!state.packing) return [];", extra)
        self.assertIn("extra.push('pack_name')", extra)
        self.assertIn("extra.push('pack_channels')", extra)
        for col in ("name", "start", "end"):
            self.assertIn(f"pack_row:${{row.channel}}:{col}", extra)
        # No second required-fields list: the shared portion still derives
        # from REQUIRED_INTERNAL/EXTERNAL inside missingRequiredFields.
        helper = _slice(self.app, "function missingRequiredFields()", "\n  function ")
        self.assertIn("missingExtra()", helper)

    def test_pack_gap_tokens_have_labels_focus_and_paint(self):
        # Draft modal rows use the pack-aware labels, not raw tokens.
        label = _slice(self.app, "function missingFieldLabel(name)", "\n  function ")
        self.assertIn("'At least one channel'", label)
        self.assertIn("PACK_ROW_COL_LABELS[token[2]]", label)
        modal = _slice(self.app, "function confirmDraftSave(", "\n  function ")
        self.assertIn("esc(missingFieldLabel(name))", modal)
        # "Fill it in" jump links land inside the pack UI. Token resolution
        # now lives in fieldElement (focusField just resolves the element via
        # fieldElement, then focuses/highlights it), so the slice follows the
        # lookup to where it actually sits rather than where it used to.
        focus = _slice(self.app, "function fieldElement(name)", "\n  function ")
        self.assertIn("PACK_ROW_TOKEN_RE.exec", focus)
        self.assertIn("pack_channels", focus)
        # Failed submits paint the exact empty pack-table cells.
        paint = _slice(self.app, "function paintMissing(", "\n  function ")
        self.assertIn("pack_row:${rowEl.dataset.channel}:${col}", paint)
        self.assertIn(".pack-table input.missing{border-color:var(--danger)}", self.css)

    def test_pack_channels_gap_paints_the_channels_legend(self):
        # T6: pack_channels has no input to paint, so the Channels legend
        # carries the same .f-label/data-f hook paintMissing() already
        # matches -- a failed zero-channel submit turns the legend red like
        # every other gap, and clearMissingPaint() clears it the same way.
        self.assertIn(
            '<legend class="f-label" data-f="pack_channels">Channels <em>(required)</em></legend>',
            self.html,
        )
        self.assertIn("legend.f-label.missing,legend.f-label.missing em{color:var(--danger)}", self.css)

    def test_pack_draft_rule_names_required_dates_optional(self):
        # Blockers: pack name, at least one channel, every row name -- the
        # draft modal's Save refuses and focuses instead of posting.
        blocker = _slice(self.app, "const isDraftBlocker", "\n  function confirmDraftSave")
        self.assertIn("name==='activity_name'||name==='pack_name'||name==='pack_channels'", blocker)
        self.assertIn("token[2]==='name'", blocker)
        self.assertIn("A draft pack still needs at least one channel.", self.app)
        self.assertIn("A draft still needs a name.", self.app)  # single scope keeps its rule
        # Draft path: #btn-draft routes pack scope through the shared modal
        # into the batch commit -- never a second modal, never a bare submit.
        draft = _slice(self.app, "async function openDraftModal()", "\n  async function requestClose")
        self.assertIn("if(!await confirmDraftSave(missing))return;", draft)
        self.assertIn("if(state.packing){await commitCreatePack(true);return;}", draft)
        # Dates are optional in a draft: only present values are sent, so the
        # API's nullable date fields stay null instead of getting "".
        commit = _slice(self.app, "async function commitCreatePack(draft) {", "\n  function closeDrawer")
        self.assertIn("createActivitiesBatch(items)", commit)
        self.assertIn("if(row.start)item.start_date=", commit)
        self.assertIn("if(row.end)item.end_date=", commit)
        self.assertIn("draft activities created — chased on the Overview", commit)

    def test_pack_submit_gate_blocks_paints_and_hints_the_draft_path(self):
        gate = _slice(self.app, "async function submitPack(event) {", "async function commitCreatePack(draft) {")
        self.assertIn("state.showErrors=true;", gate)
        self.assertIn("updateReady()", gate)
        self.assertIn("focusField(missing[0]);", gate)
        self.assertIn('or use "Save as draft"', gate)
        # Full create still ends in the same atomic batch commit.
        self.assertIn("await commitCreatePack(false);", gate)


if __name__ == "__main__":
    unittest.main()
