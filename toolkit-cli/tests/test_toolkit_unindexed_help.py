"""The six non-HHC Toolkit help files remain source-bound scope records."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from research.census import (
    PageParser,
    UNINDEXED_HELP_ASSET_REVIEW,
    UNINDEXED_HELP_MISSING_TARGETS,
    UNINDEXED_HELP_REVIEW,
    inventory_unindexed_help,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]


def page_row(name: str, data: bytes) -> dict:
    parser = PageParser()
    parser.feed(data.decode("cp1252"))
    return {
        "file": name,
        "html_title": parser.title,
        "sha256": sha256(data).hexdigest(),
        "headings": parser.headings,
        "anchors": parser.anchors,
        "linked_topic_files": sorted(parser.links),
        "external_product_mentions": sorted(parser.external_product_mentions),
    }


def test_packaged_six_file_review_has_stable_ids_and_exact_source_edges() -> None:
    surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
    rows = surface["unindexed_html"]
    assert surface["counts"]["unindexed_html_files"] == len(rows) == 6
    assert [row["file"] for row in rows] == sorted(UNINDEXED_HELP_REVIEW)
    observed_assets = {}
    for row in rows:
        name = row["file"]
        role, digest = UNINDEXED_HELP_REVIEW[name]
        assert row["id"] == f"help-unindexed:{name}"
        assert row["source_path"] == f"research/vendor/toolkit-help/{name}"
        assert row["sha256"] == digest
        assert row["reviewed_role"] == role
        assert row["review_status"] == "static_markup_reviewed_runtime_unassessed"
        assert row["markup"]["form_controls"] == 0
        assert row["markup"]["inline_event_attributes"] == 0
        assert row["markup"]["inline_script_content"] == 0
        assert row["markup"]["script_elements"] == 3
        assert row["missing_html_targets"] == UNINDEXED_HELP_MISSING_TARGETS[name]
        for asset in row["asset_sources"]:
            asset_name = Path(asset["path"]).name
            assert asset["sha256"] == UNINDEXED_HELP_ASSET_REVIEW[asset_name]
            assert asset["bytes"] > 0
            observed_assets[asset_name] = asset["sha256"]
    assert observed_assets == UNINDEXED_HELP_ASSET_REVIEW
    assert surface["counts"]["topic_acceptance_verified"] == 0


def test_parity_register_keeps_reviewed_shells_pending_and_digest_bound() -> None:
    surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
    register = json.loads((ROOT / "src/cbus_toolkit/parity-obligations.json").read_text(encoding="utf-8"))
    scoped = {row["id"]: row for row in register["scope_items"] if row["kind"] == "unindexed_html"}
    assert len(scoped) == 6
    for row in surface["unindexed_html"]:
        item = scoped[f"scope:unindexed:{row['file']}"]
        assert item["source_id"] == row["id"]
        assert item["source_sha256"] == row["sha256"]
        assert item["static_role"] == row["reviewed_role"]
        assert item["review_status"] == row["review_status"]
        assets = json.dumps(row["asset_sources"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert item["source_asset_sha256"] == sha256(assets).hexdigest()
        assert item["disposition"] == "pending_analysis"
    source = json.dumps(surface["unindexed_html"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert register["source_digests"]["unindexed_help_review"] == sha256(source).hexdigest()
    assert register["census_complete"] is False


def test_reviewed_shell_inventory_records_missing_target_and_asset_hash(tmp_path: Path) -> None:
    name = "shell.htm"
    html = b'<title>Help</title><link href="base.css"><script src="help.js"></script><a href="toc.htm">Open</a>'
    (tmp_path / name).write_bytes(html)
    (tmp_path / "base.css").write_bytes(b"body{}")
    (tmp_path / "help.js").write_bytes(b"void 0;")
    assets = {
        "base.css": sha256(b"body{}").hexdigest(),
        "help.js": sha256(b"void 0;").hexdigest(),
    }
    pages = {name: page_row(name, html)}
    review = {name: ("help_navigation_template", sha256(html).hexdigest())}
    rows = inventory_unindexed_help(
        tmp_path, pages, set(), review=review,
        asset_review=assets, missing_review={name: ["toc.htm"]},
    )
    assert rows[0]["id"] == "help-unindexed:shell.htm"
    assert rows[0]["missing_html_targets"] == ["toc.htm"]
    assert [item["sha256"] for item in rows[0]["asset_sources"]] == [assets["base.css"], assets["help.js"]]

    (tmp_path / "help.js").write_bytes(b"changed")
    with pytest.raises(ValueError, match="asset changed"):
        inventory_unindexed_help(
            tmp_path, pages, set(), review=review,
            asset_review=assets, missing_review={name: ["toc.htm"]},
        )


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (b'<script src="../private.js"></script>', "unsafe asset"),
        (b'<form><input name="write"></form>', "renewed review"),
        (b'<a onclick="run()">Go</a>', "renewed review"),
        (b'<script>run()</script>', "renewed review"),
    ],
)
def test_review_rejects_new_interaction_or_unsafe_asset(
    tmp_path: Path, html: bytes, message: str
) -> None:
    name = "shell.htm"
    (tmp_path / name).write_bytes(html)
    with pytest.raises(ValueError, match=message):
        inventory_unindexed_help(
            tmp_path, {name: page_row(name, html)}, set(),
            review={name: ("help_navigation_template", sha256(html).hexdigest())},
            asset_review={}, missing_review={name: []},
        )


def test_review_rejects_changed_html_and_new_unindexed_file(tmp_path: Path) -> None:
    name = "shell.htm"
    html = b"<title>Help</title>"
    (tmp_path / name).write_bytes(html)
    pages = {name: page_row(name, html)}
    review = {name: ("help_navigation_template", sha256(html).hexdigest())}
    (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="source changed"):
        inventory_unindexed_help(tmp_path, pages, set(), review=review,
                                 asset_review={}, missing_review={name: []})
    pages["new.htm"] = page_row("new.htm", b"new")
    with pytest.raises(ValueError, match="six-file set"):
        inventory_unindexed_help(tmp_path, pages, set(), review=review,
                                 asset_review={}, missing_review={name: []})


def test_validator_rejects_falsely_resolved_unindexed_review() -> None:
    surface = json.loads((ROOT / "docs/toolkit-surface.json").read_text(encoding="utf-8"))
    surface["unindexed_html"][0]["review_status"] = "runtime_accepted"
    with pytest.raises(ValueError, match="source or role changed"):
        validate(surface)
