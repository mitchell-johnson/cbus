"""Verify the recovered thermostat Load Template post-load tables.

Supply the original Toolkit EXE and MAP.  Nothing is executed.  The pinned
routines are traversed recursively (following jump tables and SEH handler
entries), each per-plant-type case is reduced to its ordered setter
assignments, and the result must equal the tables in
``cbus_toolkit.thermostat_post_load``.  The report contains hashes,
addresses, symbol names and the derived tables, not instruction bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cbus_toolkit import thermostat_post_load as model  # noqa: E402

PLANT = "CIS_TThermostat.TPlantControlService."
AGENT = "CIS_TCBusThermostatCGateAgent.TCBusThermostatCGateAgent."
# Model field offsets of TPlantControlService (InternalCreate attribute names).
FIELDS = {0xf4: "CoolActivation", 0xf8: "CoolStage1", 0xfc: "CoolStage2", 0x100: "CoolStage3",
          0x104: "CoolFanLow", 0x108: "CoolFanMedium", 0x10c: "CoolFanHigh", 0x110: "HeatActivation",
          0x114: "HeatStage1", 0x118: "HeatStage2", 0x11c: "HeatStage3", 0x120: "HeatFanLow",
          0x124: "HeatFanMedium", 0x128: "HeatFanHigh"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Walker:
    def __init__(self, image: _Image):
        self.image = image
        self.handle_on_exception = image.by_name["System.@HandleOnException"]

    def dword(self, va: int) -> int:
        return struct.unpack("<I", self.image.pe.get_data(va - self.image.base, 4))[0]

    def name(self, va: int) -> str | None:
        names = self.image.symbols.get(va)
        return sorted(names)[0] if names else None

    def listing(self, symbol: str):
        """Recursive traversal; returns ordered (address, mnemonic, operands, note) and jump tables."""
        image, start = self.image, self.image.by_name[symbol]
        end = next(a for a in image.starts if a > start)
        raw = image.pe.get_data(start - image.base, end - start)
        seen, work, tables = {}, [start], []
        while work:
            address = work.pop()
            while start <= address < end and address not in seen:
                ins = next(image.decoder.disasm(raw[address - start:address - start + 16], address), None)
                if ins is None:
                    break
                seen[address] = ins
                target = re.fullmatch(r"0x([0-9a-f]+)", ins.op_str)
                if target and ins.mnemonic in ("push", "jmp") or target and ins.mnemonic.startswith("j"):
                    value = int(target[1], 16)
                    if start <= value < end:
                        work.append(value)
                    if value == self.handle_on_exception:
                        after = address + ins.size
                        for index in range(min(self.dword(after), 20)):
                            handler = self.dword(after + 8 + 8 * index)
                            if start <= handler < end:
                                work.append(handler)
                table = re.fullmatch(r"dword ptr \[\w+\*4 \+ 0x([0-9a-f]+)\]", ins.op_str)
                if ins.mnemonic == "jmp" and table:
                    bound = next(int(m[1], 0) + 1 for a in sorted((x for x in seen if address - 16 <= x < address),
                                                               reverse=True)
                                 for m in [re.fullmatch(r"\w+, (0x[0-9a-f]+|\d+)", seen[a].op_str)]
                                 if seen[a].mnemonic == "cmp" and m)
                    entries = [self.dword(int(table[1], 16) + 4 * i) for i in range(bound)]
                    tables.append(entries)
                    work.extend(entries)
                    break
                if ins.mnemonic in ("ret", "jmp"):
                    break
                address += ins.size
        rows = []
        for address in sorted(seen):
            ins, notes = seen[address], []
            for token in re.findall(r"0x[0-9a-f]{5,8}", ins.op_str):
                value = int(token, 16)
                if self.name(value):
                    notes.append(self.name(value))
                elif ins.mnemonic == "mov" and image.resource(value) is not None:
                    notes.append("RES:" + image.resource(value))
            rows.append((address, ins.mnemonic, ins.op_str, " ".join(notes)))
        return rows, tables, _sha(raw)


def _paths(rows, start, end_target, record):
    """Enumerate straight-line paths from one case, forking on installation-name compares."""
    index = {a: i for i, (a, *_rest) in enumerate(rows)}
    results = []

    def go(i, condition, state, actions):
        while i < len(rows):
            address, mnemonic, operands, note = rows[i]
            if mnemonic == "jmp" and re.fullmatch(r"0x[0-9a-f]+", operands):
                target = int(operands, 16)
                if target == end_target or target not in index:
                    break
                i = index[target]
                continue
            if mnemonic in ("jne", "je") and "compare" in state:
                label = state.pop("compare")
                equal_at_target = mnemonic == "je"
                go(index[int(operands, 16)], condition + [(equal_at_target, label)], dict(state), list(actions))
                condition = condition + [(not equal_at_target, label)]
                i += 1
                continue
            if mnemonic == "je" and state.pop("no_installation", False):
                i += 1
                continue
            if "GetCurrentInstallation" in note and rows[i + 1][1] == "test":
                state["no_installation"] = True
            if note.startswith("RES:"):
                state["resource"] = note[4:]
            if "UStrEqual" in note:
                state["compare"] = state.pop("resource")
            if "UpdateFanSpeedsForPlantType" in note:
                break
            record(state, actions, mnemonic, operands, note, rows, i)
            i += 1
        results.append((condition, actions))

    go(index[start], [], {}, [])
    return results


def _installation(condition):
    equal = [label for is_equal, label in condition if is_equal]
    return equal[0] if equal else None


def _assignments(state, actions, mnemonic, operands, note, rows, i):
    if mnemonic == "mov" and operands == "edx, dword ptr [ebp - 8]":
        state["value"] = model.UNUSED
    constant = re.fullmatch(r"(?:edx|dl), (0x[0-9a-f]+|\d+)", operands)
    if mnemonic == "mov" and constant:
        state["value"] = int(constant[1], 0)
    if mnemonic == "xor" and operands == "edx, edx":
        state["value"] = 0
    field = re.fullmatch(r"eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]", operands)
    if mnemonic == "mov" and field and rows[i + 1][1] == "push":
        state["excluded"] = FIELDS[int(field[1], 16)]
    if mnemonic == "call":
        method = note.rsplit(".", 1)[-1]
        if method == "GetGroup":
            state["pending"] = ("group", state["value"], state.pop("resource"), state.pop("excluded"))
        elif method.startswith("Get") and ("Output" in method or "InternalRelay" in method):
            state["pending"] = ("ref", method[3:].replace("OutputGroup", "").replace("Group", ""))
        elif method.startswith("Set"):
            actions.append((method[3:], state["value"]))
    if mnemonic == "mov" and operands == "edx, eax" and "pending" in state:
        state["value"] = state.pop("pending")


def _default_names(state, actions, mnemonic, operands, note, rows, i):
    if mnemonic == "call" and "CreateAndRenameGroup" in note:
        actions.append(state.pop("resource"))


def _case_table(walker, symbol, record):
    rows, tables, digest = walker.listing(symbol)
    end_target = Counter(int(op, 16) for _a, m, op, _n in rows
                         if m == "jmp" and re.fullmatch(r"0x[0-9a-f]+", op)).most_common(1)[0][0]
    return {case: {_installation(c): a for c, a in _paths(rows, entry, end_target, record)}
            for case, entry in enumerate(tables[0])}, digest, rows


def _normal_update(table):
    result = {}
    for plant, branches in table.items():
        result[plant] = {}
        for installation, actions in branches.items():
            rows = []
            for setter, value in actions:
                attribute = setter.replace("OutputGroup", "").replace("Group", "")
                rows.append((attribute, value))
            result[plant][installation] = tuple(rows)
    return result


def inspect(exe: Path, map_path: Path) -> dict:
    exe_raw, map_raw = exe.read_bytes(), map_path.read_bytes()
    if _sha(exe_raw) != EXE_SHA256 or _sha(map_raw) != MAP_SHA256:
        raise ValueError("Original Toolkit EXE/MAP hash mismatch")
    image = _Image(exe_raw, map_raw)
    walker = _Walker(image)
    digests, checks = {}, {}
    update, digests["UpdateParametersForPlantType"], _ = _case_table(
        walker, PLANT + "UpdateParametersForPlantType", _assignments)
    checks["update_parameters_table"] = _normal_update(update) == model.UPDATE_TABLE
    fans, digests["UpdateFanSpeedsForPlantType"], _ = _case_table(
        walker, PLANT + "UpdateFanSpeedsForPlantType", _assignments)
    checks["fan_speed_table"] = {p: {k: tuple(v) for k, v in b.items()} for p, b in fans.items()} == model.FAN_TABLE
    defaults = {}
    for attribute in model.OUTPUTS:
        symbol = PLANT + "GetDefault" + attribute + "OutputGroupForPlantType"
        table, digests[symbol.rsplit(".", 1)[-1]], _ = _case_table(walker, symbol, _default_names)
        row = {}
        for plant, branches in table.items():
            names = {k: (v[0] if v else None) for k, v in branches.items()}
            value = names[None] if list(names) == [None] else names
            if value is not None:
                row[plant] = value
        defaults[attribute] = row
    checks["afterload_default_names"] = defaults == model.DEFAULT_NAMES
    # Installation names, in LoadThermostatInstallations order.
    rows, _tables, digests["LoadThermostatInstallations"] = walker.listing(AGENT + "LoadThermostatInstallations")
    names, current = {}, None
    for i, (_a, mnemonic, operands, note) in enumerate(rows):
        index = re.fullmatch(r"dword ptr \[eax \+ 0x88\], (\d)", operands)
        if mnemonic == "mov" and index:
            current = int(index[1])
        if "SetInstallationName" in note and current:
            for _b, m2, op2, _n2 in reversed(rows[max(0, i - 8):i]):
                pointer = re.fullmatch(r"eax, dword ptr \[(0x[0-9a-f]+)\]", op2)
                if m2 == "mov" and pointer:
                    names[current] = image.resource(walker.dword(int(pointer[1], 16)))
                    break
    checks["installation_names"] = names == model.INSTALLATION_NAMES
    # Plant type virtualisation: unit 8 -> 11 unless ten output attributes are 255.
    rows, _t, digests["IntUnitPlantTypeToVirtualPlantType"] = walker.listing(
        AGENT + "IntUnitPlantTypeToVirtualPlantType")
    offsets = [int(m[1], 16) for _a, mn, op, _n in rows
               for m in [re.fullmatch(r"eax, dword ptr \[eax \+ (0x[0-9a-f]+)\]", op)] if mn == "mov" and m]
    agent_outputs = dict(zip(range(0x204, 0x23c, 4), ("CoolActivation", "CoolStage1", "CoolStage2", "CoolStage3",
                                                       "CoolFanLow", "CoolFanMedium", "CoolFanHigh",
                                                       "HeatActivation", "HeatStage1", "HeatStage2", "HeatStage3",
                                                       "HeatFanLow", "HeatFanMedium", "HeatFanHigh")))
    checks["virtual_plant_rule"] = (tuple(agent_outputs[o] for o in offsets) == model.VIRTUAL_11_OUTPUTS
                                    and any(op == "byte ptr [ebp - 8], 8" for _a, _m, op, _n in rows)
                                    and any(op == "dword ptr [ebp - 0xc], 0xb" for _a, _m, op, _n in rows))
    # Autogenerated prefix and the <Unused> group tag.
    rows, _t, digests["AutogeneratedPrefix"] = walker.listing(PLANT + "AutogeneratedPrefix")
    literals = [image.literal(int(t, 16)) for _a, _m, op, _n in rows for t in re.findall(r"0x[0-9a-f]{6,8}", op)]
    checks["group_prefix"] = "CG" in literals and "[%s%2.2d]" in literals
    checks["unused_tag"] = image.resource(walker.dword(0x13c1ca8)) == model.UNUSED_TAG
    # Damper modulation factor in BeforeSave (jump table after GetInternalPlantType).
    rows, tables, digests["BeforeSaveProgrammingInformation"] = walker.listing(
        AGENT + "BeforeSaveProgrammingInformation")
    index = {a: i for i, (a, *_r) in enumerate(rows)}
    factors = {}
    for plant, entry in enumerate(tables[0]):
        window = []
        for _a, mnemonic, operands, _n in rows[index[entry]:]:
            if mnemonic == "call" and operands == "dword ptr [ecx + 0x7c]":
                break
            window.append((mnemonic, operands))
        if ("xor", "edx, edx") in window:
            factors[plant] = 0
        else:
            factors[plant] = 1 + sum(1 for m, op in window if m == "add" and op in (
                "edx, edx", "edx, dword ptr [ebp - 8]"))
    checks["damper_modulation_factor"] = {p: f for p, f in factors.items() if f != 1} == model.DAMPER_MODULATION_FACTOR
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise ValueError("Original thermostat post-load source differs from the model: " + ", ".join(failed))
    if _sha(exe.read_bytes()) != EXE_SHA256 or _sha(map_path.read_bytes()) != MAP_SHA256:
        raise ValueError("Original files changed during inspection")
    return {
        "format": "cbus-toolkit-thermostat-post-load-static-v1",
        "original_exe_sha256": EXE_SHA256, "original_map_sha256": MAP_SHA256,
        "original_executed": False,
        "model_module_sha256": _sha(Path(model.__file__).read_bytes()),
        "routine_sha256": digests,
        "installation_names": {str(k): v for k, v in sorted(names.items())},
        "checks": {name: True for name in sorted(checks)},
        "limit": ("Static table evidence only. Template event flags, the relay-load skip, ordinary-load "
                  "default group tags and the allocator are covered by thermostat_group_allocation_static.py. "
                  "Manager-order-dependent allocation and existing-prefix rename/reuse remain unreplayed; "
                  "this receipt does not cover generic untouched-field normalization or executed Toolkit GUI."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
