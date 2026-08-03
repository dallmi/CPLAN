"""The standalone studio build: one offline, read-only file out of the database.

The assertions that matter are the two guarantees the artefact makes and cannot
check for itself once it has been handed to somebody:

* it is **complete** — no asset is left behind as an external reference, and
* it is **offline** — nothing in it points at a network location.

Everything else here is scaffolding for those two.
"""

import json
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from pipeline.api.app import Activity, Base, SyncRun
from pipeline.api.database import create_cplan_engine
from pipeline.scripts.build_studio_standalone import (
    build,
    collect_snapshot,
    inline_assets,
    payload_script,
)


@pytest.fixture
def database_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'cplan-standalone-test.sqlite3'}"
    engine = create_cplan_engine(url)
    Base.metadata.create_all(engine)
    yield url
    Base.metadata.drop_all(engine)
    engine.dispose()


def _seed(database_url, **overrides):
    engine = create_cplan_engine(database_url)
    fields = {
        "id": uuid.uuid4(),
        "source_type": "internal",
        "activity_name": "Quarterly results announcement",
        "channel": "Email",
        "start_date": datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
        "version": 1,
    }
    fields.update(overrides)
    try:
        with Session(engine) as session:
            session.add(Activity(**fields))
            session.commit()
    finally:
        engine.dispose()
    return fields


def _embedded_payload(html):
    match = re.search(r"window\.__CPLAN_SNAPSHOT__ = (\{.*?\});\n", html, re.DOTALL)
    assert match, "the built file carries no snapshot payload"
    return json.loads(match.group(1))


# --- the two guarantees -----------------------------------------------------

def test_no_asset_is_left_as_an_external_reference(database_url, tmp_path):
    """Every stylesheet and script from index.html ends up inside the file.

    A surviving `src=`/`href=` would make the artefact silently incomplete: it
    still opens, and simply renders unstyled or dead, wherever it is opened.
    """
    _seed(database_url)
    out = build(database_url, tmp_path / "standalone.html")
    html = out.read_text(encoding="utf-8")

    assert not re.search(r"<script\s+src=", html)
    assert not re.search(r'<link\s+rel="stylesheet"', html)
    # The assets are actually present, not merely unreferenced.
    for fingerprint in ("SnapshotPlanningRepository", "DatabasePlanningRepository", "channel-chip"):
        assert fingerprint in html


def test_nothing_in_the_file_points_at_the_network(database_url, tmp_path):
    """The offline guarantee, checked rather than assumed.

    The studio has no CDN dependency today. This test is what keeps it that way:
    adding one would break the standalone build's whole reason to exist, and it
    would otherwise only show up on a machine with no internet.
    """
    _seed(database_url)
    out = build(database_url, tmp_path / "standalone.html")
    html = out.read_text(encoding="utf-8")

    # XML namespace URLs in xlsx.js are identifiers inside generated workbook
    # XML, never fetched. Everything else that looks like a URL is a finding.
    urls = [
        url for url in re.findall(r'https?://[^\s"\'<>)]+', html)
        if "schemas.openxmlformats.org" not in url and "www.w3.org" not in url
    ]
    assert urls == [], f"standalone file references external URLs: {urls}"


# --- payload ----------------------------------------------------------------

def test_activities_reach_the_payload_in_the_api_wire_shape(database_url, tmp_path):
    seeded = _seed(database_url)
    out = build(database_url, tmp_path / "standalone.html")

    payload = _embedded_payload(out.read_text(encoding="utf-8"))
    assert payload["items"][0]["activity_name"] == seeded["activity_name"]
    assert payload["items"][0]["id"] == str(seeded["id"])
    assert payload["exported_at"].endswith("Z")


def test_a_database_with_no_sync_run_reports_never_synced(database_url):
    _seed(database_url)
    assert collect_snapshot(database_url)["sync_run"] == {"status": "never_synced"}


def test_the_latest_sync_run_is_embedded(database_url):
    _seed(database_url)
    engine = create_cplan_engine(database_url)
    try:
        with Session(engine) as session:
            session.add(SyncRun(snapshot_path="communications.parquet", created=3, updated=2))
            session.commit()
    finally:
        engine.dispose()

    sync_run = collect_snapshot(database_url)["sync_run"]
    assert sync_run["created"] == 3
    assert sync_run["updated"] == 2


def test_a_closing_script_tag_in_the_data_cannot_break_out_of_the_payload():
    """An activity named `</script>` must not end the script block early.

    This is the one input that turns a data row into markup. Worth a test of its
    own because the failure is total — the page renders as raw text — and it
    would only ever be triggered by real planning data, never by a fixture.
    """
    script = payload_script({"items": [{"activity_name": "</script><h1>x"}]})
    assert "</script><h1>" not in script[: script.rindex("</script>")]
    assert "\\u003c/script" in script


# --- asset inlining ---------------------------------------------------------

def test_inlining_is_driven_by_index_html_not_by_a_hardcoded_list(tmp_path):
    """A new script tag in index.html is picked up without touching the build.

    The asset list living in one place is what stops the standalone from
    drifting into a second, quietly stale implementation of the studio.
    """
    studio = tmp_path / "studio"
    studio.mkdir()
    (studio / "styles.css").write_text("body{color:red}", encoding="utf-8")
    (studio / "brand-new.js").write_text("var freshlyAdded = 1;", encoding="utf-8")
    html = '<link rel="stylesheet" href="styles.css"><script src="brand-new.js"></script>'

    result, inlined = inline_assets(html, studio)

    assert inlined == ["styles.css", "brand-new.js"]
    assert "body{color:red}" in result
    assert "var freshlyAdded = 1;" in result


def test_a_missing_asset_fails_the_build_instead_of_shipping_a_broken_file(tmp_path):
    studio = tmp_path / "studio"
    studio.mkdir()
    with pytest.raises(FileNotFoundError, match="gone.js"):
        inline_assets('<script src="gone.js"></script>', studio)


def test_absolute_urls_are_left_alone_so_a_new_cdn_dependency_stays_visible(tmp_path):
    """Not an endorsement — the opposite.

    Swallowing an external script would hide exactly the change that breaks the
    offline guarantee. Left in place, it fails the network assertion above.
    """
    studio = tmp_path / "studio"
    studio.mkdir()
    html = '<script src="https://cdn.example.com/chart.js"></script>'
    result, inlined = inline_assets(html, studio)
    assert result == html
    assert inlined == []
