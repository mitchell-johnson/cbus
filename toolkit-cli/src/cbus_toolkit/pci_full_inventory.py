"""Read-only direct PCI inventory with full MMI observations before and after.

Every child request owns a fresh numeric-IP connection. This is a sequence of
bounded observations, not an atomic network snapshot or authority to write.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time

from .pci_inventory import MMIObservation, PCIMMICollector
from .pci_serials import PCISerialCollector, SerialObservation


@dataclass(frozen=True)
class PCIInventoryObservation:
    host: str
    port: int
    local_unit: int
    initial_mmi: MMIObservation | None
    final_mmi: MMIObservation | None
    serial_observations: tuple[SerialObservation, ...]
    planned_addresses: tuple[int, ...]
    phases: tuple[dict, ...]
    termination: str
    errors: tuple[str, ...]
    elapsed: float
    overall_timeout: float
    limits: dict

    @property
    def unattempted_addresses(self):
        attempted = {item.address for item in self.serial_observations}
        return tuple(address for address in self.planned_addresses if address not in attempted)

    @property
    def collection_complete(self):
        return (self.termination == "sequence_complete" and not self.errors and
                self.initial_mmi is not None and self.initial_mmi.complete and
                self.final_mmi is not None and self.final_mmi.complete and
                tuple(item.address for item in self.serial_observations) == self.planned_addresses and
                all(item.complete and item.connection_closed for item in self.serial_observations))

    @property
    def membership_unchanged(self):
        if not (self.initial_mmi and self.initial_mmi.complete and self.final_mmi and self.final_mmi.complete):
            return None
        return self.initial_mmi.states == self.final_mmi.states

    @property
    def changed_states(self):
        if self.membership_unchanged is None: return ()
        return tuple({"address": address, "before": before, "after": after}
                     for address, (before, after) in enumerate(zip(self.initial_mmi.states, self.final_mmi.states))
                     if before != after)

    @property
    def duplicate_addresses(self):
        return tuple(item.address for item in self.serial_observations if len(item.serials) > 1)

    @property
    def serial_conflicts(self):
        locations = {}
        for item in self.serial_observations:
            for serial in item.serials: locations.setdefault(serial, set()).add(item.address)
        return tuple({"serial": serial, "addresses": sorted(addresses)}
                     for serial, addresses in sorted(locations.items(), key=lambda item: tuple(map(int, item[0].split('.'))))
                     if len(addresses) > 1)

    @property
    def missing_serial_addresses(self):
        return tuple(item.address for item in self.serial_observations if item.complete and not item.serials)

    @property
    def error_addresses(self):
        return tuple(sorted({address for item in (self.initial_mmi, self.final_mmi)
                             if item is not None for address in item.error_addresses}))

    @property
    def consistent(self):
        return (self.collection_complete and self.membership_unchanged is True and
                not self.missing_serial_addresses and not self.serial_conflicts)

    @property
    def complete(self): return self.consistent

    @property
    def unique(self): return self.complete and not self.duplicate_addresses

    @property
    def mmi_healthy(self): return self.collection_complete and not self.error_addresses

    @property
    def healthy(self): return self.unique and self.mmi_healthy

    @property
    def status(self):
        if not self.collection_complete: return "incomplete"
        if not self.consistent: return "inconsistent"
        if self.error_addresses: return "mmi_errors"
        if self.duplicate_addresses: return "duplicate_address"
        return "complete"

    @property
    def observations(self):
        return ((self.initial_mmi,) if self.initial_mmi is not None else ()) + self.serial_observations + \
               ((self.final_mmi,) if self.final_mmi is not None else ())

    @property
    def request_count(self): return sum(bool(item.request) for item in self.observations)

    @property
    def connection_closed(self): return all(item.connection_closed for item in self.observations)

    def as_dict(self):
        return {"format": "cbus-pci-inventory-observation-v1", "endpoint": {"host": self.host, "port": self.port},
                "local_unit": self.local_unit, "status": self.status, "collection_complete": self.collection_complete,
                "membership_unchanged": self.membership_unchanged, "consistent": self.consistent,
                "complete": self.complete, "unique": self.unique, "healthy": self.healthy, "mmi_healthy": self.mmi_healthy,
                "initial_mmi": self.initial_mmi.as_dict() if self.initial_mmi is not None else None,
                "final_mmi": self.final_mmi.as_dict() if self.final_mmi is not None else None,
                "serial_observations": [item.as_dict() for item in self.serial_observations],
                "planned_addresses": list(self.planned_addresses), "unattempted_addresses": list(self.unattempted_addresses),
                "duplicate_addresses": list(self.duplicate_addresses), "serial_conflicts": list(self.serial_conflicts),
                "missing_serial_addresses": list(self.missing_serial_addresses), "changed_states": list(self.changed_states),
                "error_addresses": list(self.error_addresses), "termination": self.termination, "errors": list(self.errors),
                "timing": {"elapsed_seconds": self.elapsed, "overall_timeout_seconds": self.overall_timeout,
                           "phases": [dict(item) for item in self.phases]}, "limits": dict(self.limits),
                "request_count": self.request_count, "connection_closed": self.connection_closed,
                "connection_policy": "fresh_connection_per_observation", "scope": "standard_direct_install_mmi_and_identify4",
                "atomic_snapshot": False, "authorizes_address_mutation": False, "automatic_retries": 0,
                "physical_addresses_changed": False, "database_updated": False}


class PCIInventoryCollector:
    """Initial full MMI, one serial window per present address, final full MMI.

    The caller must exclusively own the configured endpoint for the entire
    sequence. Empty completed windows and duplicate known identities are
    retained; an incomplete child stops further requests. The total budget
    never shortens configured quiet/response/confirmation durations.
    """

    def __init__(self, host, port=10001, *, local_unit, overall_timeout=600.0,
                 observation_timeout=10.0, confirmation_timeout=2.0, response_timeout=5.5,
                 quiet_period=2.0, max_mmi_frames=7, max_serial_frames=7,
                 max_unrelated=64, max_bytes=65536, command_checksum=False):
        if (isinstance(overall_timeout, bool) or not isinstance(overall_timeout, (int, float)) or
                not math.isfinite(overall_timeout) or not 0 < overall_timeout <= 3600):
            raise ValueError("overall_timeout must be finite and in (0,3600] seconds")
        common = dict(local_unit=local_unit, overall_timeout=observation_timeout,
                      confirmation_timeout=confirmation_timeout, max_unrelated=max_unrelated,
                      max_bytes=max_bytes, command_checksum=command_checksum)
        # Constructors validate every child setting without opening a socket.
        mmi = PCIMMICollector(host, port, response_timeout=response_timeout, max_frames=max_mmi_frames, **common)
        serial = PCISerialCollector(host, port, quiet_period=quiet_period, max_frames=max_serial_frames, **common)
        self.host, self.port, self.local_unit = mmi.host, mmi.port, mmi.local_unit
        self.overall_timeout, self.observation_timeout = float(overall_timeout), mmi.overall_timeout
        self.confirmation_timeout, self.response_timeout, self.quiet_period = mmi.confirmation_timeout, mmi.response_timeout, serial.quiet_period
        self.max_mmi_frames, self.max_serial_frames = max_mmi_frames, max_serial_frames
        self.max_unrelated, self.max_bytes, self.command_checksum = max_unrelated, max_bytes, command_checksum
        self._lock, self._used, self.last_observation = threading.Lock(), False, None
        self._absolute_deadline = None  # Optional enclosing workflow budget; never extends this sequence.

    def _mmi_collector(self, timeout):
        return PCIMMICollector(self.host, self.port, local_unit=self.local_unit, overall_timeout=timeout,
            confirmation_timeout=self.confirmation_timeout, response_timeout=self.response_timeout,
            max_frames=self.max_mmi_frames, max_unrelated=self.max_unrelated, max_bytes=self.max_bytes,
            command_checksum=self.command_checksum)

    def _serial_collector(self, timeout):
        return PCISerialCollector(self.host, self.port, local_unit=self.local_unit, overall_timeout=timeout,
            confirmation_timeout=self.confirmation_timeout, quiet_period=self.quiet_period,
            max_frames=self.max_serial_frames, max_unrelated=self.max_unrelated, max_bytes=self.max_bytes,
            command_checksum=self.command_checksum)

    def collect_inventory(self):
        with self._lock:
            if self._used: raise RuntimeError("Inventory collector is one-shot; establish fresh transport ownership")
            if self._absolute_deadline is not None and (isinstance(self._absolute_deadline, bool) or
                    not isinstance(self._absolute_deadline, (int, float)) or not math.isfinite(self._absolute_deadline)):
                raise ValueError("Internal absolute inventory deadline must be finite")
            self._used = True
            return self._collect()

    def _collect(self):
        started = time.monotonic()
        last_clock = started
        deadline = started + self.overall_timeout
        if self._absolute_deadline is not None:
            deadline = min(deadline, self._absolute_deadline)
        initial, final, serials, planned, phases, errors = None, None, [], (), [], []
        termination, interruption = "collecting", None

        def read_clock():
            nonlocal last_clock
            last_clock = time.monotonic()
            return last_clock

        def observe(phase, address=None):
            nonlocal termination, initial, final, planned
            phase_started = read_clock()
            budget = min(self.observation_timeout, deadline - phase_started)
            is_mmi = address is None
            admissible = budget >= self.confirmation_timeout and (
                budget >= self.response_timeout if is_mmi else budget > self.quiet_period)
            if not admissible:
                termination = "overall_timeout"
                errors.append("Remaining overall budget cannot admit " + phase + " with its configured time bounds")
                return None
            child = self._mmi_collector(budget) if is_mmi else self._serial_collector(budget)
            # Construction and scheduling consume the same sequence budget.
            # Recheck admission and pass the absolute deadline so a child's
            # later start can never extend its allowed network I/O window.
            admitted = read_clock()
            budget = min(budget, deadline - admitted)
            admissible = budget >= self.confirmation_timeout and (
                budget >= self.response_timeout if is_mmi else budget > self.quiet_period)
            if not admissible:
                termination = "overall_timeout"
                errors.append("Remaining overall budget cannot admit " + phase + " after child construction")
                return None
            child.overall_timeout = budget
            child._absolute_deadline = deadline
            timing = {"phase": phase, "address": address, "started_after_seconds": phase_started-started,
                      "ended_after_seconds": None, "overall_timeout_seconds": budget}
            phases.append(timing)
            result = None
            try:
                result = child.collect_mmi() if is_mmi else child.collect_serials(address)
            finally:
                # Store evidence before reading the coordinator clock; a timing
                # interruption must not discard the child's completed replies.
                recorded = child.last_observation if child.last_observation is not None else result
                if recorded is not None:
                    if phase == "initial_mmi":
                        initial = recorded
                        if recorded.complete: planned = recorded.addresses
                    elif phase == "final_mmi": final = recorded
                    else: serials.append(recorded)
            timing["ended_after_seconds"] = read_clock() - started
            if last_clock >= deadline:
                termination = "overall_timeout"
                errors.append("Overall inventory deadline reached during " + phase)
            elif not result.complete or not result.connection_closed:
                termination = phase + "_incomplete"
                errors.append(phase + " observation ended with " + result.termination)
            return result

        try:
            observe("initial_mmi")
            if termination == "collecting":
                planned = initial.addresses
                for address in planned:
                    observe("serial", address)
                    if termination != "collecting": break
                if termination == "collecting": observe("final_mmi")
                if termination == "collecting": termination = "sequence_complete"
        except BaseException as error:
            interruption = error
            termination = "interrupted"
            errors.append(type(error).__name__ + ": " + str(error))
        try:
            read_clock()
        except BaseException as error:
            if interruption is None: interruption = error
            termination = "interrupted"
            errors.append("Final clock sample failed: " + type(error).__name__ + ": " + str(error))
        if termination == "sequence_complete" and last_clock >= deadline:
            termination = "overall_timeout"
            errors.append("Overall inventory deadline reached before observation completed")
        limits = dict(observation_timeout_seconds=self.observation_timeout, confirmation_timeout_seconds=self.confirmation_timeout,
            response_timeout_seconds=self.response_timeout, quiet_period_seconds=self.quiet_period,
            vendor_quiet_period=self.quiet_period == 2.0, max_mmi_frames=self.max_mmi_frames,
            max_serial_frames=self.max_serial_frames, max_unrelated=self.max_unrelated, max_bytes=self.max_bytes,
            maximum_requests=258, command_checksum=self.command_checksum)
        observation = PCIInventoryObservation(self.host, self.port, self.local_unit, initial, final,
            tuple(serials), planned, tuple(phases), termination, tuple(errors), last_clock-started, self.overall_timeout, limits)
        self.last_observation = observation
        if interruption is not None:
            try: interruption.pci_inventory_observation = observation.as_dict()
            except BaseException: pass
            raise interruption
        return observation
