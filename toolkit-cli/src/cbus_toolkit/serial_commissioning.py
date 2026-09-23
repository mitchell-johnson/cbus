"""Database serial matching followed by a scalar move from address255."""
from dataclasses import fields
from xml.dom import Node

from .addressing import _container
from .classic_replacement import _document, _field, _path
from .native import _address
from .physical_addressing import PhysicalAddressing, PhysicalAddressPlan, PhysicalAddressUncertain
from .serials import parse_native_serial


class SerialCommissionPlan(PhysicalAddressPlan):
    FORMAT = "cbus-serial-commission-plan-v1"
    METHOD = "database_serial_match_then_scalar_address"

    def as_dict(self):
        return {**super().as_dict(), "method": self.METHOD}

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, dict) or document.get("method", cls.METHOD) != cls.METHOD:
            raise ValueError("Invalid serial commissioning method")
        # Earlier recovery documents omitted method. Their original identity
        # baseline remains useful for observation; new application uses SET.
        baseline = dict(document); baseline.pop("method", None)
        return super().from_dict(baseline)

    @staticmethod
    def _allowed_addresses(old, new):
        return old == 255 and 2 <= new <= 254


def _database_target(plan):
    network = _container(plan.database_xml, "Network")
    target = int(plan.destination.rsplit("/", 1)[1])
    matches, addresses = [], set()
    for node in network.documentElement.childNodes:
        if node.nodeType != Node.ELEMENT_NODE or node.tagName != "Unit": continue
        unit = _document(node.toxml())
        address = _field(unit, "Address")
        if not address.isdecimal() or not 0 <= int(address) <= 255 or int(address) in addresses:
            raise ValueError("Database contains invalid or duplicate unit addresses")
        addresses.add(int(address))
        raw = _field(unit, "SerialNumber")
        if not raw: continue
        serial = parse_native_serial(raw)
        if serial.known and serial.canonical == plan.serial:
            matches.append((int(address), _field(unit, "UnitType"), _field(unit, "FirmwareVersion")))
    if matches != [(target, plan.unit_type, plan.firmware)]:
        raise ValueError("Expected serial must match exactly one database unit at the destination, with the same type and firmware")


class SerialCommissioning(PhysicalAddressing):
    @staticmethod
    def _paths(source, new_address):
        source, project, number, old = _path(source)
        new = int(_address(new_address))
        if not SerialCommissionPlan._allowed_addresses(old, new):
            raise ValueError("Serial commissioning requires source255 and a destination in 2..254")
        network = f"//{project}/{number}"
        return source, network + "/p/" + str(new), network, old, new

    def plan(self, source, new_address, *, expected_serial):
        baseline = super().plan(source, new_address, expected_serial=expected_serial)
        plan = SerialCommissionPlan(**{field.name: getattr(baseline, field.name) for field in fields(baseline)})
        _database_target(plan)
        return plan

    def verify(self, plan):
        if type(plan) is not SerialCommissionPlan: raise ValueError("Expected a SerialCommissionPlan")
        _database_target(plan)
        return super().verify(plan)

    def apply(self, plan):
        if type(plan) is not SerialCommissionPlan: raise ValueError("Expected a SerialCommissionPlan")
        metadata = {"method": SerialCommissionPlan.METHOD, "native_operation": "set_address",
                    "native_scope": "explicit_destination",
                    "command": "SET " + plan.source + " Address " + plan.destination.rsplit("/", 1)[1]}
        try:
            return {**super().apply(plan), **metadata}
        except PhysicalAddressUncertain as error:
            details = {**error.details, **metadata}
            raise PhysicalAddressUncertain("Serial commissioning outcome requires observation; the write was not replayed", details) from error

    def commission(self, source, new_address, *, expected_serial):
        return self.apply(self.plan(source, new_address, expected_serial=expected_serial))
