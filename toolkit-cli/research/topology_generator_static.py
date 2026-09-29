"""Verify the source-only Toolkit 1.18 topology-map rules used by ``project topology``.

Supply the original EXE and MAP explicitly. This never executes vendor code,
opens a project, accesses C-Gate, or inspects site data. It disassembles the
pinned TTopologyGenerator, TTopologyExpressFlowChart, TfrmTopologyNode and
unit-catalogue routines, extracts their literal lists, branch constants and
resource strings, and requires them to equal the constants that
``cbus_toolkit.project_topology`` reproduces. It reports hashes, addresses and
short identifiers, not proprietary instruction bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

import capstone
import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cbus_toolkit import project_topology as model  # noqa: E402

EXE_SHA256 = "9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab"
MAP_SHA256 = "f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb"
METHODS = (
    "CIS_TTopologyGenerator.GenerateTopologyScript",
    "CIS_TTopologyGenerator.TTopologyGenerator.Create",
    "CIS_TTopologyGenerator.TTopologyGenerator.Generate",
    "CIS_TTopologyGenerator.TTopologyGenerator.FindLocalNetworks",
    "CIS_TTopologyGenerator.TTopologyGenerator.GenerateNetworkTree",
    "CIS_TTopologyGenerator.TTopologyGenerator.ExploreNetwork",
    "CIS_TTopologyGenerator.TTopologyGenerator.IsProcessedNetwork",
    "CIS_TTopologyGenerator.TTopologyGenerator.GetAvailableY",
    "CIS_TTopologyGenerator.TTopologyGenerator.AddNetwork",
    "CIS_TTopologyGenerator.TTopologyGenerator.AddPCIElement",
    "CIS_TTopologyGenerator.TTopologyGenerator.AddCNIElement",
    "CIS_TTopologyGenerator.TTopologyGenerator.AddCNI2Element",
    "CIS_TTopologyGenerator.TTopologyGenerator.AddCBTIElement",
    "CIS_TTopologyGenerator.TTopologyGenerator.AddBridgeElement",
    "CIS_TTopologyGenerator.TTopologyGenerator.IsWirelessGateway",
    "CIS_TTopologyGenerator.TTopologyGenerator.CheckOrphanedNetworks",
    "CIS_TTopologyGenerator.TTopologyGenerator.IsNetworkInTopologyMap",
    "CIS_TTopologyExpressFlowChart.GetNetworkConnectionColor",
    "CIS_TTopologyExpressFlowChart.TerminateNetworkConnection",
    "CIS_TTopologyExpressFlowChart.TTopologyExpressFlowChart.DrawElement",
    "CIS_TTopologyExpressFlowChart.TTopologyExpressFlowChart.DrawNetworkAddress",
    "CIS_TTopologyExpressFlowChart.TTopologyExpressFlowChart.GetElement",
    "CIS_TfrmTopologyNode.TfrmTopologyNode.OpenNearSideGUI",
    "CIS_TfrmTopologyNode.TfrmTopologyNode.OpenFarSideGUI",
    "CIS_TfrmTopologyNode.TfrmTopologyNode.OpenUnitsNode",
    "CIS_TfrmTopologyNode.TfrmTopologyNode.GetContextHelpID",
    "CIS_TfrmTopologyNode.TfrmTopologyNode.Print",
    "CIS_TfrmTopologyNode.TfrmTopologyNode.CopyToClipboard",
    "CIS_TCommonCBus.TNetworkInterface.GetInterfaceType",
    "CIS_TCommonCBus.TCBusNetwork.GetIsWireless",
    "CIS_TCommonCBus.TCBUSUnit.GetUnitType",
    "CIS_TCommonCBus.TCBUSUnit.IsNearBridge",
    "CIS_TCommonCBus.TCBUSUnit.IsBridgeFarSide",
    "CIS_TUnitType.TCGateUnitCatalog.IsBridge",
    "CIS_TUnitType.TCGateUnitCatalog.IsNearBridge",
    "CIS_TUnitType.TCGateUnitCatalog.IsBridgeFarSide",
    "CIS_TUnitType.TCGateUnitCatalog.IsWireless",
)
# Branch constants that select locality and the drawn interface element.
MARKERS = {
    "CIS_TTopologyGenerator.TTopologyGenerator.FindLocalNetworks": (
        ("sub", "al, 5"), ("add", "al, 0xfe"), ("sub", "al, 4")),
    "CIS_TTopologyGenerator.TTopologyGenerator.GenerateNetworkTree": (
        ("dec", "eax"), ("sub", "al, 3"), ("sub", "al, 4"), ("sub", "al, 6"), ("cmp", "al, 7")),
    "CIS_TTopologyGenerator.TTopologyGenerator.GetAvailableY": (
        ("sub", "eax, 0x960"), ("imul", "eax, eax, 0x961"), ("cmp", "dword ptr [ebp - 0x1c], 0x960")),
    "CIS_TTopologyExpressFlowChart.GetNetworkConnectionColor": (
        ("mov", "dword ptr [ebp - 4], 0xff0000"), ("mov", "dword ptr [ebp - 4], 0x8844ff")),
    "CIS_TfrmTopologyNode.TfrmTopologyNode.GetContextHelpID": (
        ("mov", "dword ptr [ebp - 8], 0x17b"),),
}
RESOURCE_STRINGS = {
    "CIS_TTopologyGenerator.TTopologyGenerator.CheckOrphanedNetworks": model.ORPHAN_TEXT.replace("{}", "%s"),
    "CIS_TTopologyGenerator.TTopologyGenerator.GetAvailableY": model.TOO_MANY_NETWORKS,
    "CIS_TfrmTopologyNode.TfrmTopologyNode.Print": model.PRINT_TITLE.replace("{}", "%s"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Image:
    def __init__(self, exe: bytes, map_raw: bytes) -> None:
        self.raw = exe
        self.pe = pefile.PE(data=exe)
        if self.pe.FILE_HEADER.Machine != 0x14C:
            raise ValueError("Expected pinned x86 Toolkit image")
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        segments = {
            segment: self.base + next(s.VirtualAddress for s in self.pe.sections if s.Name.startswith(name))
            for segment, name in ((1, b".text"), (2, b".itext"))
        }
        self.symbols: dict[int, set[str]] = {}
        self.by_name: dict[str, int] = {}
        for line in map_raw.decode("ascii").splitlines():
            match = re.fullmatch(r"\s*000([12]):([0-9A-Fa-f]{8})\s+(\S+)\s*", line)
            if match:
                address = int(match[2], 16) + segments[int(match[1])]
                self.symbols.setdefault(address, set()).add(match[3])
                self.by_name.setdefault(match[3], address)
        self.starts = sorted(self.symbols)
        self.strings = self._resource_strings()
        self.decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)

    def _resource_strings(self) -> dict[int, str]:
        result: dict[int, str] = {}
        for kind in self.pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if kind.id != 6:
                continue
            for block in kind.directory.entries:
                for language in block.directory.entries:
                    data = self.pe.get_data(language.data.struct.OffsetToData, language.data.struct.Size)
                    offset = 0
                    for index in range(16):
                        length = struct.unpack_from("<H", data, offset)[0]
                        offset += 2
                        result[(block.id - 1) * 16 + index] = data[offset:offset + 2 * length].decode("utf-16le")
                        offset += 2 * length
        return result

    def literal(self, va: int) -> str | None:
        try:
            offset = self.pe.get_offset_from_rva(va - self.base)
        except pefile.PEFormatError:
            return None
        if offset < 12 or offset + 4 > len(self.raw):
            return None
        length, refcount = struct.unpack_from("<i", self.raw, offset - 4)[0], struct.unpack_from("<i", self.raw, offset - 8)[0]
        if refcount != -1 or not 0 < length < 256 or struct.unpack_from("<H", self.raw, offset - 12)[0] != 1200:
            return None
        return self.raw[offset:offset + 2 * length].decode("utf-16le")

    def resource(self, va: int) -> str | None:
        try:
            data = self.pe.get_data(va - self.base + 4, 4)
        except pefile.PEFormatError:
            return None
        if len(data) != 4:
            return None
        identifier = struct.unpack_from("<I", data)[0]
        return self.strings.get(identifier)

    def method(self, name: str) -> dict:
        start = self.by_name.get(name)
        if start is None:
            raise ValueError("Missing exact original MAP symbol: " + name)
        end = next((address for address in self.starts if address > start), None)
        if end is None or not 0 < end - start <= 32768:
            raise ValueError("Unbounded original method: " + name)
        raw = self.pe.get_data(start - self.base, end - start)
        instructions = [(i.address, i.mnemonic, i.op_str) for i in self.decoder.disasm(raw, start)]
        literals, resources, by_address = [], [], {}
        for address, mnemonic, operands in instructions:
            for token in re.findall(r"0x[0-9a-f]{6,8}", operands):
                value = int(token, 16)
                text = self.literal(value)
                if text is not None:
                    literals.append(text)
                    by_address[address] = text
                elif mnemonic == "mov" and operands.startswith("eax, "):
                    resource = self.resource(value)
                    if resource is not None:
                        resources.append(resource)
        return {"start": start, "end": end, "sha256": _sha(raw),
                "instructions": instructions, "literals": literals, "resources": resources,
                "literal_at": by_address}


def _interface_table(method: dict) -> list[tuple[str, int]]:
    """Pair each compared InterfaceType literal with the enum byte(s) it assigns."""
    pairs: list[tuple[str, int]] = []
    current = "<none>"
    for address, mnemonic, operands in method["instructions"]:
        if mnemonic == "mov" and operands.startswith("edx, ") and address in method["literal_at"]:
            current = method["literal_at"][address]
        elif mnemonic == "mov" and operands.startswith("byte ptr [ebp - 5], "):
            pairs.append((current, int(operands.rsplit(", ", 1)[1], 0)))
    # The final assignment follows the last failed comparison: it is the fallback.
    if pairs:
        pairs[-1] = ("<fallback>", pairs[-1][1])
    return pairs


def inspect(exe_path: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe_path.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Image(exe_raw, map_raw)
    methods = {name: image.method(name) for name in METHODS}

    def lowered(name: str) -> set[str]:
        return {value.lower() for value in methods[name]["literals"]}

    checks = {
        "bridge_types": lowered("CIS_TUnitType.TCGateUnitCatalog.IsBridge") == model.BRIDGE_TYPES,
        "near_bridge_types": lowered("CIS_TUnitType.TCGateUnitCatalog.IsNearBridge") == model.NEAR_BRIDGE_TYPES,
        "far_bridge_types": lowered("CIS_TUnitType.TCGateUnitCatalog.IsBridgeFarSide") == model.FAR_BRIDGE_TYPES,
        "wireless_gateway_types": lowered("CIS_TTopologyGenerator.TTopologyGenerator.IsWirelessGateway")
        == model.WIRELESS_GATEWAY_TYPES,
        "wireless_unit_rule": set(methods["CIS_TUnitType.TCGateUnitCatalog.IsWireless"]["literals"])
        == {"w", *model.WIRELESS_UNIT_NAMES},
    }
    interface = _interface_table(methods["CIS_TCommonCBus.TNetworkInterface.GetInterfaceType"])
    expected_interface = [("Serial", 0), ("CNI", 1), ("CNI", 4), ("C-Bus Home Controller", 4),
                          ("SpaceLogicCBusHomeController", 10), ("Lorax", 8), ("LoraxUSB", 9),
                          ("Etherlite", 2), ("Socket", 1), ("Wiser", 4), ("Bridge", 6), ("Bridge", 5),
                          ("modem", 7), ("<fallback>", 0)]
    checks["interface_enum_table"] = interface == expected_interface
    for name, enum in (("Serial", 0), ("Lorax", 8), ("LoraxUSB", 9), ("Etherlite", 2), ("Socket", 1),
                       ("Wiser", 4), ("C-Bus Home Controller", 4), ("SpaceLogicCBusHomeController", 10),
                       ("modem", 7)):
        checks[f"interface_model:{name}"] = model.classify_interface(name, "")["enum"] == enum
    checks["interface_model:CNI"] = (model.classify_interface("CNI", "10.0.0.1:1")["enum"] == 1
                                     and model.classify_interface("CNI", "host:1")["enum"] == 4)
    for name, expected in MARKERS.items():
        seen = [(mnemonic, operands) for _, mnemonic, operands in methods[name]["instructions"]]
        checks[f"markers:{name}"] = all(marker in seen for marker in expected)
    for name, text in RESOURCE_STRINGS.items():
        checks[f"resource:{name}"] = text in methods[name]["resources"]
    element_tags = {
        "AddPCIElement": "PCI", "AddCNIElement": "CNI", "AddCNI2Element": "CNI2",
        "AddCBTIElement": "CBTI", "AddBridgeElement": "Bridge", "AddNetwork": "Network",
    }
    for method_name, tag in element_tags.items():
        literals = methods[f"CIS_TTopologyGenerator.TTopologyGenerator.{method_name}"]["literals"]
        checks[f"element:{tag}"] = "<Type>" in literals and tag in literals
    network_literals = methods["CIS_TTopologyGenerator.TTopologyGenerator.AddNetwork"]["literals"]
    checks["network_tags"] = all(tag in network_literals for tag in (
        "<StartX>", "<StartY>", "<FinishX>", "<FinishY>", "<CircularJoin>", "<Wireless>"))
    checks["orphan_warning_tag"] = "Warning" in methods[
        "CIS_TTopologyGenerator.TTopologyGenerator.CheckOrphanedNetworks"]["literals"]
    checks["drawn_element_kinds"] = {"PCI", "CBTI", "CNI", "CNI2", "Bridge", "Network"} <= set(methods[
        "CIS_TTopologyExpressFlowChart.TTopologyExpressFlowChart.DrawElement"]["literals"])
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError("Original topology source differs from the reproduced model: " + ", ".join(failed))
    if _sha(exe_path.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original files changed during inspection")
    return {
        "format": "cbus-toolkit-topology-generator-static-v1",
        "original_exe_sha256": EXE_SHA256,
        "original_map_sha256": MAP_SHA256,
        "original_executed": False,
        "model_module_sha256": _sha(Path(model.__file__).read_bytes()),
        "method_spans": {name: {"start": hex(value["start"]), "end": hex(value["end"]),
                                "bytes": value["end"] - value["start"], "sha256": value["sha256"]}
                         for name, value in methods.items()},
        "interface_enum_table": [list(pair) for pair in interface],
        "checks": {name: True for name in sorted(checks)},
        "limit": ("This verifies pinned original source routines and the constants the CLI reproduces. "
                  "It does not execute the Toolkit, load a project, render the ExpressFlowChart, "
                  "establish network-manager order, print, copy an image, or open a unit form."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
