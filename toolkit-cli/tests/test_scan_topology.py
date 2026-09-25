"""RED/GREEN tests for the pure offline scan-topology planner (no I/O)."""
import copy

import pytest

from cbus_toolkit.scan_topology import BridgeNode, plan_reconciliation, validate_topology


def test_empty_inputs_rejected():
    with pytest.raises(ValueError, match=r"^topology must contain at least one bridge$"):
        validate_topology([])
    with pytest.raises(ValueError, match=r"^topology must contain at least one bridge$"):
        validate_topology(())
    with pytest.raises(ValueError, match=r"^topology must contain at least one bridge$"):
        validate_topology(None)
    with pytest.raises(ValueError, match=r"^topology must contain at least one bridge$"):
        validate_topology(iter([]))
    with pytest.raises(ValueError, match=r"^snapshots must contain at least one network$"):
        plan_reconciliation({}, {})
    with pytest.raises(ValueError, match=r"^duplicate network_id: 0$"):
        validate_topology([BridgeNode(0, 1, (1,)), BridgeNode(0, 2, ())])


def test_generator_input_not_exhausted():
    def gen():
        yield BridgeNode(0, 1, (1,))
        yield BridgeNode(1, 2, ())

    assert validate_topology(gen()) == [BridgeNode(0, 1, (1,)), BridgeNode(1, 2, ())]


def test_duplicate_serials_flagged():
    local = {0: [(1, "S1")]}
    remote = {0: [(1, "S1"), (2, "S1")]}
    plan = plan_reconciliation(local, remote)
    assert plan["duplicates"] == [{"serial": "S1", "locations": [[0, 1], [0, 2]]}]
    assert plan["moves"] == []
    assert plan["adds"] == []


def test_moves_detected():
    local = {0: [(1, "S1")]}
    remote = {1: [(2, "S1")]}
    plan = plan_reconciliation(local, remote)
    assert plan["moves"] == [{"serial": "S1", "from": [0, 1], "to": [1, 2]}]
    assert plan["adds"] == []
    assert plan["removes"] == []
    assert plan["duplicates"] == []


def test_adds_detected():
    local = {0: [(1, "S1")]}
    remote = {0: [(1, "S1")], 1: [(2, "S2")]}
    plan = plan_reconciliation(local, remote)
    assert plan["adds"] == [{"serial": "S2", "network_id": 1, "unit_address": 2}]
    assert plan["moves"] == []
    assert plan["removes"] == []


def test_conflicts_detected():
    local = {0: [(1, "S1")]}
    remote = {0: [(1, "S2")]}
    plan = plan_reconciliation(local, remote)
    assert plan["conflicts"] == [
        {"network_id": 0, "unit_address": 1, "local_serial": "S1", "remote_serial": "S2"}
    ]


def test_local_only_reported_as_removes():
    local = {0: [(1, "S1"), (2, "S2")]}
    remote = {0: [(1, "S1")]}
    plan = plan_reconciliation(local, remote)
    assert plan["removes"] == [{"serial": "S2", "network_id": 0, "unit_address": 2}]
    assert plan["adds"] == []
    assert plan["moves"] == []


def test_multi_bridge_cycle_rejected():
    bridges = [BridgeNode(0, 1, (1,)), BridgeNode(1, 2, (2,)), BridgeNode(2, 3, (0,))]
    with pytest.raises(ValueError, match=r"^topology cycle detected involving network \d+$"):
        validate_topology(bridges)


def test_self_cycle_rejected():
    with pytest.raises(ValueError, match=r"^topology cycle detected involving network 0$"):
        validate_topology([BridgeNode(0, 1, (0,))])


def test_dangling_child_rejected():
    with pytest.raises(ValueError, match=r"^unknown child network: 1$"):
        validate_topology([BridgeNode(0, 1, (1,))])


def test_duplicate_child_networks_rejected():
    with pytest.raises(ValueError, match=r"duplicate child network"):
        BridgeNode(0, 1, (1, 1))


