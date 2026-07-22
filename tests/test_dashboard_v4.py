import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "pipeline" / "scripts" / "build_standalone_v4.py"
DASHBOARD = ROOT / "pipeline" / "dashboard-v4" / "index.html"


class DashboardV4Tests(unittest.TestCase):
    def load_builder(self):
        spec = importlib.util.spec_from_file_location("build_standalone_v4", str(SCRIPT))
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_v4_is_separate_and_contains_required_product_surfaces(self):
        self.assertTrue(DASHBOARD.exists())
        html = DASHBOARD.read_text(encoding="utf-8")
        required = [
            'data-page="overview"',
            'data-page="planning"',
            'data-page="activities"',
            'data-page="analytics"',
            'data-sub="conflicts"',
            'data-sub="capacity"',
            'data-sub="planning-health"',
            'id="attention-list"',
            'id="activity-drawer"',
            'id="change-queue"',
            'id="export-changes"',
        ]
        for marker in required:
            self.assertIn(marker, html)

    def test_builder_inlines_assets_and_embeds_available_data(self):
        builder = self.load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "v4.html"
            builder.build(output)
            html = output.read_text(encoding="utf-8")
        self.assertIn("window.__CPLAN_V4_EMBEDDED__", html)
        self.assertIn("communications.parquet", html)
        self.assertIn("<style>", html)
        self.assertNotIn('href="styles.css"', html)
        self.assertNotIn('src="analytics.js"', html)
        self.assertNotIn('src="app.js"', html)
        self.assertIn("CPLAN Planning Studio V4", html)

    def test_builder_does_not_target_current_dashboard(self):
        builder = self.load_builder()
        self.assertNotEqual(builder.SRC_DIR, ROOT / "pipeline" / "dashboard")
        self.assertEqual(builder.SRC_DIR, ROOT / "pipeline" / "dashboard-v4")
        self.assertEqual(builder.DEFAULT_OUTPUT.name, "cplan_dashboard_v4_standalone.html")

    def test_builder_fails_fast_when_an_inline_marker_is_missing(self):
        builder = self.load_builder()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "dashboard-v4"
            output_dir = root / "output"
            source.mkdir()
            output_dir.mkdir()
            (source / "index.html").write_text(
                '<html><head><link rel="stylesheet" href="styles.css"></head><body><script src="app.js"></script></body></html>',
                encoding="utf-8",
            )
            (source / "styles.css").write_text("body{}", encoding="utf-8")
            (source / "analytics.js").write_text("window.analytics={};", encoding="utf-8")
            (source / "app.js").write_text("window.app={};", encoding="utf-8")
            (output_dir / "communications.parquet").write_bytes(b"PAR1")
            builder.SRC_DIR = source
            builder.OUTPUT_DIR = output_dir
            with self.assertRaisesRegex(ValueError, "inline marker"):
                builder.build(root / "standalone.html")


if __name__ == "__main__":
    unittest.main()
