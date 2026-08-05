"""Static markers for the portal's own files: landing page, user admin, project page, manual.

Everything here reads files and nothing here touches a database, so none of it
is gated on PostgreSQL. Five of these tests used to live in
tests/test_portal_project_page.py, behind that module's `postgres_required`
marker: they skipped in the default configuration -- the one most machines run
-- so the checks that guard the printable documents and the manual's
screenshots were, in practice, not running anywhere.
"""

import re
import unittest
from pathlib import Path

PORTAL = Path(__file__).resolve().parents[1] / "pipeline" / "portal"
STATIC = PORTAL / "static"
JS = STATIC / "js"
MANUAL = PORTAL / "projects" / "cplan" / "manual.html"
ASSETS = PORTAL / "projects" / "cplan" / "assets"
EMOJI = re.compile("[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U00002B00-\U00002BFF]")

STICKY = re.compile(r"position\s*:\s*sticky")
# `@media screen`, `@media screen and (max-width: 860px)` -- but not
# `@media print`, and not a bare `@media (max-width: 700px)`, which applies to
# the print path too.
MEDIA_SCREEN = re.compile(r"@media[^{}]*\bscreen\b[^{}]*\{")
STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def declarations_only(css: str) -> str:
    """CSS with its comments blanked out, length-preserving so offsets still line up.

    Both files explain this very rule in a comment that names `position:
    sticky`, so a checker that scans raw text reports its own documentation as
    a violation.
    """
    return CSS_COMMENT.sub(lambda m: " " * len(m.group(0)), css)


def media_screen_spans(css: str) -> list[tuple[int, int]]:
    """(start, end) of every `@media screen { ... }` body, found by matching braces."""
    spans = []
    for match in MEDIA_SCREEN.finditer(css):
        depth, index = 1, match.end()
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        spans.append((match.end(), index))
    return spans


def sticky_outside_media_screen(css: str) -> list[str]:
    """Every `position: sticky` that is NOT inside an `@media screen` block, with context.

    The check this replaces was `"position: sticky" not in html or "@media
    screen" in html`, which no input can fail: the left side is true for any
    page with no inline CSS, and the right side only asks whether the string
    appears somewhere in the file, not whether the sticky declaration sits
    inside it. This one locates the media blocks and asks where each
    declaration actually is.
    """
    css = declarations_only(css)
    spans = media_screen_spans(css)
    return [
        css[max(0, match.start() - 80) : match.end()]
        for match in STICKY.finditer(css)
        if not any(start <= match.start() < end for start, end in spans)
    ]


def stylesheets_in(html: str) -> str:
    """The CSS from an HTML file's <style> blocks, so brace matching sees only CSS."""
    return "\n".join(STYLE_BLOCK.findall(html))


