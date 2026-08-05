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
        for placeholder in ("a.keller", "Portal administrator", ">AK<"):
            self.assertNotIn(placeholder, html)
        for element_id in ("user-chip-avatar", "user-chip-name", "user-chip-role"):
            self.assertIn(f'id="{element_id}"', html)
        app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("user-chip-name", app_js)
        self.assertIn("user-chip-role", app_js)

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

    def test_home_tiles_open_the_project_page_and_favicon_present(self):
        # The new tab now belongs to the application tile on the project page
        # (project.js), not to the home tile: a home tile opens the project's
        # own page, in this tab, so the six other resource tiles are reachable.
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        project_js = (STATIC / "project.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("/project/", app)
        self.assertNotIn('target="_blank"', app)
        self.assertIn('target="_blank"', project_js)
        self.assertIn('rel="noopener"', project_js)
        self.assertIn('rel="icon"', html)


class ProjectPageStaticTests(unittest.TestCase):
    """Moved here from tests/test_portal_project_page.py: none of these needs a database."""

    def test_home_tiles_link_into_the_project_page(self):
        app_js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("/project/", app_js)
        # The raw URL is gone from the tile: it belongs on the project page now.
        self.assertNotIn("tile-url", app_js)

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
