"""Owned native C-Gate 3.4 seeded shared-OID index probe, without live I/O."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = {profile: ROOT / f"rust/testdata/fixtures/native_cgate_oid_index_probe_{profile}.json"
            for profile in ("mixed", "units", "cross")}
SCRIPT = ROOT / "toolkit-cli/research/cgate_oid_index_probe.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def capture(profile):
    return json.loads(FIXTURES[profile].read_text(encoding="utf-8"))


def walk(plan):
    """Native index registration order: Networks as created, then each
    Network's Applications with their Groups and Levels, then its Units."""
    objects = []
    for network in plan["create_order"]:
        content = plan["networks"][str(network)]
        for app in content["applications"]:
            objects.append(("Application", app["tag"], app["oid"], ()))
            for group in app["groups"]:
                objects.append(("Group", group["tag"], group["oid"], (app["tag"],)))
                for level in group["levels"]:
                    objects.append(("Level", level["tag"], level["oid"], (app["tag"], group["tag"])))
        for unit in content["units"]:
            objects.append(("Unit", unit["tag"], unit["oid"], ()))
    return objects


def last(objects, oid):
    return next(((kind, tag) for kind, tag, candidate, _ in reversed(objects) if candidate == oid), None)


@pytest.mark.parametrize("profile", ["mixed", "units", "cross"])
def test_capture_is_source_bound_and_disposable(profile):
    evidence = capture(profile)
    assert evidence["schema"] == "cgate-oid-index-probe-v1"
    assert evidence["profile"] == profile
    assert evidence["product"] == "native"
    assert evidence["probe_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert evidence["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    oracle = evidence["oracle"]
    assert oracle["jar_sha256"] == "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630"
    assert oracle["java_sha256"] == "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4"
    for key in ("owned_loopback_listeners", "cleanup_complete", "process_exit_confirmed", "work_removed"):
        assert oracle[key] is True
    assert all(listener.startswith("127.0.0.1:") for listener in oracle["listeners"])
    assert evidence["physical_endpoint"] is False
    assert [seed["seed"] for seed in evidence["seeds"]] == list(range(1, 13))


@pytest.mark.parametrize("profile", ["mixed", "units", "cross"])
def test_last_registered_object_wins_and_delete_leaves_descendant_keys_stale(profile):
    evidence = capture(profile)
    compared = 0
    for seed in evidence["seeds"]:
        steps = {step["step"]: step for step in seed["steps"]}
        assert all(status == 301 for status in steps["submit"]["statuses"])
        live = walk(seed["plan"])

        def check(step):
            nonlocal compared
            for oid, observed in steps[step]["selected"].items():
                got = (observed["element"], observed["tag"]) if observed["status"] == 344 else None
                assert got == last(live, oid), (seed["seed"], step, oid)
                compared += 1

        check("submitted")
        check("reloaded")
        # DBDELETE removes only the deleted object's own key. Keys of its
        # descendants stay in the index, so deleting one of those later is a
        # 200 no-op on the live tree. Deleted keys read 401 until a rebuild.
        index = {oid: last(live, oid) for oid in evidence["shared_oids"]}
        for oid in evidence["shared_oids"]:
            hit = index.pop(oid)
            if hit and any(tag == hit[1] for _, tag, _, _ in live):
                live = [item for item in live if item[1] != hit[1] and hit[1] not in item[3]]
        assert all(value["status"] == 401 for value in steps["deleted"]["selected"].values())
        assert steps["unrelated-dbset"]["status"] == 200
        check("after-unrelated-dbset")
        check("deleted-reloaded")
    assert compared == 12 * 4 * 3
