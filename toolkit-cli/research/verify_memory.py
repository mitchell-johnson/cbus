#!/usr/bin/env python3
"""Compare changing schema-encoded values with real offline C-Gate PP bytes.

One representative is exercised for every distinct logical layout in the local
resolved specification corpus, with explicit unexercised/failed rows. Every
native fixture is a database unit in a new disposable closed-network project.
No physical network is opened. This is layout acceptance, not device parity.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.memory import MemoryCodec, MemoryImage
from cbus_toolkit.programming import Programmer
from cbus_toolkit.unitspec import UnitCatalog, UnitSpecStore


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(layout):
    return (layout.parameter.type, layout.bit_size, layout.bit_address,
            layout.array_skip, layout.array_size, layout.endian)


def inventory(store, catalog):
    layouts = defaultdict(list)
    specs = {}
    for row in store.list_specs():
        spec = store.load(row["filename"])
        specs[spec.filename] = spec
        codec = MemoryCodec(spec)
        for name in spec.parameters:
            layouts[signature(codec.layout(name))].append((spec.filename, name))
    fixture_by_spec = {}
    # Prefer concrete, default, non-internal catalogue records. Internal records
    # remain fallback fixtures when they are the only evidence for a layout.
    records = sorted(catalog.records, key=lambda r: (not r["default"], r["revision"].get("IsInternal") == "true",
                                                     "*" in r["unit_type"] or "*" in r["catalog_number"],
                                                     r["catalog_number"], r["minimum_version"]))
    for row in records:
        if row["spec_filename"] in specs and "*" not in row["unit_type"]:
            fixture_by_spec.setdefault(row["spec_filename"], row)
    chosen = {}
    todo = set(layouts)
    # Greedy coverage reduces database-unit setup without dropping rare layouts.
    while todo:
        candidates = defaultdict(set)
        for key in todo:
            for filename, name in layouts[key]:
                if filename in fixture_by_spec and not any(c.isspace() for c in name):
                    candidates[filename].add(key)
        if not candidates:
            break
        filename = min(candidates, key=lambda f: (-len(candidates[f]), f))
        for key in sorted(candidates[filename]):
            name = next(n for f, n in layouts[key] if f == filename and not any(c.isspace() for c in n))
            chosen[key] = (filename, name, fixture_by_spec[filename])
            todo.remove(key)
    return layouts, specs, chosen


def raw(session, start, count):
    reply = session.get_raw_data(start, count)
    lines = [line for line in reply.lines if "RawData=" in line]
    if len(lines) != 1:
        raise ValueError("Expected exactly one native raw-data record")
    data = bytes.fromhex(lines[0].split("RawData=", 1)[1])
    if len(data) != count:
        raise ValueError("Native raw-data byte count differed")
    return data


def integer(text):
    return int(text.replace("$", "0x"), 0) if str(text).lower().startswith(("$", "0x", "0b")) else int(text)


def trial_value(layout, before, codec, trial):
    kind = layout.parameter.type
    if kind == "sixbit":
        return ("AB12CD34", "XY98ZT76")[trial]
    if kind == "string":
        return ("MEMORY_ALPHA", "MEMORY_ZULU")[trial][:layout.array_size]
    p = layout.parameter
    minimum = integer(p.fields["MinValue"]) if p.fields.get("MinValue", "").strip() else 0
    maximum = integer(p.fields["MaxValue"]) if p.fields.get("MaxValue", "").strip() else (1 << layout.bit_size) - 1
    minimum, maximum = max(0, minimum), min((1 << layout.bit_size) - 1, maximum)
    if minimum > maximum:
        raise ValueError("Semantic range has no representable unsigned value")
    existing = codec.decode(p.name, before)
    existing = [existing] if layout.array_size == 1 else existing
    result = []
    for index, old in enumerate(existing):
        desired = maximum if (index + trial) % 2 else minimum
        if desired == old and maximum != minimum:
            desired = minimum if desired == maximum else maximum
        result.append(desired)
    return result[0] if layout.array_size == 1 else result


def compare(session, codec, name):
    layout = codec.layout(name)
    start, count = layout.address, layout.end_address - layout.address
    trials = []
    for trial, seed in enumerate((0xA5, 0x5A)):
        # Establish every byte explicitly, including gaps and unrelated bits.
        # Native unknown-memory markers therefore cannot masquerade as bytes.
        baseline = bytes([seed]) * count
        session.set_raw_data(start, baseline)
        observed = raw(session, start, count)
        if observed != baseline:
            raise AssertionError("Native raw initialization differed")
        image = MemoryImage.from_bytes(baseline, start=start)
        value = trial_value(layout, image, codec, trial)
        patch = codec.encode(name, value)
        expected = patch.apply(image)
        text = " ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        session.set(name, text)
        actual_bytes = raw(session, start, count)
        expected_bytes = expected.read(start, count)
        if actual_bytes != expected_bytes:
            differences = [start + i for i, (a, b) in enumerate(zip(actual_bytes, expected_bytes)) if a != b]
            raise AssertionError("Native byte mismatch at addresses " + str(differences[:12]))
        native = session.values(name)[name]
        if layout.parameter.type in ("int", "long", "bit"):
            native_values = [int(token, 0) for token in native.split()]
            native = native_values[0] if layout.array_size == 1 else native_values
        if native != codec.decode(name, expected):
            raise AssertionError("Native named value differs from decoded bytes")
        if actual_bytes == baseline:
            raise AssertionError("Test vector did not change any byte")
        trials.append({"seed": seed, "value": value, "native_value": native,
                       "changed_bytes": sum(a != b for a, b in zip(actual_bytes, baseline)),
                       "compared_bytes": count, "patch_edits": len(patch.edits),
                       "result_sha256": hashlib.sha256(actual_bytes).hexdigest(), "status": "pass"})
    return trials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="explicit disposable C-Gate server")
    parser.add_argument("--port", type=int, default=20023)
    parser.add_argument("--spec-dir", type=Path, default=ROOT / "research/vendor/unitspec-plain")
    parser.add_argument("--catalog", type=Path, default=ROOT / "research/vendor/cgate/app/unitspec/cbusunits.xml")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/native-memory-acceptance.json")
    args = parser.parse_args()
    store, catalog = UnitSpecStore(args.spec_dir), UnitCatalog.load(args.catalog)
    layouts, specs, chosen = inventory(store, catalog)
    project = "M" + uuid4().hex[:7].upper()
    report = {"format": "cbus-native-memory-acceptance-v1", "time": datetime.now(timezone.utc).isoformat(),
              "scope": "Changing-value differential acceptance of distinct logical memory layouts; not per-device, firmware or Toolkit workflow parity.",
              "host": args.host, "port": args.port, "project": project,
              "layout_signature": ["type", "bit_size", "bit_address", "array_skip", "array_size", "endian"],
              "codec_sha256": sha(ROOT / "src/cbus_toolkit/memory.py"), "catalog_sha256": sha(args.catalog),
              "spec_source_sha256": {p.name: sha(p) for p in sorted(args.spec_dir.glob("*.xml"))},
              "distinct_layouts": len(layouts), "cases": [], "cleanup": [],
              "limitations": ["ArrayMap does not occur in this resolved vendor corpus; it has synthetic fixed-vector tests only.",
                              "Long endian=big writes are explicitly unsupported because the native encoder is inconsistent; this corpus uses little-endian long values only.",
                              "Non-ASCII string/JVM charset asymmetry is covered by separate native tests, not this ASCII layout corpus.",
                              "Memory offset translation, device transfer methods, checksums and hardware effects are outside this acceptance."]}
    for key in sorted(layouts):
        if key not in chosen:
            report["cases"].append({"layout": list(key), "status": "unexercised",
                                    "reason": "No concrete catalogue fixture with a native token-addressable parameter name",
                                    "schema_candidates": [{"spec": f, "parameter": n} for f, n in layouts[key]]})
    grouped = defaultdict(list)
    for key, (filename, name, fixture) in chosen.items():
        grouped[filename].append((key, name, fixture))
    with CGateClient(args.host, args.port, timeout=30) as client:
        client.command("PROJECT NEW " + project)
        try:
            client.command("PROJECT USE " + project)
            client.command("DBCREATENET 254 Memory_Corpus Cni 127.0.0.1:29999")
            client.command("NET LOAD DB " + project)
            client.command("PROJECT SAVE " + project)
            try:
                report["server"] = list(client.command("GET / version").lines)
            except Exception as exc:
                report["server_version_error"] = str(exc)
            programmer = Programmer(client)
            for filename, cases in sorted(grouped.items()):
                fixture = cases[0][2]
                row_base = {"spec": filename, "unit_type": fixture["unit_type"],
                            "firmware": fixture["minimum_version"], "catalog_number": fixture["catalog_number"]}
                path = f"//{project}/254/p/220"
                added = False
                try:
                    client.command(f"DBADDSAFE //{project}/254 Unit 220 Memory_Corpus")
                    added = True
                    for field, value in (("UnitType", fixture["unit_type"]), ("FirmwareVersion", fixture["minimum_version"]),
                                         ("CatalogNumber", fixture["catalog_number"]), ("UnitName", "MEMORY")):
                        client.command(f"DBSET {path}/{field} {value}")
                    codec = MemoryCodec(specs[filename])
                    with programmer.load(f"//{project}/254", "/db" + path, name="MEM_" + uuid4().hex[:8]) as session:
                        for key, name, _ in sorted(cases):
                            row = {**row_base, "layout": list(key), "parameter": name}
                            try:
                                row["trials"] = compare(session, codec, name)
                                row["status"] = "pass"
                            except Exception as exc:
                                row.update(status="fail", error=type(exc).__name__ + ": " + str(exc))
                            report["cases"].append(row)
                except Exception as exc:
                    already = {(r.get("spec"), tuple(r["layout"])) for r in report["cases"]}
                    for key, name, _ in cases:
                        if (filename, key) not in already:
                            report["cases"].append({**row_base, "layout": list(key), "parameter": name,
                                                    "status": "fixture_failed", "error": type(exc).__name__ + ": " + str(exc)})
                finally:
                    if added:
                        try:
                            client.command("DBDELETE " + path)
                        except Exception as exc:
                            report["cleanup"].append({"operation": "delete-unit", "error": str(exc)})
                print(json.dumps({"spec": filename, "processed": len(report["cases"]), "statuses": dict(Counter(r["status"] for r in report["cases"]))}), flush=True)
        finally:
            for action in ("CLOSE", "DELETE"):
                try:
                    client.command(f"PROJECT {action} {project}")
                except Exception as exc:
                    report["cleanup"].append({"operation": action, "error": str(exc)})
    report["cases"].sort(key=lambda r: tuple(r["layout"]))
    report["summary"] = dict(Counter(r["status"] for r in report["cases"]))
    report["summary"]["passing_change_trials"] = sum(len(r.get("trials", [])) for r in report["cases"] if r["status"] == "pass")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": report["summary"], "cleanup_errors": len(report["cleanup"])}))
    return int(bool(report["cleanup"]) or any(r["status"] != "pass" for r in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
