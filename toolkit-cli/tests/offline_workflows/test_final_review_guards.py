"""Bounded regressions for confirmed final-review findings only."""
from pathlib import Path
from unittest.mock import patch
import hashlib
import json

import pytest

from cbus_toolkit.offline_workflows import catalogue_groups, catalogue_groups_input, cli

EXAMPLES = Path(__file__).resolve().parents[2] / "src/cbus_toolkit/offline_workflows/examples"


def nested_root_document():
    document = json.loads((EXAMPLES / "catalogue-groups.json").read_bytes())
    original = bytes.fromhex(document["catalogue_hex"]).decode()
    unit = original.split("<Units>", 1)[1].split("</Units>", 1)[0]
    poisoned = "<CBusUnits><Units>" + unit + unit.replace("</Unit>",
        "<CBusUnits><Units>" + unit + "</Units></CBusUnits></Unit>") + "</Units></CBusUnits>"
    document["catalogue_hex"] = poisoned.encode().hex()
    document["selection"]["unit_id"] = hashlib.sha256(poisoned.encode()).hexdigest() + ":/CBusUnits/Units[1]/Unit[1]"
    return document, poisoned.encode()


def test_nested_catalogue_root_refuses_instead_of_omitting_source_units():
    _, source = nested_root_document()
    assert source.count(b"<Unit>") == 3
    with pytest.raises(catalogue_groups.CatalogueGroupsError) as error:
        catalogue_groups.CatalogueIndex.from_bytes(source)
    assert error.value.code == "unsupported_catalogue_shape"


@pytest.mark.parametrize("operation", ("inspect", "validate", "plan"))
def test_nested_root_cannot_admit_an_unaffected_outer_selection(operation):
    document, _ = nested_root_document()
    report = catalogue_groups_input.evaluate(document, operation)
    assert report["outcome"] == "unsupported"
    assert report["validation_passed"] is False


@pytest.mark.parametrize("sync_number", (1, 2), ids=("temporary-sync", "parent-sync"))
def test_same_inode_same_length_mutation_during_sync_never_returns_success(tmp_path, sync_number):
    folder = tmp_path.resolve()
    output = folder / "report.json"
    intended = b'{"execution_enabled":false}\n'
    changed = b'{"execution_enabled":true }\n'
    assert len(intended) == len(changed)
    original_sync = cli.os.fsync
    calls = 0
    def mutate(descriptor):
        nonlocal calls
        original_sync(descriptor)
        calls += 1
        if calls == sync_number:
            source = output if output.exists() else next(folder.glob(".cbus-offline-*.tmp"))
            source.write_bytes(changed)
    with patch.object(cli.os, "fsync", mutate):
        with pytest.raises(cli.FileBoundaryError) as error:
            cli.write_new_output(output, intended)
    assert error.value.code == ("output_changed" if sync_number == 1 else "output_published_unconfirmed")
    if sync_number == 1:
        assert not output.exists()
    else:
        assert output.read_bytes() == changed
    assert not list(folder.glob(".cbus-offline-*.tmp"))


def test_successfully_published_report_matches_exact_intended_bytes(tmp_path):
    output = tmp_path.resolve() / "report.json"
    intended = b'{"execution_enabled":false}\n'
    cli.write_new_output(output, intended)
    assert output.read_bytes() == intended
    assert output.stat().st_mode & 0o777 == 0o600
