"""Owned native C-Gate 3.4 DBSETXML unsaved-change lifecycle, without live I/O."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "rust/testdata/fixtures/native_cgate_dbsetxml_lifecycle.json"
SCRIPT = ROOT / "toolkit-cli/research/cgate_dbsetxml_lifecycle.py"
HARNESS = ROOT / "toolkit-cli/research/local_cgate.py"


def capture():
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def rows():
    return {row["tag"]: row for row in capture()["cases"] if row["tag"] is not None}


def disks(phase):
    return {row["disk"]: row["files"] for row in capture()["cases"]
            if row["tag"] is None and row["phase"] == phase}


def status(row):
    return int(row["response_lines"][-1].split()[1])


def units(row):
    tag = row["tag"]
    prefix = f"[{tag}] 347-"
    document = ET.fromstring(row["response_lines"][2][len(prefix):])
    nodes = [document] if document.tag == "Unit" else document.findall("Unit")
    return [(unit.findtext("TagName"), unit.findtext("Address")) for unit in nodes]


def test_capture_is_source_bound_and_every_owned_process_was_cleaned_up():
    evidence = capture()
    assert evidence["schema"] == "native-cgate-dbsetxml-lifecycle-v1"
    assert evidence["capture_script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert evidence["service_harness_sha256"] == hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    assert evidence["oracle"] == {
        "jar_sha256": "3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630",
        "java_sha256": "94e156397958bb83fda31ee16200580fd083b0fc0ed4a9ce795cfa44ff8e72f4",
        "version": "3.4.0 build 2001",
        "physical_endpoint": False,
    }
    assert [phase["phase"] for phase in evidence["phases"]] == [
        "no-autosave", "restart-after-no-autosave", "autosave", "restart-after-autosave"]
    for phase in evidence["phases"]:
        assert phase["greeting"] == (
            "201 Service ready: Schneider Electric C-Gate Version: v3.4.0 (build 2001) "
            "#cmd-syntax=1.0\r\n")
        assert phase["owned_loopback_listeners"] is True
        assert len(phase["listeners"]) == 6
        assert all(listener.startswith("127.0.0.1:") for listener in phase["listeners"])
        for key in ("cleanup_complete", "process_exit_confirmed", "work_removed"):
            assert phase[key] is True
    assert [phase["tag_autosave"] for phase in evidence["phases"]] == ["no", "no", "yes", "yes"]
    assert [phase["terminated_with_sigterm"] for phase in evidence["phases"]] == [True, False, True, False]
    for row in rows().values():
        assert all(line.startswith(f"[{row['tag']}] ") for line in row["response_lines"])
        assert "/var/folders" not in "".join(row["response_lines"])


def test_dbsetxml_and_dbset_are_discarded_by_close_until_saved():
    case = rows()
    assert status(case[106]) == 301
    assert units(case[107]) == [("UnsavedName", "20"), ("UnsavedName", "21")]
    assert [status(case[tag]) for tag in (108, 109, 110)] == [200, 200, 200]
    assert units(case[111]) == [("SavedName", "20")]
    assert status(case[112]) == 401
    # SAVE before CLOSE keeps the replacement.
    assert units(case[118]) == [("ResavedName", "20"), ("ResavedName", "21")]
    # LOAD of a loaded project is a no-op that keeps unsaved edits.
    assert status(case[120]) == 200
    assert units(case[121]) == [("UnsavedName", "20")]
    # Neither that DBSETXML nor a scalar DBSET survives CLOSE/LOAD.
    assert status(case[122]) == 200
    assert units(case[126]) == [("ResavedName", "20")]


def test_project_file_changes_only_on_save_and_restart_loads_the_saved_tree():
    for phase in ("no-autosave", "autosave"):
        disk = disks(phase)
        assert disk["after-create"] == {} and disk["after-unsaved-dbsetxml"] == {}
        saved = disk["after-save"]["XLIFE/XLIFE.db"]
        assert saved["markers"] == ["SavedName"]
        assert disk["after-unsaved-replacement"]["XLIFE/XLIFE.db"] == saved
        assert disk["after-close-without-save"]["XLIFE/XLIFE.db"] == saved
        assert disk["before-sigterm"] == disk["after-sigterm"]
    resaved = disks("no-autosave")["after-resave"]
    assert resaved["XLIFE/XLIFE.db"]["markers"] == ["ResavedName"]
    assert resaved["XLIFE/XLIFE.db.old"]["markers"] == ["SavedName"]
    case = rows()
    # After a SIGTERM restart the unsaved RestartName edit is gone.
    assert status(case[300]) == 124
    assert units(case[303]) == [("ResavedName", "20"), ("ResavedName", "21")]
    # tag-autosave=yes does not save a DBSETXML replacement.
    assert units(case[510]) == [("SavedName", "20")]
    assert units(case[702]) == [("SavedName", "20")]