def test_bridge_bounds_rejected():
    with pytest.raises(ValueError, match=r"invalid network_id"):
        BridgeNode(256, 1, ())
    with pytest.raises(ValueError, match=r"invalid network_id"):
        BridgeNode(-1, 1, ())
    with pytest.raises(ValueError, match=r"invalid bridge_address"):
        BridgeNode(0, 256, ())
    with pytest.raises(ValueError, match=r"invalid child network_id"):
        BridgeNode(0, 1, (256,))


def test_bad_shape_rejected():
    with pytest.raises(ValueError, match=r"snapshot must be a mapping"):
        plan_reconciliation([], {0: [(1, "S1")]})
    with pytest.raises(ValueError, match=r"entries must be a list"):
        plan_reconciliation({0: [(1, "S1"), "bad"]}, {0: [(1, "S1")]})
    with pytest.raises(ValueError, match=r"invalid unit_address"):
        plan_reconciliation({0: [(999, "S1")]}, {0: [(1, "S1")]})
    with pytest.raises(ValueError, match=r"invalid serial"):
        plan_reconciliation({0: [(1, "")]}, {0: [(1, "S1")]})
    with pytest.raises(ValueError, match=r"each bridge must be a BridgeNode"):
        validate_topology([BridgeNode(0, 1, ()), "not-a-node"])


def test_duplicate_location_rejected():
    with pytest.raises(ValueError, match=r"duplicate location \(network 0, unit 1\) in local snapshot"):
        plan_reconciliation({0: [(1, "S1"), (1, "S2")]}, {0: [(1, "S1")]})
    with pytest.raises(ValueError, match=r"duplicate location \(network 0, unit 1\) in remote snapshot"):
        plan_reconciliation({0: [(1, "S1")]}, {0: [(1, "S1"), (1, "S2")]})


def test_deterministic_ordering():
    local = {0: [(1, "S1")]}
    remote_a = {0: [(1, "S1")], 1: [(5, "S9"), (3, "S3"), (1, "S5")]}
    remote_b = {1: [(1, "S5"), (3, "S3"), (5, "S9")], 0: [(1, "S1")]}
    first = plan_reconciliation(local, remote_a)
    second = plan_reconciliation(local, remote_b)
    assert first == second
    assert [item["serial"] for item in first["adds"]] == ["S3", "S5", "S9"]
    assert first["adds"] == sorted(
        first["adds"], key=lambda item: (item["serial"], item["network_id"], item["unit_address"])
    )
    assert validate_topology([BridgeNode(1, 2, ()), BridgeNode(0, 1, (1,))]) == [
        BridgeNode(0, 1, (1,)),
        BridgeNode(1, 2, ()),
    ]


def test_unrelated_value_preservation():
    note = {"nested": [1, 2, {"key": "value"}]}
    local = {0: [(1, "S1")], "note": note, "tag": "local-tag"}
    remote = {0: [(1, "S2")], "note": {"other": True}, "count": 7}
    local_snapshot = copy.deepcopy(local)
    plan = plan_reconciliation(local, remote)
    assert plan["echo"]["local_extra"] == {"note": note, "tag": "local-tag"}
    assert plan["echo"]["remote_extra"] == {"note": {"other": True}, "count": 7}
    # Echo is a deep copy: equality holds but identity does not.
    assert plan["echo"]["local_extra"]["note"] == note
    assert plan["echo"]["local_extra"]["note"] is not note
    # Mutation isolation: mutating the plan echo leaves caller data intact.
    plan["echo"]["local_extra"]["note"]["nested"].append(99)
    assert note == {"nested": [1, 2, {"key": "value"}]}
    assert local == local_snapshot
    # Mutating caller data after planning leaves the plan intact.
    note["nested"].append(100)
    assert plan["echo"]["local_extra"]["note"] != note
    # Conflict shape is stable and sorted for the differing serial at (0, 1).
    assert plan["conflicts"] == [
        {"network_id": 0, "unit_address": 1, "local_serial": "S1", "remote_serial": "S2"}
    ]
