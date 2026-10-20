"""Wave-15 offline pins for topology print/image guards (P8.03 #57)."""
from __future__ import annotations

import hashlib
import json

from cbus_toolkit.cli import main
from cbus_toolkit.project_topology import FORMAT, PRINT_TITLE, _dot_id, load_topology


def _write(tmp_path, body: bytes, name="pin.xml"):
    path = tmp_path / name
    path.write_bytes(body)
    return path


def _xml() -> bytes:
    return (
        b"<Installation><Project><TagName>HOUSE</TagName>"
        b"<Network><TagName>Local</TagName><Address>254</Address>"
        b"<Interface><InterfaceType>Serial</InterfaceType>"
        b"<InterfaceAddress>COM1</InterfaceAddress></Interface>"
        b"<Unit><Address>12</Address><UnitType>RELDN8</UnitType></Unit>"
        b"</Network></Project></Installation>"
    )


def _cli(capsys, *argv):
    status = main(["project", "topology", *map(str, argv)])
    captured = capsys.readouterr()
    return status, json.loads(captured.out or captured.err)


def test_wave15_print_title_reaches_dot_label_and_svg_title(tmp_path):
    model = load_topology(_write(tmp_path, _xml()))
    expected = PRINT_TITLE.format("HOUSE")
    assert f"label={_dot_id(expected)}" in model.dot()
    assert f"<title>{expected}</title>" in model.svg()


def test_wave15_image_result_reports_format_digest_and_size(tmp_path, capsys):
    path = _write(tmp_path, _xml())
    for fmt in ("dot", "svg"):
        status, payload = _cli(capsys, path, "--format", fmt)
        assert status == 0
        image = load_topology(path).dot() if fmt == "dot" else load_topology(path).svg()
        raw = image.encode("utf-8")
        assert payload["image_format"] == fmt
        assert payload["image"] == image
        assert payload["sha256"] == hashlib.sha256(raw).hexdigest()
        assert payload["bytes"] == len(raw)


def test_wave15_bridge_label_and_far_presence_guards(tmp_path):
    single = (
        b"<Installation><Project><TagName>HOUSE</TagName>"
        b"<Network><TagName>Local</TagName><Address>254</Address>"
        b"<Interface><InterfaceType>Serial</InterfaceType>"
        b"<InterfaceAddress>COM1</InterfaceAddress></Interface>"
        b"<Unit><Address>9</Address><UnitType>BRIDGE2N</UnitType></Unit>"
        b"</Network></Project></Installation>"
    )
    lonely = load_topology(_write(tmp_path, single, "lonely.xml")).bridges()
    assert len(lonely) == 1
    assert lonely[0]["id"] == "254/9"
    assert lonely[0]["toolkit_label"] == "9/254-"
    assert lonely[0]["far_network_present"] is False
    assert lonely[0]["far_side"] is None
    paired = (
        b"<Installation><Project><TagName>HOUSE</TagName>"
        b"<Network><TagName>N254</TagName><Address>254</Address>"
        b"<Interface><InterfaceType>Serial</InterfaceType>"
        b"<InterfaceAddress>COM1</InterfaceAddress></Interface>"
        b"<Unit><Address>1</Address><UnitType>BRIDGE2N</UnitType></Unit>"
        b"</Network>"
        b"<Network><TagName>N1</TagName><Address>1</Address>"
        b"<Interface><InterfaceType>Bridge</InterfaceType>"
        b"<InterfaceAddress>254/p/1</InterfaceAddress></Interface>"
        b"<Unit><Address>254</Address><UnitType>BRIDGE2F</UnitType></Unit>"
        b"</Network></Project></Installation>"
    )
    bridge = next(
        item for item in load_topology(_write(tmp_path, paired, "paired.xml")).bridges()
        if item["id"] == "254/1"
    )
    assert bridge["toolkit_label"] == "1/254-254"
    assert bridge["far_network_present"] is True
    assert bridge["far_side"] is not None
    assert bridge["far_side"]["path"] == "/network/1/unit/254"


def test_wave15_topology_model_format_and_identity(tmp_path):
    path = _write(tmp_path, _xml())
    model = load_topology(path)
    result = model.as_dict()
    assert FORMAT == "cbus-project-topology-v1"
    assert result["format"] == "cbus-project-topology-v1"
    assert result["project"]["sha256"] == model.digest
    assert result["project"]["bytes"] == model.size == len(path.read_bytes())
