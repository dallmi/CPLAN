"""Repository markdown, rendered into the portal's chrome on request.

Rendered rather than rewritten: the technical documentation already exists in
`pipeline/docs/`, is already maintained there, and a hand-copied second version
would be wrong within a month. Rendering happens per request and is cheap — the
largest of these documents is under 200 lines.

These files are markdown, not HTML, so a document added later must never be
able to inject markup into a portal page. The first version of this module
enforced that by running `html.escape()` over the whole source before handing
it to `markdown.markdown()`. That broke real documents: Python-Markdown's own
fenced-code handling escapes `<`, `>`, `&` and quotes inside a code fence on
the assumption that it is receiving raw, unescaped source. Fed already-escaped
text instead, it escaped it a second time, so a JS snippet's `=>` came out as
the literal text `&gt;` rather than `>` — visible corruption in
`cross-channel-matching.md`, not a cosmetic wrinkle.

The fix keeps the same guarantee without the double escaping: instead of
pre-escaping the source, the two Markdown components that would recognise and
pass through raw HTML are deregistered from the parser —
`html_block` (block-level raw HTML) and `html` (the inline pattern for tags
inside a paragraph). This is the documented replacement for the `safe_mode`
Python-Markdown removed. With both handlers gone, a `<script>` or `<img
onerror=...>` in the source is never recognised as markup; it falls through
untouched to the serializer, which HTML-escapes it exactly once — same result
as before for the security case, correct output for the code-fence case.
If someone "simplifies" this by removing the two `deregister` calls, raw HTML
from a document becomes live markup on a portal page again — that is the
vulnerability this module exists to prevent.
"""

from __future__ import annotations

import html as html_escape
import re
from typing import Any

import markdown

from pipeline.portal.resources import load_manifest, manifest_path

_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]

# Matches the rendered body's own leading <h1>, if it has one, so it can be
# dropped in favour of the template's single <h1> (see _strip_leading_h1).
_LEADING_H1 = re.compile(r"\A\s*<h1[^>]*>.*?</h1>\s*", re.DOTALL)


def _render_markdown(source: str) -> str:
    """Convert repository markdown to HTML without ever passing through raw HTML.

    A fresh `Markdown` instance per call: the class carries state between
    conversions (e.g. footnote/reference tables), and this module is called
    once per request, so sharing one instance across calls without a `reset()`
    would leak state between unrelated documents.
    """
    converter = markdown.Markdown(extensions=_EXTENSIONS)
    converter.preprocessors.deregister("html_block")
    converter.inlinePatterns.deregister("html")
    return converter.convert(source)


def _strip_leading_h1(body: str) -> str:
    """Drop the source document's own top-level heading, if it starts with one.

    `_PAGE` already renders exactly one <h1>, from the manifest's title — the
    same sentence-case copy already shown in the <title> element, the
    breadcrumb and the rail, so the page stays internally consistent. Before
    this, a document whose source begins with `# Some Heading` rendered that
    heading a second time as the body's own <h1>, immediately under the
    template's — visible on every one of this project's documents, since all
    of them open with a top-level heading, and in at least one case wrong
    even as a duplicate: the manifest says "Data model", the source's own
    heading says "Data Model", and the two are never reconciled.

    A document is edited for its own sake in `pipeline/docs/`, not for the
    portal's chrome, so the fix lives here, in the renderer, not in the
    markdown: only the source's *leading* heading is removed (a non-greedy,
    start-anchored match), and only when there is one — a document with no
    top-level heading of its own is untouched, and the template's <h1>
    quietly does double duty as its only title, exactly as before.
    """
    return _LEADING_H1.sub("", body, count=1)


def published_documents(slug: str) -> list[dict[str, Any]]:
    """The documents this project publishes — an allow-list, not a directory scan."""
    for spec in load_manifest(slug).get("tiles", []):
        if spec.get("kind") == "docs":
            return spec.get("documents", [])
    return []


def render_document(
    slug: str, key: str, project_name: str, documents: list[dict[str, Any]]
) -> str | None:
    """A complete HTML page for one declared document, or None if undeclared."""
    entry = next((d for d in documents if d.get("key") == key), None)
    if entry is None:
        return None
    path = manifest_path(slug, "docs", key)
    if path is None or not path.is_file():
        body = "<p class='missing'>This document is not available in this installation.</p>"
        source_note = ""
    else:
        source = path.read_text(encoding="utf-8")
        body = _strip_leading_h1(_render_markdown(source))
        source_note = f"Source: <code>{html_escape.escape(str(path.relative_to(path.parents[2])))}</code>"
    return _PAGE.format(
        title=html_escape.escape(entry.get("title", key)),
        project=html_escape.escape(project_name),
        slug=html_escape.escape(slug),
        rail=_rail(slug, key, documents),
        body=body,
        source_note=source_note,
    )


def _rail(slug: str, current: str, documents: list[dict[str, Any]]) -> str:
    items = []
    for document in documents:
        key = html_escape.escape(document.get("key", ""))
        title = html_escape.escape(document.get("title", key))
        current_attr = ' aria-current="page"' if document.get("key") == current else ""
        items.append(f'<li><a href="/project/{slug}/docs/{key}"{current_attr}>{title}</a></li>')
    return "\n".join(items)


_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — {project}</title>
<link rel="stylesheet" href="/document.css">
</head><body>
<header class="top no-print">
  <a class="brand" href="/project/{slug}"><span class="brand-mark"></span>{project}</a>
  <button class="btn" onclick="window.print()">Print / PDF</button>
</header>
<nav class="crumb no-print"><a href="/">Portal</a> › <a href="/project/{slug}">{project}</a> › {title}</nav>
<main class="doc-layout">
  <aside class="doc-rail no-print"><ul>{rail}</ul></aside>
  <article class="doc"><h1>{title}</h1>{body}<p class="footnote">{source_note}</p></article>
</main>
</body></html>
"""