class PortalFrontendTests(unittest.TestCase):
    def test_shell_markup_has_every_screen(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for element_id in (
            "screen-signin", "screen-app", "project-tiles", "user-rows",
            "matrix-rows", "person-drawer", "invite-modal", "toast",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('type="module"', html)
        self.assertIsNone(EMOJI.search(html))

    def test_navigation_covers_the_three_pages(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for page in ("home", "users", "matrix"):
            self.assertIn(f'data-page="{page}"', html)

    def test_user_table_has_every_sortable_column(self):
        # A later task wires sorting with querySelectorAll('#user-table
        # th.sortable') and toggles state.userSort on data-sort. Every
        # sortable column must carry both, or sorting by that column silently
        # never works.
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for sort_key in ("name", "role", "projects"):
            self.assertIn(f'data-sort="{sort_key}"', html)
        self.assertEqual(html.count('class="sort-arrow"'), 3)

    def test_topbar_carries_no_hardcoded_username(self):
        # The topbar must be populated from the signed-in session at runtime,
        # not ship with whoever last reviewed the prototype baked in.
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for placeholder in ("a.keller", "Portal administrator", ">AK<", "Andrea"):
            self.assertNotIn(placeholder, html)
        for element_id in ("user-chip-avatar", "user-chip-name", "user-chip-role"):
            self.assertIn(f'id="{element_id}"', html)
        app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("user-chip-name", app_js)
        self.assertIn("user-chip-role", app_js)

    def test_home_head_has_no_hardcoded_greeting(self):
        # The prototype's home page greeted a specific person by name; that
        # residue would show up for every user, since no later task
        # personalises this page. The head must be static, data-free copy.
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Good morning", html)
        self.assertNotIn("Andrea", html)

    def test_signin_fields_start_empty(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('value="a.keller"', html)
        self.assertNotIn('value="prototype"', html)

    def test_boot_module_has_no_emoji(self):
        # The old test_no_emoji_and_corporate_palette covered index.html and
        # app.js; this task retires both as the portal's entry point, so the
        # guard moves to the files that replaced them.
        app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIsNone(EMOJI.search(app_js))

    def test_stylesheet_follows_the_design_system(self):
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        self.assertIn("#E60000", css)                 # corporate red primary
        self.assertIn("#F7F7F5", css)                 # page background
        self.assertIn("Frutiger 45 Light", css)       # brand typeface, not system-ui
        self.assertIn("--radius: 2px", css)
        # Drop shadows are forbidden on layout surfaces; the shipped portal had
        # one on every panel. Overlay scrims are not shadows and stay allowed.
        for rule in ("box-shadow", "linear-gradient", "radial-gradient"):
            self.assertNotIn(rule, css, f"{rule} is forbidden by the design system")

    def test_role_ramp_and_status_classes_exist(self):
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        for cls in (".role-admin", ".role-editor", ".role-contributor", ".role-viewer", ".role-none"):
            self.assertIn(cls, css)
        for cls in (".status", ".status-dot", ".toast", ".popover", ".drawer-panel"):
            self.assertIn(cls, css)

    def test_tile_primary_has_its_own_declaration_and_a_red_accent(self):
        # The comment above .tile.no-access mentions "a red fill" in passing;
        # a naive substring check on ".tile-primary" could pass on a comment
        # alone. declarations_only() blanks comments first, so this only
        # passes if a real rule targets .tile-primary and marks it with the
        # corporate red -- not a background fill or tint, per the design
        # system, so this checks for the token, not for "background".
        css = declarations_only((STATIC / "styles.css").read_text(encoding="utf-8"))
        match = re.search(r"\.tile-primary\b[^{]*\{([^}]*)\}", css)
        self.assertIsNotNone(match, ".tile-primary must have a declaration of its own, not just a mention in a comment")
        self.assertIn("var(--primary)", match.group(1))

    def test_project_page_classes_ported_from_the_old_stylesheet_exist(self):
        # These classes are not in the brief's interface list -- the project
        # page (project.html / project.js) landed after the brief was written
        # -- but dropping them silently breaks that page's styling.
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        for cls in (
            ".crumbs", ".crumb-sep", ".crumb-here",
            ".panel", ".panel-head", ".subtitle",
            ".tile-status", ".tile-primary", ".prose", ".hidden",
        ):
            self.assertIn(cls, css)

    def test_document_stylesheet_follows_the_design_system(self):
        css = (STATIC / "document.css").read_text(encoding="utf-8")
        for rule in ("box-shadow", "linear-gradient", "radial-gradient"):
            self.assertNotIn(rule, css, f"{rule} is forbidden by the design system")

    def test_project_page_uses_the_portal_shell(self):
        html = (STATIC / "project.html").read_text(encoding="utf-8")
        self.assertIn('class="topbar"', html)
        self.assertIn('class="brand-block"', html)
        self.assertIn('class="btn quiet"', html)
        self.assertNotIn("btn-ghost", html)   # superseded button class
        # pages.py renders its own copy of this header for the shell pages
        # (access, data, reports, changelog, docs); it must carry the same
        # chrome, not the old brand/btn-ghost markup the stylesheet no longer
        # has rules for.
        pages_py = (PORTAL / "pages.py").read_text(encoding="utf-8")
        self.assertNotIn("btn-ghost", pages_py)
        self.assertNotIn('class="brand"', pages_py)

    def test_api_module_covers_every_endpoint(self):
        api = (JS / "api.js").read_text(encoding="utf-8")
        for route in (
            "/api/me", "/api/login", "/api/logout", "/api/portal/projects",
            "/api/portal/users", "/role", "/revoke", "/password", "/active", "/display-name",
        ):
            self.assertIn(route, api)

    def test_state_pivots_rows_into_accounts(self):
        state = (JS / "state.js").read_text(encoding="utf-8")
        # portal.users returns one row per user x project x role; the UI needs
        # one object per person carrying a per-project map.
        self.assertIn("accountsFromRows", state)
        self.assertIn("export const ROLES", state)
        self.assertIn("highestRole", state)

    def test_app_module_imports_initials_instead_of_redefining_it(self):
        # initials() used to be written out separately in app.js and ui.js.
        # ui.js is now the single home for it; app.js must import it rather
        # than carry its own copy, or the two will drift apart again.
        app_js = (JS / "app.js").read_text(encoding="utf-8")
        self.assertIn("import { initials", app_js)
        self.assertNotIn("function initials(", app_js)

    def test_home_tiles_open_the_project_page_and_favicon_present(self):
        # The new tab now belongs to the application tile on the project page
        # (project.js), not to the home tile: a home tile opens the project's
        # own page, in this tab, so the six other resource tiles are reachable.
        project_js = (STATIC / "project.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('target="_blank"', project_js)
        self.assertIn('rel="noopener"', project_js)
        self.assertIn('rel="icon"', html)

    def test_tiles_show_purpose_and_role_not_the_url(self):
        home = (JS / "home.js").read_text(encoding="utf-8")
        self.assertIn("purpose", home)
        self.assertIn("roleChip", home)
        self.assertIn('target="_blank"', home)
        self.assertIn('rel="noopener"', home)
        # The shipped portal printed the raw URL as the tile subtitle.
        self.assertNotIn("tile-url", home)

    def test_users_table_can_search_filter_and_sort(self):
        users = (JS / "users.js").read_text(encoding="utf-8")
        for hook in ("user-search", "user-filter-role", "user-filter-status", "user-count", "user-empty"):
            self.assertIn(hook, users)
        self.assertIn("aria-sort", users)
        self.assertIn("openDrawer", users)

    def test_users_row_template_matches_the_table_head_column_count(self):
        # Phase 1 has no groups concept, so the Groups column was removed from
        # index.html's <thead>. If the row template in users.js emits a
        # different number of <td>s than the head has <th>s, every row
        # silently misaligns under its header. index.html is the source of
        # truth for the column count.
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        thead_match = re.search(r'<table id="user-table">.*?<thead>(.*?)</thead>', html, re.DOTALL)
        self.assertIsNotNone(thead_match, "user-table thead not found")
        column_count = thead_match.group(1).count("<th")

        users = (JS / "users.js").read_text(encoding="utf-8")
        row_match = re.search(r"innerHTML = list\.map\(\(u\) => `(.*?)`\)\.join\(''\)", users, re.DOTALL)
        self.assertIsNotNone(row_match, "users.js row template not found")
        cell_count = row_match.group(1).count("<td")

        self.assertEqual(
            cell_count, column_count,
            "users.js row template must emit exactly as many <td>s as user-table has <th>s",
        )

    def test_matrix_pivots_and_offers_no_access(self):
        matrix = (JS / "matrix.js").read_text(encoding="utf-8")
        self.assertIn("matrix-rows", matrix)
        self.assertIn("matrix-head", matrix)
        self.assertIn("revokeRole", matrix)     # emptying a cell
        self.assertIn("setRole", matrix)
        self.assertIn("No access", matrix)
        self.assertIn("Export as CSV", matrix)

    def test_matrix_popover_offers_a_no_access_option(self):
        # The matrix exists to let an admin clear a grant, not just set one.
        # A menu item with an empty data-role, wired to revokeRole, is the
        # actual capability; the string "No access" alone could be just a
        # legend label.
        matrix = (JS / "matrix.js").read_text(encoding="utf-8")
        self.assertIn('data-role=""', matrix)
        option_match = re.search(r'data-role=""[^>]*>\s*<span[^>]*>[^<]*</span>([^<]*)', matrix)
        self.assertIsNotNone(option_match, "no-access popover option not found")
        self.assertIn("No access", option_match.group(1))

    def test_drawer_shows_access_and_guards_destructive_actions(self):
        drawer = (JS / "drawer.js").read_text(encoding="utf-8")
        self.assertIn("openDrawer", drawer)
        self.assertIn("resetPassword", drawer)
        self.assertIn("setActive", drawer)
        self.assertIn("window.confirm", drawer)   # destructive steps are confirmed
        self.assertIn("Danger zone", drawer)

    def test_drawer_has_no_group_section(self):
        # Phase 1 has no groups concept: every grant is direct, so the drawer
        # must not render a Groups section, group memberships, a per-group
        # "Remove" button, or describe access as inherited from a group. That
        # is a later phase's feature and must not creep back in as a stub.
        drawer = (JS / "drawer.js").read_text(encoding="utf-8")
        self.assertNotIn("Groups", drawer)
        self.assertNotIn("group", drawer.lower())
        self.assertNotIn("inherited from", drawer.lower())


class ProjectPageStaticTests(unittest.TestCase):
    """Moved here from tests/test_portal_project_page.py: none of these needs a database."""

    def test_project_shell_markup_and_no_emoji(self):
        html = (STATIC / "project.html").read_text(encoding="utf-8")
        js = (STATIC / "project.js").read_text(encoding="utf-8")
        self.assertIn('id="project-tiles"', html)
        self.assertIn('id="project-role"', html)
        self.assertIn("/api/portal/projects/", js)
        self.assertIsNone(EMOJI.search(html))
        self.assertIsNone(EMOJI.search(js))

    def test_every_manual_screenshot_referenced_exists(self):
        # The manual exists; a deleted one must fail here, not skip.
        referenced = set(
            re.findall(r'src="/project/cplan/assets/([^"]+)"', MANUAL.read_text(encoding="utf-8"))
        )
        self.assertTrue(referenced, "the manual should carry screenshots")
        for name in referenced:
            self.assertTrue((ASSETS / name).is_file(), f"missing screenshot: {name}")

    def test_manual_screenshots_are_not_in_the_public_static_tree(self):
        # They were, and were readable with no session at all. The manual is
        # gated; its illustrations must be gated with it, which means they live
        # in the project's own asset directory behind /project/{slug}/assets.
        self.assertFalse((STATIC / "docs").exists())
        self.assertNotIn("/docs/img/", MANUAL.read_text(encoding="utf-8"))

    def test_capture_script_declares_a_shot_per_manual_step(self):
        from pipeline.scripts.capture_manual_shots import SHOTS

        self.assertGreaterEqual(len(SHOTS), 9)
        self.assertEqual(len({shot.key for shot in SHOTS}), len(SHOTS))

    def test_capture_script_writes_into_the_gated_asset_directory(self):
        # If the capture script and the manual disagree about where pictures
        # live, the next capture run silently repopulates the old public path.
        from pipeline.scripts.capture_manual_shots import OUT

        self.assertEqual(OUT, ASSETS)


class PrintablesCarryNoStickyTests(unittest.TestCase):
    """`position: sticky` must appear only inside `@media screen`, in every printable file.

    Safari's PDF writer can emit an empty content stream when a sticky element
    exists anywhere in the DOM, so this is not a style preference: an
    unscoped declaration turns Print / PDF into a blank document.
    """

    def test_the_checker_itself_can_fail(self):
        # The check this replaces could not fail. Prove this one does, in both
        # directions, before trusting it on the real files.
        self.assertEqual(sticky_outside_media_screen("@media screen { .top { position: sticky; } }"), [])
        self.assertEqual(len(sticky_outside_media_screen(".top { position: sticky; }")), 1)
        self.assertEqual(
            len(sticky_outside_media_screen("@media print { .x { position:sticky; } }")), 1
        )
        # A declaration after a closed @media screen block is outside it.
        self.assertEqual(
            len(sticky_outside_media_screen("@media screen { .a { color: red; } }\n.b { position: sticky; }")),
            1,
        )
        # A comment explaining the rule is not a violation of it.
        self.assertEqual(sticky_outside_media_screen("/* no position: sticky here */"), [])

    def test_document_css_keeps_sticky_off_the_print_path(self):
        css = (STATIC / "document.css").read_text(encoding="utf-8")
        self.assertIn("position: sticky", css)  # or this test is guarding nothing
        self.assertEqual(sticky_outside_media_screen(css), [])

    def test_the_manual_keeps_sticky_off_the_print_path(self):
        # The manual is the page that actually gets printed, and it had no such
        # test at all. Its CSS is inline, so read it out of the <style> blocks.
        css = stylesheets_in(MANUAL.read_text(encoding="utf-8"))
        self.assertIn("position: sticky", css)
        self.assertEqual(sticky_outside_media_screen(css), [])
