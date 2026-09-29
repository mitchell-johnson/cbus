#!/usr/bin/env python3
"""Run every admitted CONVERTUNIT pair against one owned C-Gate-compatible server.

Each positive case creates synthetic database units with generated non-default
PP values, converts them in catalogue (mode 1) and move (mode 2) form, and
compares the stored PP list, rebuilt identity, PP GET readback and a
save/close/load reload against ``cbus_toolkit.conversion_mapping``. Expected
values come only from the private mapping table, unit specifications and
catalogue plus the source values read back before conversion.

The receipt keeps hashes of private inputs and of per-case PP lists, never the
vendor files, decoded specifications or complete parameter inventories.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.cgate import CGateClient, CGateError
from cbus_toolkit.conversion_mapping import (MappingTable, admitted_pairs, catalog_default, convert_parameters,
                                             expected_identity, load_catalog, render_parameters,
                                             session_default)
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, ProgrammingError, xml_text
from cbus_toolkit.unitspec import UnitSpecStore


FORMAT = "cbus-convertunit-pairs-receipt-v1"
# Representative catalogue numbers, each resolved to its catalogue default revision.
CATALOGS = {
    "DIMDU4": "L5504D2U", "DIMDN4": "L5504D2A", "DIMDN4F": "LU5504TD4A", "DIMDN8": "L5508D1A",
    "DIMDN8F": "SLC5508TD2A", "DIMDD4": "5504D2D", "DIMDD8": "5508D1D", "RELDN4": "L5504RVF16",
    "RELDN8": "L5508RVF", "RELDN12": "L5512RVF", "RELDN4A": "5504RVF", "RELDN8A": "5508RVF",
    "RELDN16A": "5516RVF",
}
# Identity and protocol-owned fields are left at their initialized values.
FIXED = frozenset({"UnitAddress", "Project", "NetworkAddress", "CustType", "SerialNo", "CheckSum"})
# Explicit per-seed values that reach every rule branch in the admitted table.
SEEDED = {
    1: {"InterLockingChannel": "2", "PowerUpDelay": "3 70 90 10 255 59 60 61", "RestrikeDelay": "7",
        "ErrorRefreshTime": "6", "LocalToggleEnable": "0", "NetworkPriority": "0", "UnitName": "CONVA"},
    2: {"InterLockingChannel": "9", "PowerUpDelay": "61 5 200 0 12 90 70 3", "RestrikeDelay": "0",
        "ErrorRefreshTime": "3", "LocalToggleEnable": "1", "NetworkPriority": "1", "UnitName": "CONVB"},
    3: {"InterLockingChannel": "5", "PowerUpDelay": "9 9 9 9 9 9 9 9", "RestrikeDelay": "12",
        "ErrorRefreshTime": "7", "UnitName": "DEST"},
}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def canonical(value) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


class Inputs:
    """Private vendor inputs, loaded once and identified by hash."""
    def __init__(self, spec_dir: Path, catalog_path: Path, table_path: Path):
        self.store = UnitSpecStore(spec_dir)
        self.catalog = load_catalog(catalog_path)
        self.table = MappingTable.load(table_path)
        self.hashes = {"ConvertUnitMappingTable.xml": self.table.sha256,
                       "cbusunits.xml": digest(catalog_path.read_bytes())}
        self.spec_dir = spec_dir

    def revision(self, unit_type):
        catalog = CATALOGS[unit_type]
        record = catalog_default(self.catalog, unit_type, catalog)
        return catalog, record["firmware"], record["spec_filename"]

    def spec(self, unit_type):
        spec = self.store.load(self.revision(unit_type)[2])
        for filename in spec.sources:  # The selected file and its includes.
            self.hashes.setdefault(filename, digest((self.spec_dir / filename).read_bytes()))
        return spec


def generated_values(spec, seed):
    """Deterministic valid non-default values for writable numeric parameters."""
    values = {}
    for name, parameter in spec.parameters.items():
        if name in FIXED or parameter.type not in ("int", "bit"):
            continue
        low = int(parameter.fields.get("MinValue", "0").replace("$", "0x"), 0) if parameter.fields.get("MinValue", "").strip() else 0
        high = (int(parameter.fields["MaxValue"].replace("$", "0x"), 0) if parameter.fields.get("MaxValue", "").strip()
                else (1 << parameter.bit_size) - 1)
        if parameter.type == "bit":
            low, high = max(low, 0), min(high, 1)
        span = high - low + 1
        salt = int(digest(f"{seed}:{name}".encode())[:8], 16)
        values[name] = " ".join(str(low + (salt + index * (seed * 2 + 1)) % span) for index in range(parameter.array_size))
    for name, value in SEEDED[seed].items():
        if name in spec.parameters:
            count = spec.parameters[name].array_size
            tokens = value.split()
            values[name] = " ".join(tokens[:count]) if spec.parameters[name].type != "sixbit" else value
    return values


def unit_document(client, path):
    root = ET.fromstring(xml_text(client.command("DBGETXML " + path)))
    scalars = {child.tag: child.text or "" for child in root if child.tag not in ("PP", "OutputChannel") and len(child) == 0}
    pp = [(child.get("Name"), child.get("Value")) for child in root if child.tag == "PP"]
    channels = [{grand.tag: grand.text or "" for grand in child if grand.tag in ("Address", "TagName")}
                for child in root if child.tag == "OutputChannel"]
    return {"scalars": scalars, "pp": pp, "channels": channels}


def response_row(response):
    return {"code": response.code, "final": response.final}


def command(client, text):
    try:
        return client.command(text)
    except CGateError as error:
        return error.response


class Runner:
    def __init__(self, client, inputs: Inputs, *, project=None):
        self.client = client
        self.inputs = inputs
        self.projects = NativeProjects(client)
        self.db = NativeDatabase(client)
        self.programmer = Programmer(client)
        self.project = project or ("V" + uuid4().hex[:7].upper())
        self.network = f"//{self.project}/254"
        self.address = 10

    def open(self):
        self.projects.operation("new", self.project)
        self.projects.operation("use", self.project)
        command(self.client, "DBCREATENET 254 Conversion Cni 127.0.0.1:29999")
        # Native loads the closed runtime model; cmqttd treats NET LOAD as a
        # snapshot restore and needs no runtime load for database units.
        command(self.client, "NET LOAD DB")

    def close(self):
        for action in ("close", "delete"):
            try:
                self.projects.operation(action, self.project)
            except (CGateError, RuntimeError, OSError):
                pass

    def make_unit(self, unit_type, seed):
        catalog, firmware, _ = self.inputs.revision(unit_type)
        spec = self.inputs.spec(unit_type)
        address = self.address
        self.address += 1
        path = f"{self.network}/p/{address}"
        self.db.create_unit(self.network, address, f"Unit{address}", unit_type, firmware, catalog_number=catalog)
        rejected = []
        with self.programmer.load(self.network, "/db" + path) as session:
            for name, value in generated_values(spec, seed).items():
                try:
                    session.set(name, value)
                except (CGateError, RuntimeError, ValueError):
                    rejected.append(name)
            session.save_to_source()
        return path, rejected

    def readback(self, path, target_spec, predicted):
        """PP GET values must agree with the stored list or the target default.

        C-Gate can store a rule result that its own PP loader cannot parse. The
        model predicts that from the stored strings; the load error is retained.
        """
        stored = dict(predicted)
        unparseable = sorted(name for name, value in predicted
                             if name in target_spec.parameters and not _parseable(target_spec.parameters[name], value))
        try:
            with self.programmer.load(self.network, "/db" + path) as session:
                values = session.values()
        except (CGateError, ProgrammingError) as error:
            text = error.response.final if isinstance(error, CGateError) else str(error)
            named = sorted(set(re.findall(r"parameter (\w+) \(", text)))
            consistent = bool(unparseable) and bool(named) and set(named) <= set(unparseable)
            return {"loaded": False, "error_codes": sorted(set(re.findall(r"\b([2-5][0-9]{2})\b", text))),
                    "error_parameters": named, "predicted_unparseable": unparseable,
                    "mismatches": [] if consistent else ["<load>"]}
        if unparseable:
            return {"loaded": True, "predicted_unparseable": unparseable, "mismatches": ["<unexpected-load>"]}
        mismatches = []
        for name, parameter in target_spec.parameters.items():
            expected = stored.get(name)
            actual = values.get(name)
            if expected is None:
                expected = session_default(parameter)
            if not _equivalent(parameter, expected, actual):
                mismatches.append(name)
        return {"loaded": True, "parameter_count": len(values), "mismatches": mismatches}

    def positive(self, source_type, target_type, mode):
        source, rejected = self.make_unit(source_type, 1 if mode == 1 else 2)
        before = unit_document(self.client, source)
        target_spec = self.inputs.spec(target_type)
        destination_before = None
        if mode == 1:
            catalog = self.inputs.revision(target_type)[0]
            arguments = f"1 {source} {target_type} {catalog}"
            destination = source
        else:
            destination, _ = self.make_unit(target_type, 3)
            destination_before = unit_document(self.client, destination)
            arguments = f"2 {source} {destination}"
            catalog = destination_before["scalars"].get("CatalogNumber")
        # Native stores rendered PP strings; a Rust server may retain the set
        # spelling. Rules operate on the native rendering in both cases.
        rendered = render_parameters(self.inputs.spec(source_type), before["pp"])
        predicted = convert_parameters(self.inputs.table, source_type, rendered, target_spec, target_type)
        identity = expected_identity(mode=mode, source=before["scalars"],
                                     destination=destination_before and destination_before["scalars"],
                                     target_type=target_type, catalog_number=catalog, catalog=self.inputs.catalog)
        self.projects.operation("use", self.project)
        check = command(self.client, "CONVERTUNIT CHECK " + arguments)
        convert = command(self.client, "CONVERTUNIT CONVERT " + arguments)
        row = {"id": f"{source_type}->{target_type}/mode{mode}", "source_type": source_type,
               "target_type": target_type, "mode": mode,
               "table_index": getattr(self.inputs.table.find(source_type, target_type), "index", None),
               "rules": sorted({rule.name for pair in getattr(self.inputs.table.find(source_type, target_type), "pairs", ())
                                for rule in pair.rules}),
               "check": response_row(check), "convert": response_row(convert),
               "source_stored_as_rendered": rendered == before["pp"],
               "source_rejected_sets": rejected, "source_pp_count": len(before["pp"]),
               "predicted_pp_count": len(predicted), "predicted_sha256": canonical(predicted),
               "target_parameter_count": len(target_spec.parameters)}
        if convert.code != 200:
            row["passed"] = False
            return row
        after = unit_document(self.client, destination)
        observed_identity = {key: after["scalars"].get(key) for key in identity if key != "OutputChannels"}
        observed_identity = {key: value for key, value in observed_identity.items() if value is not None}
        observed_identity["OutputChannels"] = after["channels"]
        row.update(observed_sha256=canonical(after["pp"]),
                   pp_matches=after["pp"] == predicted,
                   pp_set_matches=dict(after["pp"]) == dict(predicted),
                   pp_mismatches=sorted(name for name in set(dict(after["pp"])) | set(dict(predicted))
                                        if dict(after["pp"]).get(name) != dict(predicted).get(name)),
                   identity_matches=observed_identity == identity,
                   identity_mismatches=sorted(key for key in set(observed_identity) | set(identity)
                                              if observed_identity.get(key) != identity.get(key)),
                   omitted_target_parameters=len(target_spec.parameters) - len(after["pp"]),
                   output_channels=len(after["channels"]))
        if mode == 2:
            gone = command(self.client, "DBGET " + source)
            row["source_removed"] = gone.code == 401
        row["readback"] = self.readback(destination, target_spec, after["pp"])
        self.projects.operation("save", self.project)
        self.projects.operation("close", self.project)
        self.projects.operation("load", self.project)
        self.projects.operation("use", self.project)
        reloaded = unit_document(self.client, destination)
        # A native reload adds DeviceName and an empty GroupNumber scalar.
        row["reload_added_scalars"] = sorted(set(reloaded["scalars"]) - set(after["scalars"]))
        row["reload_matches"] = (reloaded["pp"] == after["pp"] and reloaded["channels"] == after["channels"]
                                 and all(reloaded["scalars"].get(key) == value for key, value in after["scalars"].items()))
        row["passed"] = bool(check.code == 200 and row["pp_set_matches"] and row["identity_matches"]
                             and row["reload_matches"] and not row["readback"]["mismatches"]
                             and row.get("source_removed", True))
        return row

    def negatives(self):
        rows = []
        def case(case_id, text, expected_code, *, unchanged=None):
            before = unit_document(self.client, unchanged) if unchanged else None
            response = command(self.client, text)
            row = {"id": case_id, "command": text.replace(self.project, "PROJECT"), **response_row(response),
                   "expected_code": expected_code}
            if unchanged:
                row["unchanged"] = unit_document(self.client, unchanged) == before
            row["passed"] = response.code == expected_code and row.get("unchanged", True)
            rows.append(row)
        self.projects.operation("use", self.project)
        dimmer, _ = self.make_unit("DIMDN4", 1)
        relay, _ = self.make_unit("RELDN4A", 1)
        c3 = f"{self.network}/p/{self.address + 50}"
        for verb in ("CHECK", "CONVERT"):
            case(f"incompatible-type/{verb}", f"CONVERTUNIT {verb} 1 {dimmer} RELDN4A 5504RVF", 301, unchanged=dimmer)
            case(f"reverse-not-admitted/{verb}", f"CONVERTUNIT {verb} 1 {relay} RELDN4 L5504RVF16", 301, unchanged=relay)
            case(f"missing-source/{verb}", f"CONVERTUNIT {verb} 1 {c3} DIMDU4 L5504D2U", 401)
            case(f"missing-destination/{verb}", f"CONVERTUNIT {verb} 2 {dimmer} {c3}", 301, unchanged=dimmer)
            case(f"incompatible-destination/{verb}", f"CONVERTUNIT {verb} 2 {dimmer} {relay}", 301, unchanged=relay)
            case(f"unknown-catalogue/{verb}", f"CONVERTUNIT {verb} 1 {dimmer} DIMDU4 NOSUCH", 301, unchanged=dimmer)
        case("unchanged-identity/CHECK", f"CONVERTUNIT CHECK 1 {dimmer} DIMDN4 L5504D2A", 200, unchanged=dimmer)
        case("unchanged-identity/CONVERT", f"CONVERTUNIT CONVERT 1 {dimmer} DIMDN4 L5504D2A", 301, unchanged=dimmer)
        case("mode-out-of-range", f"CONVERTUNIT CHECK 4 {dimmer} DIMDU4 L5504D2U", 400, unchanged=dimmer)
        return rows

    def bare_source(self):
        """A source without stored PP skips every rule and keeps only defaults."""
        address = self.address
        self.address += 1
        path = f"{self.network}/p/{address}"
        self.db.add(self.network, "unit", address, f"Bare{address}")
        for field, value in (("UnitName", "BARE"), ("UnitType", "DIMDN4"), ("FirmwareVersion", "2.7.00"),
                             ("CatalogNumber", "L5504D2A")):
            self.db.set(path + "/" + field, value)
        target_spec = self.inputs.spec("DIMDU4")
        predicted = convert_parameters(self.inputs.table, "DIMDN4", [], target_spec, "DIMDU4")
        self.projects.operation("use", self.project)
        response = command(self.client, f"CONVERTUNIT CONVERT 1 {path} DIMDU4 L5504D2U")
        row = {"id": "bare-source/DIMDN4->DIMDU4/mode1", **response_row(response), "predicted_pp_count": len(predicted)}
        if response.code == 200:
            after = unit_document(self.client, path)
            row.update(pp_set_matches=dict(after["pp"]) == dict(predicted),
                       pp_mismatches=sorted(name for name in set(dict(after["pp"])) | set(dict(predicted))
                                            if dict(after["pp"]).get(name) != dict(predicted).get(name)))
        row["passed"] = response.code == 200 and row.get("pp_set_matches", False)
        return row


def _parseable(parameter, value):
    """Whether C-Gate's PP loader accepts one stored value for this parameter."""
    if parameter.type not in ("int", "bit", "long"):
        return True
    tokens = value.split()
    return (len(tokens) == parameter.array_size
            and all(re.fullmatch(r"0[xX][0-9A-Fa-f]+|[0-9]+", token) for token in tokens))


