"""Single physical KEYE1 address move to an independently empty destination."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .addressing import _container, _network_canonical
from .cgate import CGateError
from .classic_replacement import _path, _field
from .native import NativeDatabase, _address
from .programming import xml_text
from .serial_population import _fingerprint
from .serials import NativeSerials, SerialTransportError, parse_native_serial


class PhysicalAddressUncertain(RuntimeError):
    """A write was attempted; recovery must observe state rather than replay it."""
    def __init__(self, message, details):
        self.details = details
        super().__init__(message)


def _digest(text):
    return hashlib.sha256(repr(_network_canonical(text)).encode()).hexdigest()


@dataclass(frozen=True)
class PhysicalAddressPlan:
    FORMAT = "cbus-physical-unit-readdress-plan-v1"
    source: str
    destination: str
    serial: str
    unit_type: str
    firmware: str
    inventory: tuple[tuple, ...]
    runtime: tuple[tuple[str, str], ...]
    database_xml: str
    database_hash: str

    @staticmethod
    def _allowed_addresses(old, new):
        return old != new and 1 <= old <= 254 and 1 <= new <= 254

    def as_dict(self):
        return {"format": self.FORMAT, "source": self.source,
                "destination": self.destination, "serial": self.serial, "unit_type": self.unit_type,
                "firmware": self.firmware, "database_hash": self.database_hash,
                "inventory": [list(row) for row in self.inventory], "runtime": dict(self.runtime),
                "database_xml": self.database_xml,
                "native_retries": 0, "automatic_write_retries": 0, "database_changed": False,
                "physical_refresh_scope": "entire_network", "moved": False}

    @classmethod
    def from_dict(cls, document):
        """Read a complete recovery baseline without issuing native commands.

        The XML/hash and identities are caller-supplied evidence, not a signed
        attestation. Application still rebuilds and compares a fresh plan.
        """
        fields = {"format", "source", "destination", "serial", "unit_type", "firmware", "database_hash",
                  "inventory", "runtime", "database_xml", "native_retries", "automatic_write_retries",
                  "database_changed", "physical_refresh_scope", "moved"}
        if not isinstance(document, dict) or set(document) != fields:
            raise ValueError("Recovery requires a complete physical address plan document")
        for name, value in (("format", cls.FORMAT),
                            ("native_retries", 0), ("automatic_write_retries", 0),
                            ("database_changed", False), ("physical_refresh_scope", "entire_network"), ("moved", False)):
            if type(document[name]) is not type(value) or document[name] != value:
                raise ValueError("Invalid physical recovery plan field: " + name)
        for name in ("source", "destination", "serial", "unit_type", "firmware", "database_xml", "database_hash"):
            if not isinstance(document[name], str): raise ValueError("Invalid physical recovery plan field: " + name)
        source, project, number, old = _path(document["source"])
        destination, target_project, target_number, new = _path(document["destination"])
        if (source != document["source"] or destination != document["destination"]
                or (project, number) != (target_project, target_number)
                or not cls._allowed_addresses(old, new)):
            raise ValueError("Invalid physical recovery source or destination")
        serial = parse_native_serial(document["serial"])
        if (not serial.known or serial.canonical != document["serial"]
                or document["unit_type"] != "KEYE1" or document["firmware"] != "2.5.00"):
            raise ValueError("Invalid or unsupported recovery identity")
        rows = document["inventory"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
            raise ValueError("Recovery inventory must be nonempty and bounded")
        inventory, addresses, serials = [], set(), set()
        for row in rows:
            if (not isinstance(row, list) or len(row) != 5 or type(row[0]) is not int
                    or not 0 <= row[0] <= 255 or any(not isinstance(value, str) or not value
                        or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in row[1:])
                    or row[4] != "ok"):
                raise ValueError("Invalid recovery inventory row")
            identity = parse_native_serial(row[3])
            if not identity.known or row[0] in addresses or identity.canonical in serials:
                raise ValueError("Recovery inventory contains unknown or duplicate identities")
            inventory.append(tuple(row)); addresses.add(row[0]); serials.add(identity.canonical)
        source_rows = [row for row in inventory if row[0] == old]
        if (inventory != sorted(inventory) or new in addresses or len(source_rows) != 1
                or source_rows[0][1:3] != (document["unit_type"], document["firmware"])
                or parse_native_serial(source_rows[0][3]).canonical != serial.canonical):
            raise ValueError("Recovery inventory does not describe the original source and empty destination")
        runtime = document["runtime"]
        expected = {"InterfaceState": "running", "TargetInterfaceState": "running", "SyncState": "idle",
                    "AutoUnravel": "no", "AutoUpdate": "no", "Retries": "0", "NetworkType": "Wired", "Name": str(number)}
        if (not isinstance(runtime, dict) or set(runtime) != set(expected) | {"Type", "InterfaceAddress"}
                or any(runtime[name] != value for name, value in expected.items())
                or any(not isinstance(value, str) or not value
                    or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in runtime.values())):
            raise ValueError("Invalid recovery runtime preconditions")
        database = _container(document["database_xml"], "Network")
        interfaces = database.getElementsByTagName("InterfaceType")
        endpoints = database.getElementsByTagName("InterfaceAddress")
        if (len(interfaces) != 1 or len(endpoints) != 1 or not interfaces[0].firstChild or not endpoints[0].firstChild
                or interfaces[0].firstChild.data.lower() not in ("cni", "serial")
                or interfaces[0].firstChild.data.lower() != runtime["Type"].lower()
                or endpoints[0].firstChild.data != runtime["InterfaceAddress"]
                or _field(database, "Address") != str(number)
                or _digest(document["database_xml"]) != document["database_hash"]):
            raise ValueError("Recovery database evidence or hash is inconsistent")
        return cls(source, destination, serial.canonical, document["unit_type"], document["firmware"],
                   tuple(inventory), tuple(sorted(runtime.items())), document["database_xml"], document["database_hash"])


class PhysicalAddressing:
    def __init__(self, client):
        self.client, self.scanner, self.database = client, NativeSerials(client), NativeDatabase(client)
        self.last_uncertain = None

    def _runtime(self, network):
        expected = {"InterfaceState": "running", "TargetInterfaceState": "running", "SyncState": "idle",
                    "AutoUnravel": "no", "AutoUpdate": "no", "Retries": "0", "NetworkType": "Wired"}
        result = {}
        for field, required in expected.items():
            result[field] = self.scanner._get(network, field)
            if result[field] != required:
                raise ValueError(f"Physical readdress requires {field}={required}; native value is {result[field]!r}")
        for field in ("Name", "Type", "InterfaceAddress"):
            result[field] = self.scanner._get(network, field)
        if result["Name"] != network.rsplit("/", 1)[1]:
            raise ValueError("Runtime network name differs from its path")
        return tuple(sorted(result.items()))

    def _database(self, network):
        text = xml_text(self.database.get(network, xml=True))
        document = _container(text, "Network")
        interfaces = [n.firstChild.data if n.firstChild else "" for n in document.getElementsByTagName("InterfaceType")]
        if len(interfaces) != 1 or interfaces[0].lower() not in ("cni", "serial"):
            raise ValueError("Physical address helper requires one direct CNI or Serial interface")
        if _field(document, "Address") != network.rsplit("/", 1)[1]:
            raise ValueError("Database network address differs from its path")
        return text

    @staticmethod
    def _paths(source, new_address):
        source, project, number, old = _path(source)
        new = int(_address(new_address))
        if not 1 <= old <= 254 or not 1 <= new <= 254 or new == old:
            raise ValueError("Distinct physical addresses in 1..254 are required")
        network = f"//{project}/{number}"
        return source, network + "/p/" + str(new), network, old, new

    @staticmethod
    def _pair(inventory, old, new):
        if inventory.errors or not inventory.refresh_completed:
            raise ValueError("Physical address check did not complete: " + " | ".join(inventory.errors))
        records = {r.address: r for r in inventory.records}
        if set(records) != {old, new}: raise ValueError("Physical address check omitted an address")
        return records[old], records[new]

    def _coverage(self, network, inventory, *, present=(), absent=()):
        """Require the native dk/dn reader's complete MMI address coverage.

        CHECKUNIT and SYNC use dw/dx, which can interpret omitted ranges as
        zero even for explicitly selected addresses. PINGU uses the separate
        dk/dn reader that rejects missing/overlapping ranges. Its address list
        must agree with every healthy cached identity; no absent range is
        inferred from the cache or the CHECKUNIT result.
        """
        command = "NET PINGU " + network
        response = self.scanner._command(command)
        if (response.code != 200 or len(response.lines) != 2
                or response.lines[1] != "200 OK."):
            raise ValueError("Physical address coverage requires an exact successful NET PINGU reply")
        match = re.fullmatch(r"302-Units=([0-9]{1,3}(?:, [0-9]{1,3})*)", response.lines[0])
        if not match:
            raise ValueError("Physical address coverage requires a nonempty NET PINGU unit list")
        tokens = match[1].split(", ")
        addresses = tuple(int(value) for value in tokens)
        if (any(value > 255 or token != str(value) for token, value in zip(tokens, addresses))
                or tuple(sorted(set(addresses))) != addresses):
            raise ValueError("NET PINGU unit addresses must be unique, ordered decimal values in 0..255")
        if any(address not in addresses for address in present):
            raise ValueError("NET PINGU does not independently observe the required source address")
        if any(address in addresses for address in absent):
            raise ValueError("NET PINGU observes an occupied physical destination")
        expected = tuple(row[0] for row in inventory)
        if not expected or addresses != expected:
            raise ValueError("NET PINGU full address coverage differs from the healthy cached identity inventory")
        return {"command": command, "reply": list(response.lines), "addresses": list(addresses),
                "native_reader": "dk/dn", "full_coverage": True, "cached_addresses_match": True}

    def plan(self, source, new_address, *, expected_serial):
        source, destination, network, old, new = self._paths(source, new_address)
        expected = parse_native_serial(expected_serial)
        if not expected.known: raise ValueError("A known expected native serial is required")
        runtime = self._runtime(network)
        database = self._database(network)
        document = _container(database, "Network")
        endpoints = document.getElementsByTagName("InterfaceAddress")
        kinds = document.getElementsByTagName("InterfaceType")
        if (len(endpoints) != 1 or not endpoints[0].firstChild
                or endpoints[0].firstChild.data != dict(runtime)["InterfaceAddress"]
                or kinds[0].firstChild.data.lower() != dict(runtime)["Type"].lower()):
            raise ValueError("Runtime and database interface definitions differ")
        pair = self.scanner.refresh(network, [old, new])
        before, target = self._pair(pair, old, new)
        if before.status != "ok" or before.presence != "single":
            raise ValueError("Source must contain exactly one healthy physical unit")
        if target.status != "absent": raise ValueError("Physical destination is occupied or unresolved")
        if before.unit_type != "KEYE1" or before.firmware != "2.5.00":
            raise ValueError("Physical readdress is verified only for KEYE1 firmware 2.5.00")
        actual = parse_native_serial(before.serial)
        if actual.canonical != expected.canonical: raise ValueError("Source serial differs from the expected unit")
        inventory = _fingerprint(self.scanner.cached(network))
        if any(row[1] == "BRIDGE" or row[1].startswith("WGATE") for row in inventory):
            raise ValueError("Bridge and wireless gateway topologies are outside this physical workflow")
        if any(row[0] == new for row in inventory): raise ValueError("Destination remains occupied in the native model")
        if not any(row[:4] == (old, before.unit_type, before.firmware, before.serial) for row in inventory):
            raise ValueError("Physical source changed during observation")
        if _digest(self._database(network)) != _digest(database):
            raise ValueError("Database changed during physical observation")
        if self._runtime(network) != runtime: raise ValueError("Runtime settings changed during observation")
        self._coverage(network, inventory, present=(old,), absent=(new,))
        return PhysicalAddressPlan(source, destination, actual.canonical, before.unit_type, before.firmware,
                                   inventory, runtime, database, _digest(database))

    def verify(self, plan):
        """Observe a completed/uncertain move with fresh physical reads; no write."""
        if not isinstance(plan, PhysicalAddressPlan): raise ValueError("Expected a PhysicalAddressPlan")
        type(plan).from_dict(plan.as_dict())
        new = int(plan.destination.rsplit("/", 1)[1])
        source, destination, network, old, new = self._paths(plan.source, new)
        if destination != plan.destination: raise ValueError("Physical move must stay in one network")
        if self._runtime(network) != plan.runtime:
            raise ValueError("Recovery runtime settings differ from the original plan")
        observed = self.scanner.refresh(network, [old, new])
        result = {"outcome": "uncertain", "observation": observed.as_dict(), "database_unchanged": False,
                  "other_identities_unchanged": False, "source_absent": False, "serial_confirmed": False,
                  "observed_identities": [], "serial_observed_addresses": [], "mmi": None}
        try:
            before, after = self._pair(observed, old, new)
            inventory = _fingerprint(self.scanner.cached(network))
            result["observed_identities"] = [dict(zip(("address", "unit_type", "firmware", "serial", "state"), row)) for row in inventory]
            result["serial_observed_addresses"] = [row[0] for row in inventory if parse_native_serial(row[3]).canonical == plan.serial]
            expected = tuple(sorted((new if row[0] == old else row[0], *row[1:]) for row in plan.inventory))
            result["other_identities_unchanged"] = inventory == expected
            result["database_unchanged"] = _digest(self._database(network)) == plan.database_hash
            result["mmi"] = self._coverage(network, inventory)
            result["source_absent"] = before.status == "absent" and old not in result["mmi"]["addresses"]
            result["serial_confirmed"] = (after.status == "ok" and after.presence == "single"
                and after.unit_type == plan.unit_type and after.firmware == plan.firmware
                and parse_native_serial(after.serial).canonical == plan.serial)
            if all(result[key] for key in ("other_identities_unchanged", "database_unchanged", "source_absent", "serial_confirmed")):
                result["outcome"] = "confirmed_moved"
            elif (before.status == "ok" and after.status == "absent" and new not in result["mmi"]["addresses"]
                    and parse_native_serial(before.serial).canonical == plan.serial
                    and inventory == plan.inventory and result["database_unchanged"]):
                result["outcome"] = "confirmed_not_moved"
        except (ValueError, CGateError, SerialTransportError) as error:
            result["verification_error"] = str(error)
        return result

    def apply(self, plan):
        if not isinstance(plan, PhysicalAddressPlan): raise ValueError("Expected a PhysicalAddressPlan")
        current = self.plan(plan.source, int(plan.destination.rsplit("/", 1)[1]), expected_serial=plan.serial)
        if current != plan: raise ValueError("Physical readdress plan is stale or has been modified")
        network = plan.source.rsplit("/p/", 1)[0]
        if self._runtime(network) != plan.runtime: raise ValueError("Runtime changed immediately before physical write")
        pre_write_mmi = self._coverage(network, plan.inventory,
            present=(int(plan.source.rsplit("/", 1)[1]),), absent=(int(plan.destination.rsplit("/", 1)[1]),))
        evidence = {"plan": plan.as_dict(), "write_attempted": True, "automatic_write_retries": 0,
                    "outcome": "uncertain", "reply": None, "pre_write_mmi": pre_write_mmi}
        self.last_uncertain = None
        try:
            # There is exactly one scalar mutation. Native Retries=0 is a
            # required precondition; no rollback or reconnect can replay it.
            response = self.client.command("SET " + plan.source + " Address " + plan.destination.rsplit("/", 1)[1])
            evidence["reply"] = list(response.lines)
            if (response.code != 200 or len(response.lines) != 1
                    or response.final.upper() != ("200 OK: " + plan.destination).upper()):
                raise RuntimeError("Native address command did not confirm its destination")
            evidence["verification"] = self.verify(plan)
            if evidence["verification"]["outcome"] != "confirmed_moved":
                raise RuntimeError("Fresh physical identity verification did not confirm the complete move")
        except BaseException as error:
            if hasattr(error, "response"): evidence["reply"] = list(error.response.lines)
            evidence["cause"] = str(error)
            self.last_uncertain = evidence
            if not isinstance(error, Exception):
                # Preserve cancellation semantics and recovery evidence. The
                # C-Gate transport closes its interrupted stream; no follow-up
                # read, reconnect or reverse write is attempted here.
                evidence["interruption_type"] = type(error).__name__
                try: error.physical_address_evidence = evidence
                except BaseException: pass
                raise
            raise PhysicalAddressUncertain("Physical address outcome requires observation; the write was not replayed", evidence) from error
        return {**plan.as_dict(), **evidence, "moved": True, "outcome": "confirmed_moved"}

    def readdress(self, source, new_address, *, expected_serial):
        return self.apply(self.plan(source, new_address, expected_serial=expected_serial))
