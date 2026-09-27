"""Release-specific evidence guard for P6.05's native cache-read boundary."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from research.verify_edlt_dynamic_cache_scope import FIXTURE, check_evidence


@pytest.fixture
def evidence() -> dict:
    return json.loads(FIXTURE.read_text())


def test_native_scope_evidence_is_explicit_and_consistent(evidence: dict) -> None:
    check_evidence(evidence)


@pytest.mark.parametrize("change", [
    lambda row: row["static_bytecode"]["registered_subcommands"].update(read="invented"),
    lambda row: row["owned_loopback_oracle"]["label_query_commands"].update(
        {"LABEL GET //NO_SUCH/254/p/5": ["200 OK."]}),
    lambda row: row["supported_boundary"].update(native_label_cache_inventory=True),
    lambda row: row["supported_boundary"].update(physical_firmware_protocol_absence_proven=True),
    lambda row: row["supported_boundary"].update(cmqtt_observed_traffic_is_device_readback=True),
    lambda row: row["owned_loopback_oracle"].update(cleanup_complete=False),
    lambda row: row["original_gui_project_observation"]["offline_gui"].update(
        send_labels_enabled=True),
    lambda row: row["original_gui_project_observation"]["private_project_structure"].update(
        group_value_displayed_in_gui=True),
    lambda row: row["original_gui_project_observation"]["scope"].update(
        device_cache_readback=True),
    lambda row: row["original_gui_project_observation"]["artifact_sha256"].update(
        private_project_xml="0" * 64),
])
def test_evidence_guard_rejects_overclaims_and_changed_oracle(evidence: dict, change) -> None:
    altered = deepcopy(evidence)
    change(altered)
    with pytest.raises(ValueError):
        check_evidence(altered)
