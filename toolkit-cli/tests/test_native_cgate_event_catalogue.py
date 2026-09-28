"""Integrity and native bounds for the owned event-catalogue receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rust/testdata/fixtures/native_cgate_event_catalogue.json"


def test_native_event_catalogue_source_and_cleanup() -> None:
    report = json.loads(FIXTURE.read_text())
    assert report["schema"] == "native-cgate-event-catalogue-v1"
    assert report["oracle"]["physical_endpoint"] is False
    for name, expected in report["oracle"]["source_hashes"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    for case in report["cases"].values():
        assert all(case["cleanup"].values())


def test_native_event_catalogue_level_and_unknown_command_bound() -> None:
    cases = json.loads(FIXTURE.read_text())["cases"]

    def codes(rows: list[str]) -> list[str]:
        return [row.split(" ", 2)[1] for row in rows]

    assert "938" not in codes(cases["7"]["early_event_rows"])
    assert "938" in codes(cases["8"]["early_event_rows"])
    assert "899" in codes(cases["9"]["early_event_rows"])
    assert "999" in codes(cases["9"]["accepted_event_rows"])
    exchanges = {row["tag"]: row for row in cases["9"]["exchanges"]}
    assert exchanges["known"]["reply"] == ["[known] 400 Syntax Error."]
    assert codes(exchanges["known"]["events"]) == ["761", "766"]
    assert exchanges["unknown"]["reply"] == ["[unknown] 400 Syntax Error."]
    assert codes(exchanges["unknown"]["events"]) == ["766"]