def _equivalent(parameter, expected, actual):
    if actual is None:
        return expected in (None, "")
    if parameter.type in ("int", "bit", "long"):
        def numbers(text):
            return [int(token[1:], 16) if token.startswith("$") else int(token, 0) for token in text.split()]
        try:
            want, got = numbers(expected), numbers(actual)
        except ValueError:
            return False
        return got == want
    return expected.rstrip() == actual.rstrip()


def run(client, inputs: Inputs, *, pairs=None, modes=(1, 2)):
    runner = Runner(client, inputs)
    runner.open()
    try:
        cases = []
        for source, target in pairs or admitted_pairs():
            for mode in modes:
                try:
                    cases.append(runner.positive(source, target, mode))
                except (CGateError, RuntimeError, ValueError, OSError) as error:
                    cases.append({"id": f"{source}->{target}/mode{mode}", "passed": False,
                                  "error": f"{type(error).__name__}: {error}"})
        negatives = runner.negatives()
        bare = runner.bare_source()
    finally:
        runner.close()
    return {"format": FORMAT, "inputs": dict(sorted(inputs.hashes.items())), "cases": cases,
            "negative_cases": negatives, "boundary_cases": [bare],
            "summary": {"positive": len(cases), "positive_passed": sum(row["passed"] for row in cases),
                        "negative": len(negatives), "negative_passed": sum(row["passed"] for row in negatives),
                        "boundary_passed": int(bare["passed"])}}


