"""Pure route planning from legacy project topology; no endpoint is opened."""
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from cbus_toolkit.commissioning_route import (
    assert_fresh_project,
    plan_commissioning_route,
    project_sha256,
)
from cbus_toolkit.project import ProjectDocument, ProjectError


def network(address, interface_type, interface_address, *, units=()):
    children = "".join(
        f"<Unit><Address>{unit}</Address><UnitType>{unit_type}</UnitType></Unit>"
        for unit, unit_type in units
    )
    return (
        f"<Network><TagName>N{address}</TagName><Address>{address}</Address>"
        f"<Interface><InterfaceType>{interface_type}</InterfaceType>"
        f"<InterfaceAddress>{interface_address}</InterfaceAddress></Interface>"
        f"{children}</Network>"
    )


def document(networks, *, name="HOUSE"):
    raw = (
        f"<Installation><Project><TagName>{name}</TagName>"
        f"{''.join(networks)}</Project></Installation>"
    ).encode()
    return raw, ProjectDocument.from_bytes(raw)


def line(depth=2):
    addresses = tuple(range(254, 254 - depth - 1, -1))
    networks = []
    for index, address in enumerate(addresses):
        units = []
        if index + 1 < len(addresses):
            units.append((addresses[index + 1], "BRIDGE2N"))
        if index == len(addresses) - 1:
            units.append((5, "KEYGL5"))
        if index == 0:
            networks.append(network(address, "CNI", "127.0.0.1:10001", units=units))
        else:
            networks.append(
                network(address, "Bridge", f"{addresses[index - 1]}/p/{address}", units=units)
            )
    return document(networks)


def plan(raw, project, *, source=254, target=252, unit=5, local=16, name="HOUSE"):
    return plan_commissioning_route(
        project,
        project_digest=project_sha256(raw),
        source_network=source,
        target_network=target,
        target_unit=unit,
        local_unit=local,
        expected_ack_tag=0x55,
        expected_project_name=name,
    )


def test_two_bridge_plan_derives_outgoing_and_independent_ack_path():
    raw, project = line()
    result = plan(raw, project)
    assert result.bridges == (253, 252)
    assert result.expected.as_dict() == {
        "outer_source_byte": 253,
        "destination_byte": 16,
        "route_entries": [252, 5],
    }
    report = result.as_dict()
    assert report["project_sha256"] == project_sha256(raw)
    assert report["target_unit_type"] == "KEYGL5"
    assert report["expected_ack_tag"] == 0x55
    assert report["logical_network_resolved"] is True
    assert report["physical_bridge_acceptance_verified"] is False
    assert report["nonvolatile_persistence_verified"] is False


def test_read_plan_uses_the_same_route_without_inventing_an_ack_tag():
    raw, project = line()
    result = plan_commissioning_route(
        project, project_digest=project_sha256(raw), source_network=254,
        target_network=252, target_unit=5, local_unit=16,
        expected_project_name="HOUSE",
    )
    assert result.bridges == (253, 252)
    report = result.as_dict()
    assert report["expected_reply_path"] == {
        "outer_source_byte": 253, "destination_byte": 16,
        "route_entries": [252, 5],
    }
    assert "expected_ack_path" not in report
    assert "expected_ack_tag" not in report


def test_read_route_boundaries_cover_direct_through_six_bridges():
    for depth in range(7):
        raw, project = line(depth)
        result = plan_commissioning_route(
            project, project_digest=project_sha256(raw), source_network=254,
            target_network=254 - depth, target_unit=5, local_unit=16,
        )
        expected_bridges = tuple(range(253, 253 - depth, -1))
        assert result.bridges == expected_bridges
        path = result.as_dict()["expected_reply_path"]
        assert path["outer_source_byte"] == (expected_bridges[0] if depth else 5)
        assert path["destination_byte"] == 16
        assert path["route_entries"] == list(expected_bridges[1:]) + ([5] if depth else [])


def test_direct_and_six_bridge_boundaries_are_exact():
    direct_raw, direct_project = document([
        network(254, "Serial", "/dev/owned", units=((5, "KEYGL5"),)),
    ])
    direct = plan(direct_raw, direct_project, target=254)
    assert direct.bridges == ()
    assert direct.expected.as_dict() == {
        "outer_source_byte": 5,
        "destination_byte": 16,
        "route_entries": [],
    }

    raw, project = line(6)
    routed = plan(raw, project, target=248)
    assert routed.bridges == (253, 252, 251, 250, 249, 248)
    assert routed.expected.route_entries == (252, 251, 250, 249, 248, 5)


