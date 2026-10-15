"""Executable description of native ``NET UNRAVELUNIT`` address resolution.

Pure prediction over caller-supplied facts: the complete physical serial
inventory, the database serial/address mapping, the selected addresses and
the MATCHDB flag. It performs no scans or bus writes and makes no hardware,
bridge or persistence claim.

The rules are the ones observed from owned C-Gate 3.4.0 build 2001 against the
research ``UnravelBusFixture`` (``rust/testdata/fixtures/
native_cgate_unravel_cases.json``); tests replay every captured case:

* Selected addresses are scanned in ascending order.
* A healthy singleton at an ordinary address is left alone, even when MATCHDB
  places its serial elsewhere (so a two-unit swap is not resolved) or the
  serial is absent from the database.
* Address 255 is cleared. At another duplicated address one keeper remains:
  the local PCI at its own address; with MATCHDB the serial the database
  places there, otherwise none; without MATCHDB the numerically lowest serial.
* The other serials are processed in descending numeric serial order. With
  MATCHDB a serial with exactly one database address goes there. An occupied
  database address is first cleared by moving its single occupant to a free
  address. Everything else takes the lowest free address: not 0, 1 or 255,
  absent from both the network and the database, then absent from the
  network only.
* Native sends a selected-serial broadcast when the source address held more
  than one serial when scanned, otherwise the legacy protected address STORE.
* A two-link occupied-address chain is predicted: when the single occupant
  of a database target itself has an occupied single database target, the
  deeper occupant is cleared first (to free) and each link moves to its own
  database address in deepest-first order, preserving physical identity.
  When the occupant's own database target is vacant or absent, the occupant
  is displaced to the lowest free address, matching the observed native
  single-link captures. Longer cycles are refused.

``refusal`` names topologies outside that observed subset (for example an
occupied database target with several occupants, or a cyclic displacement
chain); they are not predicted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .serials import parse_native_serial

SELECTED_SERIAL = "selected_serial"
LEGACY_ADDRESS = "legacy_address"


def _serial_key(serial: str) -> tuple[int, int]:
    number = parse_native_serial(serial)
    if not number.known or number.canonical != serial:
        raise ValueError(f"Serial {serial!r} must be a known canonical native serial")
    return number.first, number.second


def _address(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an address in 0..255")
    return value


@dataclass(frozen=True)
class UnravelMove:
    serial: str
    source: int
    destination: int
    reason: str  # database_match | free_address | displacement
    native_method: str


@dataclass(frozen=True)
class UnravelPlan:
    moves: tuple[UnravelMove, ...]
    kept: tuple[tuple[int, str], ...]
    final: dict[str, int]
    refusal: str | None = None
    physical_comparison: str = "unassessed"
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {"moves": [move.__dict__.copy() for move in self.moves],
                "kept": [list(item) for item in self.kept], "final": dict(self.final),
                "refusal": self.refusal, "physical_comparison": self.physical_comparison}


def plan_unravel(physical: Mapping[int, Iterable[str]], database: Mapping[int, str | None], *,
                 selection: Iterable[int] | None = None, match_database: bool = False,
                 local_unit: int = 16, local_serial: str | None = None) -> UnravelPlan:
    """Predict the native final topology and move sequence.

    ``physical`` maps each present address to its serials (the local PCI
    included when ``local_serial`` is given). ``database`` maps database unit
    addresses to their serial, or ``None`` for a unit without one.
    """
    if type(match_database) is not bool:
        raise ValueError("match_database must be a Boolean")
    local_unit = _address(local_unit, "local_unit")
    network: dict[int, list[str]] = {}
    seen: set[str] = set()
    for address, serials in physical.items():
        address = _address(address, "physical address")
        values = list(serials)
        if not values:
            raise ValueError(f"Physical address {address} needs at least one serial")
        for serial in values:
            _serial_key(serial)
            if serial in seen:
                raise ValueError(f"Serial {serial} appears more than once")
            seen.add(serial)
        network[address] = sorted(values, key=_serial_key)
    if local_serial is not None and local_serial not in network.get(local_unit, ()):
        raise ValueError("local_serial must be present at local_unit")
    db_addresses: dict[str, list[int]] = {}
    for address, serial in database.items():
        address = _address(address, "database address")
        if serial is not None:
            _serial_key(serial)
            db_addresses.setdefault(serial, []).append(address)
    chosen = sorted(network) if selection is None else sorted(
        {_address(value, "selected address") for value in selection})

    location = {serial: address for address, serials in network.items() for serial in serials}
    occupants = {address: list(serials) for address, serials in network.items()}
    moves: list[UnravelMove] = []
    kept: list[tuple[int, str]] = []
    moved: set[str] = set()

    def free_address() -> int | None:
        for candidates in ((lambda a: a not in occupants and a not in database),
                           (lambda a: a not in occupants)):
            for candidate in range(2, 255):
                if candidate != local_unit and candidates(candidate):
                    return candidate
        return None

    def move(serial: str, destination: int, reason: str, method: str) -> None:
        source = location[serial]
        occupants[source].remove(serial)
        if not occupants[source]:
            del occupants[source]
        occupants.setdefault(destination, []).append(serial)
        location[serial] = destination
        moved.add(serial)
        moves.append(UnravelMove(serial, source, destination, reason, method))

    def plan(refusal: str) -> UnravelPlan:
        return UnravelPlan(tuple(moves), tuple(kept), dict(location), refusal)

    def db_single(serial: str, exclude: int) -> int | None:
        if not match_database:
            return None
        targets = db_addresses.get(serial, [])
        if len(targets) == 1 and targets[0] not in (0, 1, 255, exclude):
            return targets[0]
        return None

    def ensure_vacant(destination: int, serial_stack: tuple[str, ...],
                      addr_stack: tuple[int, ...]) -> str | None:
        """Clear a single-occupant database target, pushing chain moves.

        Returns a refusal string or ``None``. ``"several"`` is a sentinel for
        a multi-occupant target that the caller formats with serial context.
        When the occupant's own database target is itself occupied, it is
        cleared recursively first so each link lands on its own database
        address (deepest first). When it is vacant or absent the occupant
        goes to free, matching observed native single-link behavior.
        """
        if destination in addr_stack:
            return f"Database displacement chain is cyclic at address {destination}"
        blocking = occupants.get(destination, [])
        if not blocking:
            return None
        if len(blocking) > 1:
            return "several"
        occupant = blocking[0]
        if occupant in serial_stack:
            return f"Database displacement chain is cyclic at serial {occupant}"
        if occupant in moved:
            return f"Database address {destination} cannot be cleared unambiguously"
        own = db_single(occupant, location[occupant])
        if own is not None:
            if own == local_unit:
                return f"Database address {own} for {occupant} is the local PCI"
            if own in addr_stack:
                return f"Database displacement chain is cyclic at address {own}"
            occupying = occupants.get(own, [])
            if occupying:
                if len(occupying) > 1:
                    return f"Database address {own} for {occupant} holds several units"
                refusal = ensure_vacant(own, serial_stack + (occupant,), addr_stack + (destination,))
                if refusal is not None:
                    if refusal == "several":
                        return f"Database address {own} for {occupant} holds several units"
                    return refusal
                move(occupant, own, "displacement", LEGACY_ADDRESS)
                return None
        spare = free_address()
        if spare is None:
            return "No free address to displace the database target occupant"
        move(occupant, spare, "displacement", LEGACY_ADDRESS)
        return None

    for address in chosen:
        serials = list(occupants.get(address, ()))
        if not serials:
            continue
        if address != 255 and len(serials) == 1:
            kept.append((address, serials[0]))
            continue
        if address == local_unit and local_serial is not None:
            keeper = local_serial
        elif address == 255:
            keeper = None
        elif match_database:
            keeper = next((serial for serial in serials if db_addresses.get(serial) == [address]), None)
        else:
            keeper = serials[0]
        method = SELECTED_SERIAL if len(serials) > 1 else LEGACY_ADDRESS
        for serial in sorted((s for s in serials if s != keeper), key=_serial_key, reverse=True):
            target = db_addresses.get(serial, [])
            if match_database and len(target) == 1 and target[0] not in (0, 1, 255, address):
                destination = target[0]
                if destination == local_unit:
                    return plan(f"Database address {destination} for {serial} is the local PCI")
                refusal = ensure_vacant(destination, (serial,), (address,))
                if refusal is not None:
                    if refusal == "several":
                        return plan(f"Database address {destination} for {serial} holds several units")
                    return plan(refusal)
                move(serial, destination, "database_match", method)
                continue
            destination = free_address()
            if destination is None:
                return plan("No free unit address is available for unravel")
            move(serial, destination, "free_address", method)
        if keeper is not None:
            kept.append((address, keeper))
    return plan(None)
