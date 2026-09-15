"""Capture the original preset-level controls; research, not acceptance.

Requires an already running, explicitly owned Windows original-assembly bridge.
No production restore-level implementation is used to predict the results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def cases():
    rows = []

    def add(name, overrides=None, actions=(), cache="complete"):
        rows.append(dict(name=name, overrides=overrides or {}, actions=list(actions), cache=cache))

    def widget(number, kind, group=42, level=73, secondary=False):
        row = {f"Widget{number}WidgetType": [kind],
               f"Widget{number}WidgetByteValue1": [128 if secondary else 0],
               f"Widget{number}WidgetByteValue6": [group]}
        if number >= 6:
            row[f"Widget{number}RestoreLevel"] = [level]
        return row

    # Every original widget kind plus unknown/fallback/end-marker cases.
    for kind in (*range(18), 127, 254, 255):
        add(f"kind-{kind}", widget(6, kind), ("groups",))
    base = {"NavWidgetType": [1], "EnableLevelStore": [0], "PrimaryApplication": [56], "SecondaryApplication": [57],
            **widget(6, 2), **widget(7, 3), **widget(8, 4, 12, 83),
            **widget(9, 5, 42, 93, True), **widget(10, 14, 42, 103),
            **widget(11, 15, 42, 113), **widget(12, 16, 42, 123),
            **widget(13, 2, 1, 133), **widget(14, 2, 42, 143),
            **widget(15, 0, 42, 153), **widget(16, 6, 42, 163),
            **widget(17, 10, 42, 173), **widget(18, 2, 255, 183),
            **widget(19, 17, 42, 193), **widget(20, 0, 42, 203),
            **widget(21, 0, 42, 213)}
    for page in (0, 1, 2, 7, 255):
        add(f"visibility-mode-{page}", {**base, "NavWidgetType": [page]}, ("groups",))
    for sync in (False, True):
        for level in (-1, 0, 1, 73, 74, 128, 254, 255, 256):
            add(f"edit-{str(sync).lower()}-{level}", base,
                (f"edit 6 {level} {str(sync).lower()}", "validate", "write"))
        for page in (0, 1):
            add(f"hidden-mode-{page}-sync-{sync}", {**base, "NavWidgetType": [page]},
                (f"edit 6 42 {str(sync).lower()}", "refresh", "groups"))
        add(f"empty-and-end-sync-{sync}", {**base, "Widget10WidgetType": [255]},
            (f"edit 6 42 {str(sync).lower()}",))
    for mode in ("duplicate-groups", "duplicate-app-groups"):
        add(mode, base, ("edit 6 42 false", "groups"), cache=mode)
    add("same-value-no-propagation", base, ("edit 6 73 true",))
    add("sequential-sync-then-independent", base,
        ("edit 6 42 true", "edit 8 77 false", "edit 6 88 false"))
    add("previous-mode-hidden", {**base, "EnableLevelStore": [1]}, ("groups",))
    add("previous-mode-rejected-edit", {**base, "EnableLevelStore": [1]}, ("edit 6 42 true",))
    add("previous-mode-forced-diagnostic", {**base, "EnableLevelStore": [1]}, ("force-edit 6 42 true",))
    add("hidden-widget-rejected-edit", {**base, "NavWidgetType": [0]}, ("edit 13 42 false",))
    add("hidden-widget-forced-diagnostic", {**base, "NavWidgetType": [0]}, ("force-edit 13 42 false",))
    add("restore-mode-switch", {**base, "EnableLevelStore": [1]},
        ("restore-mode preset", "edit 6 42 false", "restore-mode previous", "edit 6 77 true"))
    add("standby-reference", {**base, **widget(2, 2, 42)}, ("groups", "edit 6 88 false"))
    add("missing-group", {**base, **widget(6, 2, 99)}, ("groups",))
    add("missing-primary", base, ("groups",), "missing-app56")
    add("missing-secondary", base, ("groups",), "missing-app57")
    add("secondary-disabled", {**base, "SecondaryApplication": [255]}, ("groups", "edit 6 88 false"))
    add("page-switch", {**base, "NavWidgetType": [0]}, ("mode 1", "edit 13 99 false", "mode 0"))
    for kind in (2, 3, 4, 5, 16):
        add(f"missing-kind-{kind}", {**base, **widget(6, kind, 99)}, ("groups",))
    add("missing-standby", {**base, **widget(2, 2, 99)}, ("groups", "edit 6 42 false"))
    add("missing-tail", {**base, "Widget10WidgetType": [255], **widget(14, 2, 99)}, ("groups", "edit 6 42 false"))
    add("binding-mismatched-same-group", {**base, "Widget7RestoreLevel": [17]}, ("groups", "edit 6 73 false"))
    add("option-enable-preset-edit", {**base, "EnableLevelStore": [1]}, ("restore-mode preset", "edit 6 42 true"))
    add("option-disable-preset", base, ("restore-mode previous",))
    add("option-enable-multiple-edit", {**base, "NavWidgetType": [0]}, ("mode 1", "edit 13 42 false"))
    add("option-enable-single-edit", base, ("mode 0", "edit 6 42 true"))
    for flag in (0xfb, 0xfe):
        for sync in (False, True):
            record = bytes((flag, 1, 42, 2, 26, 0xf1, 12, 123))
            add(f"composition-scene-{flag}-{sync}", {**base, "Scene1StartAddress": [0],
                "Scene3StartAddress": [0], "SceneBucket": list(record.ljust(232, b'\xff')),
                **widget(2, 7), "Widget2WidgetByteValue1": [0xed],
                **widget(17, 8), "Widget17WidgetByteValue1": [0x12],
                "StaticTextString0": list(b'\xff\xfe\0'.ljust(64, b'\0'))},
                (f"edit 6 254 {str(sync).lower()}",))
    for sync in (False, True):
        add(f"composition-image-{sync}", {**base, "Widget6WidgetByteValue1": [16]},
            (f"edit 6 1 {str(sync).lower()}",), cache="image-present")
    return rows


def tsv(values):
    return "".join(name + "\t" + (value if isinstance(value, str) else " ".join(hex(n) for n in value))
                   + "\n" for name, value in values.items()).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New owned evidence directory")
    parser.add_argument("--case", action="append", help="Exact case names; omit for all")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    selected = [row for row in cases() if not args.case or row["name"] in args.case]
    if not selected or args.case and set(args.case) != {row["name"] for row in selected}:
        parser.error("Unknown or missing case selection")
    args.output.mkdir(parents=True, exist_ok=False)
    document = {"format": "cbus-edlt-restore-level-research-v1", "acceptance": False,
                "physical_device_verified": False, "full_form_initialization_verified": False,
                "cases": selected, "executions": []}
    path = args.output / "research.json"
    path.write_text(json.dumps(document, indent=2) + "\n")
    if args.prepare_only:
        print(json.dumps({"prepared_cases": len(selected), "output": str(path)}))
        return 0

    from cbus_toolkit.edlt import EdltLighting
    from cbus_toolkit.unitspec import UnitSpecStore
    from research.windows_bridge import WindowsModelProbe
    spec_dir = ROOT / "research/vendor/unitspec-plain"
    spec_path = spec_dir / "KEYGL5.xml"
    baseline = EdltLighting(UnitSpecStore(spec_dir).load("KEYGL5.xml")).snapshot(
        UnitSpecStore(spec_dir).load("KEYGL5.xml").defaults())
    source = ROOT / "research/NativeEdltRestoreLevelsProbe.cs"
    inputs = {"probe.cs": source.read_bytes(), "KEYGL5.xml": spec_path.read_bytes(),
              "values.tsv": tsv(baseline), "driver.py": Path(__file__).read_bytes(),
              "windows_bridge.py": (ROOT / 'research/windows_bridge.py').read_bytes()}
    for name, data in inputs.items():
        (args.output / name).write_bytes(data)
    document["input_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()}
    path.write_text(json.dumps(document, indent=2) + "\n")
    probe = WindowsModelProbe(source, ROOT / "research/vendor/toolkit/app", references=("eDLT.dll",))
    document["vendor_manifest"] = probe.vendor_manifest
    document["probe_prefix"] = probe.prefix
    executable = probe.bridge.pull('vendor\\' + probe.prefix + '.exe')
    (args.output / 'probe.exe').write_bytes(executable)
    document['compiled_executable_sha256'] = hashlib.sha256(executable).hexdigest()
    for row in selected:
        if source.read_bytes() != inputs['probe.cs'] or (ROOT / 'research/windows_bridge.py').read_bytes() != inputs['windows_bridge.py']:
            raise RuntimeError('Original probe or Windows harness changed during research run')
        files = {"KEYGL5.xml": inputs["KEYGL5.xml"], "values.tsv": inputs["values.tsv"],
                 "overrides.tsv": tsv(row["overrides"]),
                 "actions.txt": ("\n".join(row["actions"]) + "\n").encode()}
        result = probe.run_result(("KEYGL5.xml", "values.tsv", "overrides.tsv", "actions.txt", "owned", row["cache"]), files=files)
        stem = row["name"]
        (args.output / (stem + ".stdout.txt")).write_bytes(result["stdout"])
        (args.output / (stem + ".stderr.txt")).write_bytes(result["stderr"])
        execution = {key: value for key, value in result.items() if key not in ("stdout", "stderr")}
        execution.update(case=stem, input_sha256={name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                         stdout_sha256=hashlib.sha256(result["stdout"]).hexdigest(),
                         stderr_sha256=hashlib.sha256(result["stderr"]).hexdigest())
        document["executions"].append(execution)
        path.write_text(json.dumps(document, indent=2) + "\n")
        print(json.dumps({"case": stem, "exit_code": result["exit_code"], "job_id": result["job_id"]}), flush=True)
    print(json.dumps({"executed_cases": len(selected), "acceptance": False, "output": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
