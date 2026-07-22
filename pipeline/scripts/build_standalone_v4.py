#!/usr/bin/env python3
"""Build the separate CPLAN Planning Studio V4 standalone dashboard.

The current dashboard and its standalone builder are intentionally untouched.
This builder inlines the V4 CSS/JavaScript and embeds the current read-only
Parquet snapshot plus metadata. Local edits remain browser drafts and can be
exported as a versioned JSON change set.
"""

import base64
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = SCRIPT_DIR.parent
SRC_DIR = PIPELINE_DIR / "dashboard-v4"
OUTPUT_DIR = PIPELINE_DIR / "output"
DEFAULT_OUTPUT = OUTPUT_DIR / "cplan_dashboard_v4_standalone.html"
DATA_FILES = (("communications.parquet", True), ("meta.json", False))


def _embedded_fetch_shim(payload):
    serialized = json.dumps(payload, separators=(",", ":"))
    return """<script>
window.__CPLAN_V4_EMBEDDED__ = %s;
(function () {
  var nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  function decode(value) {
    var binary = atob(value);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : ((input && input.url) || '');
    var path = url.split('?')[0];
    var names = Object.keys(window.__CPLAN_V4_EMBEDDED__);
    for (var i = 0; i < names.length; i += 1) {
      var name = names[i];
      if (path.endsWith(name)) {
        var type = name.endsWith('.json') ? 'application/json' : 'application/octet-stream';
        return Promise.resolve(new Response(decode(window.__CPLAN_V4_EMBEDDED__[name]), {
          status: 200,
          headers: {'Content-Type': type}
        }));
      }
    }
    if (!nativeFetch) return Promise.reject(new Error('No embedded file for ' + url));
    return nativeFetch(input, init);
  };
})();
</script>""" % serialized


def build(output=DEFAULT_OUTPUT):
    source = SRC_DIR / "index.html"
    css_path = SRC_DIR / "styles.css"
    analytics_path = SRC_DIR / "analytics.js"
    app_path = SRC_DIR / "app.js"
    required = (source, css_path, analytics_path, app_path)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing V4 source assets: " + ", ".join(missing))

    embedded = {}
    for name, is_required in DATA_FILES:
        path = OUTPUT_DIR / name
        if not path.exists():
            if is_required:
                raise FileNotFoundError("Required data file missing: %s" % path)
            continue
        embedded[name] = base64.b64encode(path.read_bytes()).decode("ascii")

    html = source.read_text(encoding="utf-8")
    replacements = (
        ('<link rel="stylesheet" href="styles.css">', "<style>\n%s\n</style>" % css_path.read_text(encoding="utf-8")),
        ('<script src="analytics.js"></script>', "<script>\n%s\n</script>" % analytics_path.read_text(encoding="utf-8")),
        ('<script src="app.js"></script>', "<script>\n%s\n</script>" % app_path.read_text(encoding="utf-8")),
        ("<head>", "<head>\n%s" % _embedded_fetch_shim(embedded)),
    )
    for marker, replacement in replacements:
        if html.count(marker) != 1:
            raise ValueError("Expected exactly one inline marker: %s" % marker)
        html = html.replace(marker, replacement, 1)
    for marker, _ in replacements[:3]:
        if marker in html:
            raise ValueError("Standalone build retained inline marker: %s" % marker)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def main():
    try:
        output = build()
    except Exception as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    print("CPLAN Planning Studio V4 built")
    print("Output: %s" % output)
    print("Size: %s bytes" % output.stat().st_size)
    print("Current dashboard remains unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
