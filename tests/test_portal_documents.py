"""Rendering repository markdown into portal chrome."""

from __future__ import annotations

import pytest

from pipeline.portal.documents import published_documents, render_document


def test_published_documents_lists_the_manifest_entries():
    keys = [d["key"] for d in published_documents("cplan")]
    assert "data-model" in keys
    assert "design-review-v2" not in keys


def test_render_produces_a_whole_page_with_the_document_in_it():
    html = render_document("cplan", "data-model", "Communication Planning", published_documents("cplan"))
    assert html.startswith("<!DOCTYPE html>")
    assert "Data model" in html
    assert "Communication Planning" in html


def test_render_lists_every_sibling_document_and_marks_the_current_one():
    html = render_document("cplan", "tracking-id", "Communication Planning", published_documents("cplan"))
    assert '/project/cplan/docs/data-model' in html
    assert 'aria-current="page"' in html


def test_render_refuses_an_undeclared_key():
    assert render_document("cplan", "design-review-v2", "Communication Planning", published_documents("cplan")) is None


def test_markdown_source_is_treated_as_markdown_not_html(tmp_path, monkeypatch):
    # These documents are markdown. A stray tag in one must render as text, so
    # that adding a document can never inject markup into the portal.
    source = tmp_path / "evil.md"
    source.write_text("# Title\n\n<script>alert(1)</script>\n", encoding="utf-8")
    monkeypatch.setattr("pipeline.portal.documents.manifest_path", lambda *a, **k: source)
    html = render_document("cplan", "evil", "Project", [{"key": "evil", "title": "Evil"}])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_says_so_when_the_declared_file_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.portal.documents.manifest_path", lambda *a, **k: tmp_path / "absent.md")
    html = render_document("cplan", "data-model", "Project", [{"key": "data-model", "title": "Data model"}])
    assert html is not None and "not available" in html


def test_fenced_code_does_not_get_double_escaped(tmp_path, monkeypatch):
    # A fenced code block containing '=>', '>' and single quotes must come out
    # single-escaped. The first version of this module ran html.escape() over
    # the whole source before handing it to markdown, which collided with
    # Python-Markdown's own escaping of fenced-code content: the source '>'
    # became '&gt;' in the pre-escape, then the leading '&' of that entity was
    # escaped again inside the code fence, producing the literal text
    # '&amp;gt;' instead of '>'. That is the regression this guards against.
    source = tmp_path / "snippet.md"
    source.write_text(
        "```js\nconst names = ['EMI', 'EMA'];\nreturn ch => ch.length > 0;\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("pipeline.portal.documents.manifest_path", lambda *a, **k: source)
    html = render_document("cplan", "snippet", "Project", [{"key": "snippet", "title": "Snippet"}])
    assert "&amp;gt;" not in html
    assert "&amp;#x27;" not in html
    assert "ch =&gt; ch.length &gt; 0" in html


def test_every_declared_document_renders_without_corruption():
    # A check that only ever looked at one document (data-model.md, named in
    # the brief) would not have caught the double-escaping regression above:
    # data-model.md's own code fence has no '<', '>', '&' or quote characters
    # to expose it. Render all five declared documents and check each one's
    # structure survives, so a future regression in any of them is caught.
    documents = published_documents("cplan")
    keys = {d["key"] for d in documents}
    assert keys == {
        "data-model",
        "planning-process",
        "tracking-id",
        "cross-channel-matching",
        "communication-structure",
    }
    for document in documents:
        html = render_document("cplan", document["key"], "Communication Planning", documents)
        assert html is not None
        assert "<pre><code" in html or "<p>" in html
        # Every one of these documents opens with its own top-level heading
        # in the source; the template supplies a second <h1> from the
        # manifest title. Exactly one must survive, or the page shows its
        # title twice (e.g. "Data model" from the manifest, then "Data
        # Model" from the source, one under the other).
        assert html.count("<h1") == 1, f"{document['key']!r} rendered {html.count('<h1')} <h1> elements"

    data_model_html = render_document("cplan", "data-model", "Communication Planning", documents)
    assert "<table>" in data_model_html

    cross_channel_html = render_document(
        "cplan", "cross-channel-matching", "Communication Planning", documents
    )
    assert "<code" in cross_channel_html
    assert "=&gt;" in cross_channel_html
    assert "&amp;gt;" not in cross_channel_html


def test_rendered_page_carries_no_sticky_positioning():
    # The document pages are printable; Safari's PDF writer can emit an empty
    # content stream when `position: sticky` exists anywhere in the DOM. The
    # page carries no inline CSS, so this asserts the absence outright rather
    # than the un-failable "or '@media screen' in html" it used to. The
    # stylesheet it links is checked properly in tests/test_portal_frontend.py.
    html = render_document("cplan", "data-model", "Communication Planning", published_documents("cplan"))
    assert "position: sticky" not in html
    assert "<style" not in html


def test_the_source_note_is_relative_to_the_repository_root():
    # It used to be computed as path.relative_to(path.parents[2]), which is the
    # repository root only for a path exactly three levels deep: a document
    # declared at the root rendered two directory names from ABOVE the root --
    # local, machine-specific ones -- into a published page.
    html = render_document("cplan", "data-model", "Communication Planning", published_documents("cplan"))
    assert "Source: <code>pipeline/docs/data-model.md</code>" in html


def test_a_document_declared_at_the_repository_root_names_itself_correctly(tmp_path, monkeypatch):
    from pipeline.portal.resources import REPO_ROOT

    monkeypatch.setattr("pipeline.portal.documents.manifest_path", lambda *a, **k: REPO_ROOT / "README.md")
    html = render_document("cplan", "readme", "Project", [{"key": "readme", "title": "Readme"}])
    assert "Source: <code>README.md</code>" in html


def test_changelog_style_markdown_gets_the_document_chrome_without_a_rail(tmp_path):
    from pipeline.portal.documents import render_markdown_file

    source = tmp_path / "CHANGELOG.md"
    source.write_text("# What's new\n\n## 4 August 2026\n\n- A thing changed.\n", encoding="utf-8")
    html = render_markdown_file(source, "What's new", "Communication Planning", "cplan")
    assert html.startswith("<!DOCTYPE html>")
    assert "/document.css" in html
    assert "window.print()" in html
    assert "doc-layout solo" in html
    assert "doc-rail" not in html  # nothing to switch between
    assert html.count("<h1") == 1  # the source's own leading heading is dropped
    assert "4 August 2026" in html


def test_a_declared_but_unwritten_changelog_is_a_page_not_an_error(tmp_path):
    from pipeline.portal.documents import render_markdown_file

    html = render_markdown_file(tmp_path / "absent.md", "What's new", "Project", "cplan")
    assert "Nothing has been recorded here yet." in html
    html = render_markdown_file(None, "What's new", "Project", "cplan")
    assert "Nothing has been recorded here yet." in html


def test_markdown_in_a_project_changelog_cannot_inject_markup(tmp_path):
    from pipeline.portal.documents import render_markdown_file

    source = tmp_path / "CHANGELOG.md"
    source.write_text("## 2026\n\n<script>alert(1)</script>\n", encoding="utf-8")
    html = render_markdown_file(source, "What's new", "Project", "cplan")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