@contextmanager
def owned_backend(backend, *, spec_dir, catalog_path, table_path, binary=None, vendor=None, java=None):
    if backend == "native":
        from research.local_cgate import LocalCGate
        service = LocalCGate(vendor, java=java)
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        with service:
            client = CGateClient("127.0.0.1", service.port, timeout=60).connect()
            try:
                yield client, {"backend": "native", "cgate_jar_sha256": service.report["vendor_jar_sha256"],
                               "java_sha256": service.report["java_sha256"]}
            finally:
                client.close()
        return
    with tempfile.TemporaryDirectory(prefix="cbus-convertunit-") as tmp:
        specs = Path(tmp) / "unitspec"
        specs.mkdir()
        # Rust servers confine specification reads to the canonical directory,
        # so private inputs are copied into this owned temporary directory.
        for path in sorted(Path(spec_dir).glob("*.xml")):
            shutil.copyfile(path, specs / path.name)
        if not (specs / "cbusunits.xml").exists():
            shutil.copyfile(catalog_path, specs / "cbusunits.xml")
        with _rust_server(backend, Path(binary), specs, Path(tmp)) as port:
            client = CGateClient("127.0.0.1", port, timeout=60).connect()
            try:
                yield client, {"backend": backend, "binary_sha256": digest(Path(binary).read_bytes())}
            finally:
                client.close()


