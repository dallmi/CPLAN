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

# Named imports, static (`import { a, b } from './x.js'`) and dynamic
# (`const { a, b } = await import('./x.js')`, used by drawer.js/invite.js to
# dodge a circular import). Both bind a local name that may be aliased with
# `as`; the export lives under the name *before* `as`.
IMPORT_STATIC = re.compile(r"import\s*\{([^}]+)\}\s*from\s*['\"]\./([\w.-]+\.js)['\"]")
IMPORT_DYNAMIC = re.compile(r"const\s*\{([^}]+)\}\s*=\s*await\s+import\(['\"]\./([\w.-]+\.js)['\"]\)")
# `export function foo`, `export const bar = ...`, and `export { a, b as c }`.
# In the last form the *exported* name is the one after `as`.
EXPORT_DECL = re.compile(r"export\s+(?:async\s+function\*?|function\*?|const|let|class)\s+([A-Za-z_$][\w$]*)")
EXPORT_LIST = re.compile(r"export\s*\{([^}]+)\}(?!\s*from)")


def exported_names(source: str) -> set[str]:
    """Every name a module file makes available to `import { name } from`."""
    names = set(EXPORT_DECL.findall(source))
    for group in EXPORT_LIST.findall(source):
        for item in group.split(","):
            item = item.strip()
            if item:
                names.add(item.split(" as ")[-1].strip())
    return names


