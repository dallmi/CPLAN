"""Static markers for the portal landing page + user-admin UI."""

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "pipeline" / "portal" / "static"
EMOJI = re.compile("[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U00002B00-\U00002BFF]")


class PortalFrontendTests(unittest.TestCase):
    def test_login_and_tiles_markup(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="login-overlay"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('id="project-tiles"', html)
        self.assertIn("/api/portal/projects", app)
        self.assertIn("/api/me", app)
        self.assertIn("Sign in", html)
        self.assertNotIn("Anmelden", html)

    def test_user_admin_panel_present_and_admin_gated(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="user-admin"', html)
        self.assertIn("/api/portal/users", app)
        self.assertIn("function canAdmin", app)
        self.assertIn('method: "POST"', app)
        # role change / password reset / activate wired
        self.assertIn("/role", app)
        self.assertIn("/password", app)
        self.assertIn("/active", app)

    def test_no_emoji_and_corporate_palette(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        css = (STATIC / "styles.css").read_text(encoding="utf-8")
        self.assertIsNone(EMOJI.search(html))
        self.assertIsNone(EMOJI.search(app))
        self.assertIn("#E60000", css)   # corporate red primary
        self.assertIn("#F7F7F5", css)   # page background

    def test_tiles_open_in_new_tab_and_favicon_present(self):
        app = (STATIC / "app.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('target="_blank"', app)
        self.assertIn('rel="noopener"', app)
        self.assertIn('rel="icon"', html)
