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
    # content stream when `position: sticky` exists anywhere in the DOM.
    html = render_document("cplan", "data-model", "Communication Planning", published_documents("cplan"))
    assert "position: sticky" not in html or "@media screen" in html