def imported_names(source: str) -> list[tuple[str, str]]:
    """[(exported_name, module_filename), ...] for every named import in `source`."""
    result = []
    for pattern in (IMPORT_STATIC, IMPORT_DYNAMIC):
        for match in pattern.finditer(source):
            for item in match.group(1).split(","):
                item = item.strip()
                if item:
                    result.append((item.split(" as ")[0].strip(), match.group(2)))
    return result


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

    def test_a_tile_carries_the_projects_logo_only_when_there_is_one(self):
        # The API sends `logo: null` for a project that publishes no mark, so
        # the template must branch rather than emit an <img src="null"> that
        # renders as a broken-image glyph on every tile without a picture.
        home = (JS / "home.js").read_text(encoding="utf-8")
        self.assertIn("tile-logo", home)
        self.assertIn("if (!p.logo) return ''", home)
        # The name sits right beside it, so the picture is decorative: alt=""
        # keeps a screen reader from announcing the project twice.
        self.assertIn('alt=""', home)
        # The URL comes from the API and still goes through the escaper.
        self.assertIn("esc(p.logo)", home)

    def test_the_logo_is_styled_to_fit_a_tile_whatever_shape_it_is(self):
        # A logo is supplied by whoever owns the project, in whatever
        # proportions they have. Without a height, a width cap and `contain`,
        # one wide or one very large PNG blows up the whole tile grid.
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        block = css.split("\n.tile-logo {")[1].split("}")[0]
        for rule in ("height:", "max-width:", "object-fit: contain"):
            self.assertIn(rule, block)

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
        # Phase 1 has no groups concept: every grant is direct. This checks
        # the markup a Groups section would actually need -- a heading of its
        # own, a membership list, a remove control scoped to one entry rather
        # than the whole account -- not the word "group" in the source. A raw
        # word grep trips on a legitimate explanatory comment, and it would
        # wave through a Groups section relabelled under a different heading.
        drawer = (JS / "drawer.js").read_text(encoding="utf-8")

        # Phase 1 ships exactly these three sections, in this order. A Groups
        # section, however labelled, would add a fourth heading here.
        self.assertEqual(drawer.count('class="drawer-section"'), 3)
        self.assertEqual(
            re.findall(r"<h3>([^<]+)</h3>", drawer),
            ["Account", "Project access", "Danger zone"],
        )

        # A membership list needs its own per-entry remove control; the
        # danger zone offers exactly one remove action, scoped to the whole
        # account, not one per list item.
        self.assertEqual(drawer.count('data-act="remove"'), 1)

    def test_the_import_export_checker_can_fail(self):
        # Prove the two helpers actually work, in both directions, before
        # trusting them on the real module files below.
        self.assertEqual(exported_names("export function foo() {}"), {"foo"})
        self.assertEqual(exported_names("export const bar = 1;"), {"bar"})
        self.assertEqual(exported_names("export async function baz() {}"), {"baz"})
        self.assertEqual(exported_names("export { a, b as c };"), {"a", "c"})
        self.assertEqual(
            imported_names("import { foo, bar } from './x.js';"),
            [("foo", "x.js"), ("bar", "x.js")],
        )
        self.assertEqual(
            imported_names("const { a } = await import('./y.js');"),
            [("a", "y.js")],
        )
        self.assertEqual(imported_names("import { z } from './z.js';"), [("z", "z.js")])

    def test_every_named_import_resolves_to_a_real_export(self):
        # A typo in an import name (or an export that got renamed/removed
        # without updating its callers) currently only surfaces as a runtime
        # error in the browser console. This walks every named import --
        # static and the dynamic `await import()` used to dodge circular
        # imports -- across the module files and checks the target module
        # actually exports that name.
        sources = {path.name: path.read_text(encoding="utf-8") for path in JS.glob("*.js")}
        exports_by_module = {name: exported_names(src) for name, src in sources.items()}

        problems = []
        for name, source in sources.items():
            for imported_name, module in imported_names(source):
                if module not in exports_by_module:
                    problems.append(f"{name} imports from missing module {module}")
                    continue
                if imported_name not in exports_by_module[module]:
                    problems.append(
                        f"{name} imports `{imported_name}` from {module}, which does not export it"
                    )
        self.assertEqual(problems, [])

    def test_invite_modal_replaces_the_browser_prompt(self):
        invite = (JS / "invite.js").read_text(encoding="utf-8")
        self.assertIn("createUser", invite)
        self.assertIn("ROLE_DESC", invite)      # each role explained in a sentence
        self.assertIn("iv-generate", invite)    # generated password
        for module in ("api.js", "state.js", "ui.js", "home.js", "users.js", "matrix.js", "drawer.js", "invite.js", "app.js"):
            source = (JS / module).read_text(encoding="utf-8")
            self.assertNotIn("window.prompt", source, f"{module} still collects input via window.prompt")

    def test_password_word_list_is_large_clean_and_deduplicated(self):
        # Word list quality matters more than exact size (per the owner's
        # decision: ~2,000 pronounceable words, four drawn per password for
        # ~44 bits of entropy, replacing the old 8-word/3-word/2-digit
        # scheme). This only checks the shape a bad regeneration would
        # break: enough entries, no duplicates, and every entry spellable
        # and typeable (lowercase a-z, 3-7 letters).
        words_js = (JS / "password-words.js").read_text(encoding="utf-8")
        match = re.search(r"PASSWORD_WORDS\s*=\s*\[(.*)\];", words_js, re.DOTALL)
        self.assertIsNotNone(match, "PASSWORD_WORDS array not found in password-words.js")
        words = re.findall(r"'([^']*)'", match.group(1))

        self.assertGreaterEqual(len(words), 1500, "password word list has fewer than 1,500 entries")
        self.assertEqual(len(words), len(set(words)), "password word list has duplicate entries")
        word_shape = re.compile(r"^[a-z]{3,7}$")
        bad = [w for w in words if not word_shape.fullmatch(w)]
        self.assertEqual(bad, [], f"non-conforming word-list entries: {bad}")

    def test_generate_password_draws_four_words_with_a_csprng(self):
        # The old generatePassword() picked three of eight fixed words with
        # Math.random() and appended a two-digit number (~12.5 bits,
        # brute-forceable in seconds against a login with no rate limit).
        # The owner's fix is four words from the ~2,000-word pool via a
        # cryptographically secure, unbiased draw -- this checks the shape
        # of that fix, not just that *a* password gets generated.
        ui = (JS / "ui.js").read_text(encoding="utf-8")
        self.assertIn("import { PASSWORD_WORDS } from './password-words.js'", ui)
        self.assertIn("crypto.getRandomValues", ui)
        self.assertNotIn("Math.random", ui)

        # generatePassword() itself must join exactly four words; the
        # rejection-sampling helper it calls into is what actually draws
        # from PASSWORD_WORDS, so match on the join call it makes.
        func_match = re.search(r"export function generatePassword\(\)\s*\{(.*?)\n\}", ui, re.DOTALL)
        self.assertIsNotNone(func_match, "generatePassword() not found in ui.js")
        body = func_match.group(1)
        self.assertIn("PASSWORD_WORDS", ui)
        pick_calls = re.findall(r"pick\(\)", body)
        self.assertEqual(len(pick_calls), 4, "generatePassword() must draw exactly four words")
        self.assertIn("join('-')", body)


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