def test_ambiguous_cycle_disconnected_and_overdepth_fail_closed():
    duplicate_raw, duplicate = document([
        network(254, "CNI", "owned", units=((5, "KEYGL5"),)),
        network(254, "CNI", "other", units=((5, "KEYGL5"),)),
    ])
    with pytest.raises(ProjectError, match="Duplicate Network address|duplicate network address"):
        plan(duplicate_raw, duplicate, target=254)

    cycle_raw, cycle = document([
        network(254, "CNI", "owned", units=((253, "BRIDGE2N"),)),
        network(253, "Bridge", "252/p/253", units=((252, "BRIDGE2N"), (5, "KEYGL5"))),
        network(252, "Bridge", "253/p/252", units=((253, "BRIDGE2N"),)),
    ])
    with pytest.raises(ProjectError, match="cycle"):
        plan(cycle_raw, cycle, target=253)

    disconnected_raw, disconnected = document([
        network(254, "CNI", "owned", units=()),
        network(253, "Serial", "other", units=((5, "KEYGL5"),)),
    ])
    with pytest.raises(ProjectError, match="disconnected"):
        plan(disconnected_raw, disconnected, target=253)

    long_raw, long_project = line(7)
    with pytest.raises(ProjectError, match="six-bridge"):
        plan(long_raw, long_project, target=247)


def test_missing_malformed_and_unsupported_transitions_fail_before_a_plan():
    cases = [
        (
            [
                network(254, "CNI", "owned", units=()),
                network(253, "Bridge", "254/p/253", units=((5, "KEYGL5"),)),
            ],
            "no bridge unit",
        ),
        (
            [
                network(254, "CNI", "owned", units=((253, "RELAY"),)),
                network(253, "Bridge", "254/p/253", units=((5, "KEYGL5"),)),
            ],
            "unsupported bridge type",
        ),
        (
            [
                network(254, "CNI", "owned", units=((253, "BRIDGE2N"),)),
                network(253, "Bridge", "bad", units=((5, "KEYGL5"),)),
            ],
            "malformed",
        ),
        (
            [network(254, "IP", "owned", units=((5, "KEYGL5"),))],
            "directly attached",
        ),
    ]
    for networks, message in cases:
        raw, project = document(networks)
        with pytest.raises(ProjectError, match=message):
            plan(raw, project, target=253 if len(networks) > 1 else 254)


def test_reverse_and_sibling_starts_are_not_inferred_for_a_direct_pci():
    raw, project = document([
        network(254, "CNI", "owned", units=((253, "BRIDGE2N"), (252, "BRIDGE2N"))),
        network(253, "Bridge", "254/p/253", units=((254, "BRIDGE2N"), (5, "KEYGL5"))),
        network(252, "Bridge", "254/p/252", units=((254, "BRIDGE2N"), (6, "KEYGL5"))),
    ])
    for source, target, unit in ((253, 254, 5), (253, 252, 6)):
        with pytest.raises(ProjectError, match="reverse and sibling bridge starts are unsupported"):
            plan(raw, project, source=source, target=target, unit=unit)


def test_target_and_project_identity_are_exact_and_output_is_preserving():
    raw, project = line()
    with pytest.raises(ProjectError, match="Project identity mismatch"):
        plan(raw, project, name="OTHER")
    with pytest.raises(ProjectError, match="Target unit 6 is absent"):
        plan(raw, project, unit=6)
    result = plan(raw, project)
    first = result.as_dict()
    first["bridges"].append(1)
    first["expected_ack_path"]["route_entries"].append(1)
    assert result.bridges == (253, 252)
    assert result.expected.route_entries == (252, 5)


def test_stale_snapshot_is_rejected_and_recovery_uses_fresh_bytes():
    raw, project = line()
    result = plan(raw, project)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "house.xml"
        path.write_bytes(raw)
        assert_fresh_project(path, result.project_sha256)
        path.write_bytes(raw.replace(b"KEYGL5", b"KEYE1 "))
        with pytest.raises(ProjectError, match="stale or was substituted"):
            assert_fresh_project(path, result.project_sha256)
        path.unlink()
        with pytest.raises(ProjectError, match="Unable to re-read"):
            assert_fresh_project(path, result.project_sha256)


def test_cbz_plan_parses_the_exact_bytes_bound_by_the_digest():
    xml, _ = line()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("project.xml", xml)
        archive.writestr("retained.bin", b"opaque")
    snapshot = output.getvalue()
    project = ProjectDocument.from_snapshot(snapshot)
    result = plan(snapshot, project)
    assert result.project_format == "legacy-cbz"
    assert result.project_sha256 == project_sha256(snapshot)
    assert project.to_xml_bytes() == xml