@contextmanager
def _rust_server(backend, binary, specs, scratch):
    if backend == "cgate-mock":
        process = subprocess.Popen([str(binary), "--bind", "127.0.0.1:0", "--unitspec", str(specs)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            if not select.select([process.stdout], [], [], 10)[0]:
                raise TimeoutError("mock listener announcement timed out")
            match = re.fullmatch(r"cgate-mock listening on 127\.0\.0\.1:([0-9]+)", process.stdout.readline().strip())
            if match is None:
                raise ValueError("mock listener is not owned IPv4 loopback")
            yield int(match[1])
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdout.close()
        return
    from cbus_toolkit.simulator import PCISimulator
    project = scratch / "project.xml"
    project.write_text("<Installation><Project><TagName>BRIDGE_TEST</TagName><Network><Address>254</Address>"
                       "<TagName>Loopback</TagName></Network></Project></Installation>", encoding="utf-8")
    with socket.socket() as broker, PCISimulator(profile="captured", command_checksum=True).running() as pci:
        broker.bind(("127.0.0.1", 0))
        broker.listen(1)
        with (scratch / "cmqttd.log").open("w+") as log:
            process = subprocess.Popen([
                str(binary), "--tcp", f"{pci[0]}:{pci[1]}", "--broker-address", "127.0.0.1",
                "--broker-port", str(broker.getsockname()[1]), "--broker-disable-tls", "--timesync", "0",
                "--status-resync", "0", "--project-file", str(project), "--cgate-bind", "127.0.0.1:0",
                "--cgate-state", str(scratch / "state.json"), "--cgate-unitspec", str(specs),
            ], stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while True:
                    log.seek(0)
                    match = re.search(r"C-Gate service listening on 127\.0\.0\.1:([0-9]+)", log.read())
                    if match:
                        yield int(match[1])
                        break
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("cmqttd C-Gate listener did not open")
                    time.sleep(.02)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("native", "cgate-mock", "cmqttd"), required=True)
    parser.add_argument("--unitspec", type=Path, default=os.environ.get("CBUS_UNITSPEC_DIR"))
    parser.add_argument("--catalog", type=Path, help="cbusunits.xml (default: <vendor>/unitspec/cbusunits.xml)")
    parser.add_argument("--vendor", type=Path, default=os.environ.get("CBUS_LOCAL_CGATE_VENDOR"))
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.unitspec is None:
        parser.error("--unitspec or CBUS_UNITSPEC_DIR is required")
    catalog = args.catalog or (args.vendor / "unitspec/cbusunits.xml" if args.vendor else None)
    if catalog is None:
        parser.error("--catalog or --vendor is required")
    table = args.unitspec / "ConvertUnitMappingTable.xml"
    inputs = Inputs(args.unitspec, catalog, table)
    encrypted = args.vendor / "unitspec/ConvertUnitMappingTable.xml.es" if args.vendor else None
    if encrypted and encrypted.is_file():
        inputs.hashes["ConvertUnitMappingTable.xml.es"] = digest(encrypted.read_bytes())
    with owned_backend(args.backend, spec_dir=args.unitspec, catalog_path=catalog, table_path=table,
                       binary=args.binary, vendor=args.vendor, java=os.environ.get("CBUS_CGATE_JAVA")) as (client, backend):
        receipt = run(client, inputs)
    receipt["backend"] = backend
    # Private input locations are omitted; their hashes identify them.
    receipt["command"] = shlex.join(["research/convertunit_pairs.py", "--backend", args.backend])
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt["summary"]))
    return 0 if all(row["passed"] for row in [*receipt["cases"], *receipt["negative_cases"],
                                              *receipt["boundary_cases"]]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
