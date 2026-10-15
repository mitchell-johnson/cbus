"""Admit one verified legacy-address displacement link.

First slice of the approved P3.05 legacy sidecar design (Option A: a new KIND
alongside ``VerifiedMove``; additive and reversible). Multi-move schema
migration and admissibility-widening of the selected-serial lane are ruled
out. Single-journal chained tests and sequenced single-move journals cannot
work (no two admissible journals chain); this slice does not attempt chaining.
It adds ONE admissible legacy journal kind plus its admission test, which is
the prerequisite the chaining-impossibility proof demands.

A legacy journal proves a single ``ensure_vacant`` link from
``duplicate_resolution``: a non-255 singleton source moved with
``native_method="legacy_address"`` and ``reason="displacement"`` to a free
address (``displaced`` is ``None``), or onto an address vacated by the named
``displaced`` occupant (with a fresh-empty ``vacated`` re-proof). Chain
ordering for future slices travels in ``{chain_id, depth, displaced}``:
``depth == 0`` with no displaced occupant is the only free-destination shape;
``depth > 0`` must name the displaced occupant.

Guardrails (unchanged from the selected-serial lane): single-shot
semantics, journal-before-send with fsync durability, pre-I/O refusal,
read-only recovery, no replay (marker deletion makes the journal stale),
cooperating-process-only. This module performs no PCI, CNI or C-Bus I/O.

Intentional divergence: the attempt-identity domain is separate from the
selected-serial lane. Markers live in their own namespace
(``.cbus-legacy-address-attempt-sha256-{fingerprint}.json``) and the
fingerprint is SHA-256 over this lane's own canonical plan JSON
(``_json`` with sorted keys), not the Rust serde fingerprint bytes. No
canonicalization bridges the lanes; each lane refuses the other's files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

from .duplicate_resolution import LEGACY_ADDRESS
from .pci_selected_serial import MAX_JOURNAL_BYTES, _Journal, _json, _keys, _unique_pairs
from .serial_reconcile import ReconcileError  # serial_reconcile imports this module lazily, so no cycle.
from .serials import parse_native_serial


LEGACY_RESULT_FORMAT = "cbus-legacy-address-result-v1"
LEGACY_ATTEMPT_FORMAT = "cbus-legacy-address-attempt-v1"
LEGACY_PLAN_FORMAT = "cbus-legacy-address-plan-v1"
LEGACY_ATTEMPT_SCOPES = ("resolved_journal_directory", "operator_selected_attempt_store")

_LEGACY_PLAN_KEYS = ("format", "serial", "source", "destination", "endpoint", "local_unit",
                     "expected_local_serial", "reason", "native_method", "chain_id", "depth",
                     "displaced", "before", "expected_after")
_LEGACY_JOURNAL_KEYS = ("format", "operation", "state", "outcome", "plan", "before", "after", "vacated",
                        "journal", "attempt_identity", "receipt_matches_request", "attempt_recorded",
                        "attempt_durability_verified", "transport_invoked", "send_attempted",
                        "after_collection_complete", "expected_identity_change", "unexpected_changes",
                        "errors", "atomic_observation", "firmware_persistence_verified",
                        "physical_compatibility_verified", "exclusive_ownership_required",
                        "automatic_retries", "automatic_rollback", "database_updated", "deadline_scope")
_LEGACY_MARKER_KEYS = ("format", "operation", "attempt_id", "scope", "journal", "plan",
                       "send_may_have_occurred", "read_only_recovery_only")
# Fixed block parallel to serial_reconcile._FIXED for a completed expected change.
_LEGACY_FIXED = {"operation": "apply", "state": "after_observed", "outcome": "observed_expected_change",
                 "attempt_recorded": True, "attempt_durability_verified": True, "transport_invoked": True,
                 "send_attempted": True, "after_collection_complete": True, "expected_identity_change": True,
                 "unexpected_changes": [], "errors": [], "atomic_observation": False,
                 "firmware_persistence_verified": False, "physical_compatibility_verified": False,
                 "exclusive_ownership_required": True, "automatic_retries": 0, "automatic_rollback": False,
                 "database_updated": False, "deadline_scope": "transaction_after_validation_and_lock"}


def _read_bounded(path, limit):
    """Read one regular file without following a final symbolic link."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"{path} is not a regular file")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{path} exceeds its size bound")
    return raw


def _parse(raw, name):
    try:
        text = raw.decode("utf-8")
        return json.loads(text, object_pairs_hook=_unique_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON value")))
    except (UnicodeDecodeError, ValueError) as error:
        raise ReconcileError(f"{name} is not strict UTF-8 JSON: {error}") from error


def _legacy_fingerprint(plan):
    """Own fingerprint domain: SHA-256 over this lane's canonical plan JSON.

    Intentionally distinct from ``pci_selected_serial._canonical_fingerprint``
    (Rust serde bytes). The two lanes never share a marker.
    """
    return hashlib.sha256(_json(plan).encode("utf-8")).hexdigest()


def _address(value, name):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an address in 0..255")
    return value


def _canonical_serial(value, name):
    try:
        number = parse_native_serial(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a known canonical native serial: {error}") from error
    if not number.known or number.canonical != value:
        raise ValueError(f"{name} must be a known canonical native serial")
    return value


def _endpoint(value):
    _keys(value, ("host", "port"), "Legacy endpoint")
    if not isinstance(value["host"], str) or not value["host"]:
        raise ValueError("Legacy endpoint host must be a nonempty string")
    if type(value["port"]) is not int or not 1 <= value["port"] <= 65535:
        raise ValueError("Legacy endpoint port must be in 1..65535")
    return {"host": value["host"], "port": value["port"]}


def _normalize_inventory(value, name):
    """Validate a canned identity map and return its canonical form.

    Shape is ``{"identities": [{"address": int, "serials": [canonical]}]}``
    sorted by address. Summaries cannot supply absence: every present address
    appears exactly once with its full singleton serial list.
    """
    _json(value)  # Bound the evidence first, as the selected-serial proofs do.
    if type(value) is not dict or set(value) != {"identities"}:
        raise ValueError(f"{name} has unsupported or missing fields")
    rows = value["identities"]
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{name} needs at least one identity row")
    mapping: dict[int, list[str]] = {}
    for row in rows:
        _keys(row, ("address", "serials"), name + " row")
        address = _address(row["address"], name + " address")
        if address in mapping:
            raise ValueError(f"{name} lists address {address} twice")
        serials = row["serials"]
        if not isinstance(serials, list) or not serials:
            raise ValueError(f"{name} address {address} needs at least one serial")
        for serial in serials:
            _canonical_serial(serial, f"{name} address {address} serial")
        if len(set(serials)) != len(serials):
            raise ValueError(f"{name} address {address} repeats a serial")
        mapping[address] = sorted(serials, key=lambda s: tuple(map(int, s.split("."))))
    seen: set[str] = set()
    for serials in mapping.values():
        if seen.intersection(serials):
            raise ValueError(f"{name} shows a serial at multiple addresses")
        seen.update(serials)
    canonical = {"identities": [{"address": a, "serials": mapping[a]} for a in sorted(mapping)]}
    if _json(value) != _json(canonical):
        raise ValueError(f"{name} is not in canonical sorted form")
    return mapping


def _inventory_document(mapping):
    return {"identities": [{"address": a, "serials": list(mapping[a])} for a in sorted(mapping)]}


def _validate_legacy_plan(value):
    """Validate the embedded plan and return its canonical dict."""
    plan = json.loads(_json(value))  # Detach from caller objects; reject nonfinite data.
    _keys(plan, _LEGACY_PLAN_KEYS, "Legacy plan")
    if plan["format"] != LEGACY_PLAN_FORMAT:
        raise ValueError("Unsupported legacy-address plan")
    serial = _canonical_serial(plan["serial"], "Plan serial")
    source = _address(plan["source"], "Plan source")
    destination = _address(plan["destination"], "Plan destination")
    endpoint = _endpoint(plan["endpoint"])
    local = _address(plan["local_unit"], "Plan local_unit")
    expected_local = _canonical_serial(plan["expected_local_serial"], "Plan expected_local_serial")
    if plan["reason"] != "displacement":
        raise ValueError("Legacy sidecar admits only reason displacement")
    if plan["native_method"] != LEGACY_ADDRESS:
        raise ValueError(f"Legacy sidecar admits only native_method {LEGACY_ADDRESS!r}")
    chain_id = plan["chain_id"]
    if not isinstance(chain_id, str) or not chain_id or len(chain_id) > 128:
        raise ValueError("Plan chain_id must be a nonempty string of at most 128 characters")
    depth = plan["depth"]
    if type(depth) is not int or depth < 0:
        raise ValueError("Plan depth must be an integer >= 0")
    displaced = plan["displaced"]
    if displaced is not None:
        _canonical_serial(displaced, "Plan displaced")
        if displaced == serial:
            raise ValueError("Plan displaced must differ from the moved serial")
    # Chain-ordering linkage: only a depth-0 link may carry no displaced
    # occupant; any deeper link must name the occupant it vacates.
    if displaced is None and depth != 0:
        raise ValueError("A link with no displaced occupant must be depth 0")
    if depth > 0 and displaced is None:
        raise ValueError("A deeper chain link must name its displaced occupant")
    if source == 255:
        raise ValueError("Legacy source must be a non-255 singleton address")
    if source == destination:
        raise ValueError("Plan source and destination must differ")
    if source == local or destination == local:
        raise ValueError("Plan source and destination must differ from local_unit")
    for banned, name in ((0, "destination"), (1, "destination"), (255, "destination")):
        if destination == banned:
            raise ValueError(f"Plan {name} must be a free ordinary address, not {banned}")
    before = _normalize_inventory(plan["before"], "Plan before")
    expected_after = _normalize_inventory(plan["expected_after"], "Plan expected_after")
    # Non-255 singleton source evidence plus the pinned local PCI.
    if before.get(source) != [serial]:
        raise ValueError("Plan before must hold the moved serial as a singleton at source")
    if before.get(local) != [expected_local]:
        raise ValueError("Plan before must hold the pinned local serial at local_unit")
    # Occupied destination ONLY with displaced naming the observed occupant.
    if displaced is None:
        if destination in before:
            raise ValueError("Plan destination is occupied but no displaced occupant is named")
    elif before.get(destination) != [displaced]:
        raise ValueError("Plan displaced must name the observed singleton occupant at destination")
    # The expected map is exactly the one-link move applied to before.
    wanted = dict(before)
    del wanted[source]
    wanted[destination] = [serial]
    if expected_after != wanted:
        raise ValueError("Plan expected_after is not the single-link move applied to before")
    if expected_after.get(local) != [expected_local]:
        raise ValueError("Plan expected_after must keep the pinned local serial")
    return {"format": LEGACY_PLAN_FORMAT, "serial": serial, "source": source, "destination": destination,
            "endpoint": endpoint, "local_unit": local, "expected_local_serial": expected_local,
            "reason": "displacement", "native_method": LEGACY_ADDRESS, "chain_id": chain_id,
            "depth": depth, "displaced": displaced, "before": _inventory_document(before),
            "expected_after": _inventory_document(expected_after)}


@dataclass(frozen=True)
class VerifiedLegacyMove:
    """A journal-proven legacy displacement link; every field was rederived."""

    journal_path: str
    journal_sha256: str
    attempt_id: str
    attempt_identity: str
    serial: str
    source: int
    destination: int
    endpoint: dict
    local_unit: int
    receipt_matches_request: bool
    reason: str
    native_method: str
    chain_id: str
    depth: int
    displaced: str | None
    route: tuple = ()
    project_sha256: str | None = None
    source_network: int | None = None
    target_network: int | None = None

    def as_dict(self):
        return {"path": self.journal_path, "sha256": self.journal_sha256, "attempt_id": self.attempt_id,
                "attempt_identity": self.attempt_identity, "outcome": "observed_expected_change",
                "receipt_matches_request": self.receipt_matches_request, "reason": self.reason,
                "native_method": self.native_method, "chain_id": self.chain_id, "depth": self.depth,
                "displaced": self.displaced}

    def move(self):
        return {"serial": self.serial, "source": self.source, "destination": self.destination,
                "endpoint": dict(self.endpoint), "local_unit": self.local_unit, "reason": self.reason,
                "native_method": self.native_method, "chain_id": self.chain_id, "depth": self.depth,
                "displaced": self.displaced}


def verify_legacy_journal(path, raw=None, value=None):
    """Admit only a complete, internally consistent legacy displacement journal.

    Modeled line-for-line on ``serial_reconcile.verify_journal``: the fresh
    before inventory must equal the plan's, the local PCI pin must hold, the
    source must be a non-255 singleton, an occupied destination is admitted
    only with ``displaced`` naming its observed singleton occupant plus a
    fresh-empty ``vacated`` re-proof, and the after inventory must reparse to
    exactly the expected map. The own-namespace attempt marker must still
    exist and embed the same plan; deleting it authorizes a replay, which
    makes this journal stale. Performs no I/O beyond reading the two files.
    """
    path = Path(path)
    try:
        if raw is None:
            raw = _read_bounded(path, MAX_JOURNAL_BYTES)
    except (OSError, ValueError) as error:
        raise ReconcileError(f"Cannot read legacy-address journal: {error}") from error
    if value is None:
        value = _parse(raw, "Legacy-address journal")
    if not isinstance(value, dict):
        raise ReconcileError("Legacy-address journal must be a JSON object")
    if value.get("format") == LEGACY_ATTEMPT_FORMAT:
        raise ReconcileError("An attempt marker records only an uncertain attempt; reconcile a completed apply journal")
    if value.get("format") != LEGACY_RESULT_FORMAT:
        raise ReconcileError("Unsupported legacy-address journal format")
    try:
        plan = _validate_legacy_plan(value.get("plan"))
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReconcileError(f"Journal plan is invalid or tampered: {error}") from error
    try:
        _keys(value, _LEGACY_JOURNAL_KEYS, "Legacy journal")
    except ValueError as error:
        raise ReconcileError(f"Journal fields are unsupported or incomplete (pre-marker journals are unbound): {error}") from error
    if value["operation"] != "apply":
        raise ReconcileError("Reconciliation requires an apply journal")
    if value["state"] != "after_observed":
        raise ReconcileError(f"Journal is in progress or interrupted (state {value['state']!r}); verify it read-only first")
    if value["outcome"] != "observed_expected_change":
        raise ReconcileError(f"Journal outcome {value['outcome']!r} is not observed_expected_change")
    for key, wanted in _LEGACY_FIXED.items():
        if _json(value[key]) != _json(wanted):
            raise ReconcileError(f"Journal field {key} is inconsistent with a completed expected change")
    if _json(value["plan"]) != _json(plan):
        raise ReconcileError("Journal plan is not in canonical validated form")
    if value["receipt_matches_request"] is not False:
        raise ReconcileError("Legacy displacement carries no selected-serial receipt")
    try:
        before = _normalize_inventory(value["before"], "Journal before")
        if _json(value["before"]) != _json(plan["before"]):
            raise ValueError("fresh before inventory differs from the plan")
        after = _normalize_inventory(value["after"], "Journal after")
        if _json(value["after"]) != _json(plan["expected_after"]):
            raise ValueError("after inventory does not reparse to the expected identity map")
        vacated = value["vacated"]
        if plan["displaced"] is None:
            if vacated is not None:
                raise ValueError("a free-destination link carries no vacated re-proof")
        else:
            vacated_map = _normalize_inventory(vacated, "Journal vacated")
            wanted_vacated = dict(before)
            del wanted_vacated[plan["destination"]]
            if vacated_map != wanted_vacated:
                raise ValueError("vacated re-proof is not before with only the displaced occupant removed")
            if vacated_map.get(plan["source"]) != [plan["serial"]]:
                raise ValueError("vacated re-proof must still hold the mover at source")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReconcileError(f"Journal evidence is tampered or inconsistent: {error}") from error
    recorded = value["journal"]
    if not isinstance(recorded, dict) or set(recorded) != {"path"} or not isinstance(recorded["path"], str):
        raise ReconcileError("Journal location record is malformed")
    marker = value["attempt_identity"]
    fingerprint = _legacy_fingerprint(plan)
    if not isinstance(marker, str) or Path(marker).name != f".cbus-legacy-address-attempt-sha256-{fingerprint}.json":
        raise ReconcileError("Journal attempt identity does not name its plan's marker")
    try:
        marker_raw = _read_bounded(marker, MAX_JOURNAL_BYTES)
    except FileNotFoundError as error:
        raise ReconcileError("Attempt marker is missing; its deletion authorizes a replay, so this journal is stale") from error
    except (OSError, ValueError) as error:
        raise ReconcileError(f"Cannot read the attempt marker: {error}") from error
    record = _parse(marker_raw, "Attempt marker")
    try:
        _keys(record, _LEGACY_MARKER_KEYS, "Attempt marker")
        if record["format"] != LEGACY_ATTEMPT_FORMAT or record["attempt_id"] != "sha256:" + fingerprint:
            raise ValueError("marker ID differs from the journal plan")
        if (record["operation"] != "apply" or record["send_may_have_occurred"] is not True or
                record["read_only_recovery_only"] is not True or record["scope"] not in LEGACY_ATTEMPT_SCOPES):
            raise ValueError("marker envelope does not describe a read-only recovery-only apply attempt")
        if _json(_validate_legacy_plan(record["plan"])) != _json(plan):
            raise ValueError("marker embeds a different plan")
        written = Path(recorded["path"])
        if record["journal"] not in (recorded["path"], str(written.parent.resolve() / written.name)):
            raise ValueError("marker names a different journal")
        scope = (LEGACY_ATTEMPT_SCOPES[0] if Path(marker).parent.resolve() == Path(record["journal"]).parent.resolve()
                 else LEGACY_ATTEMPT_SCOPES[1])
        if record["scope"] != scope:
            raise ValueError("marker scope does not match its journal directory")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReconcileError(f"Attempt marker does not bind this journal (stale or tampered): {error}") from error
    return VerifiedLegacyMove(str(path.absolute()), hashlib.sha256(raw).hexdigest(), record["attempt_id"], marker,
                              plan["serial"], plan["source"], plan["destination"], dict(plan["endpoint"]),
                              plan["local_unit"], value["receipt_matches_request"], plan["reason"],
                              plan["native_method"], plan["chain_id"], plan["depth"], plan["displaced"])


LEGACY_RECORD_FORMAT = "cbus-legacy-reconcile-record-v1"
LEGACY_RECONCILE_RESULT_FORMAT = "cbus-legacy-reconcile-result-v1"
LEGACY_PHASES = ("physical_done", "db_pending", "db_done")
_LEGACY_RECORD_KEYS = ("format", "phase", "journal", "move", "database", "unit",
                       "before_sha256", "expected_sha256", "database_changed", "history",
                       "last_error", "rollback_errors", "bus_io_performed")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _legacy_db_digest(snapshot):
    """Content digest of a flat address->serial database snapshot."""
    canonical = {"identities": [{"address": a, "serials": [snapshot[a]]} for a in sorted(snapshot)]}
    return hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()


def _legacy_locate(snapshot, move):
    """Find the one database entry carrying the moved serial and classify it.

    ``snapshot`` is a flat ``{address: serial}`` mapping supplied by the
    database object. The destination must already be vacant: an
    occupied-destination physical link only reconciles once the displaced
    occupant is gone from the database (chain ordering travels in the
    journals, not in this single-link edit).
    """
    if type(snapshot) is not dict:
        raise ReconcileError("Legacy database snapshot must be an address->serial mapping")
    for address, serial in snapshot.items():
        if type(address) is not int or not 0 <= address <= 255:
            raise ReconcileError(f"Legacy database address {address!r} is not in 0..255")
        try:
            _canonical_serial(serial, "Database serial")
        except ValueError as error:
            raise ReconcileError(f"Legacy database holds a non-canonical serial: {error}") from error
    holders = [a for a, s in snapshot.items() if s == move.serial]
    if not holders:
        raise ReconcileError(f"Serial {move.serial} is not recorded in the database")
    if len(holders) > 1:
        raise ReconcileError(f"Serial {move.serial} is ambiguous in the database")
    address = holders[0]
    if address == move.source:
        position = "source"
    elif address == move.destination:
        position = "destination"
    else:
        raise ReconcileError(f"Database records serial {move.serial} at {address}, neither the journal source "
                             f"{move.source} nor destination {move.destination}; the journal or database is stale")
    if position == "source" and move.destination in snapshot:
        raise ReconcileError(f"Destination {move.destination} is occupied in the database; "
                             "reconcile the displaced occupant first")
    return {"address": address, "serial": move.serial}, position


class LegacyReconcileRecord:
    """Exclusive-create legacy reconciliation record with checked atomic updates.

    Own record namespace (``LEGACY_RECORD_FORMAT`` and a
    ``.reconcile-legacy.json`` suffix): the selected-serial lane never reads
    or writes these files. Durability travels through ``_Journal``: exclusive
    creation plus fsync of the file and its directory before any database
    mutation, then atomic fsynced replacements.
    """

    def __init__(self, path, value=None, raw=None):
        self.path = Path(path).absolute()
        self.value = value
        self.writer = _Journal(self.path)
        self.writer.expected = raw

    @classmethod
    def load(cls, path):
        try:
            raw = _read_bounded(path, MAX_JOURNAL_BYTES)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise ReconcileError(f"Cannot read legacy reconciliation record: {error}") from error
        value = _parse(raw, "Legacy reconciliation record")
        if (not isinstance(value, dict) or value.get("format") != LEGACY_RECORD_FORMAT or
                set(value) != set(_LEGACY_RECORD_KEYS) or value["phase"] not in LEGACY_PHASES or
                not isinstance(value["history"], list)):
            raise ReconcileError("Unsupported or malformed legacy reconciliation record")
        return cls(path, value, raw)

    def _write(self):
        self.writer.write(self.value)

    def create(self, value):
        try:
            self.value = value
            self._write()
        except FileExistsError as error:
            raise ReconcileError("A legacy reconciliation record was created concurrently; rerun to resume",
                                 record=str(self.path)) from error

    def advance(self, phase, **fields):
        self.value.update(fields)
        self.value["phase"] = phase
        self.value["history"].append({"phase": phase, "at": _now()})
        self._write()

    def mark_attempted(self):
        self.value["database_changed"] = None  # Unknown until verification.
        self.value["history"].append({"event": "database_write_attempted", "at": _now()})
        self._write()

    def fail(self, error, rollback_errors=()):
        self.value["last_error"] = {"type": type(error).__name__, "message": str(error)}
        self.value["rollback_errors"] = list(rollback_errors)
        self.value["history"].append({"event": "database_write_failed", "at": _now()})
        try:
            self._write()
        except BaseException as secondary:  # Keep the original failure visible.
            self.value["last_error"]["record_update_error"] = str(secondary)


def default_legacy_record_path(journal):
    """Record beside the journal with a legacy-only suffix (never shared)."""
    journal = Path(journal).absolute()
    return journal.with_name(journal.name + ".reconcile-legacy.json")


def _legacy_record(move, identity, unit, plan, phase):
    return {"format": LEGACY_RECORD_FORMAT, "phase": phase, "journal": move.as_dict(), "move": move.move(),
            "database": identity, "unit": {"address": unit["address"], "serial": unit["serial"]},
            "before_sha256": plan["before_sha256"] if plan else None,
            "expected_sha256": plan["expected_sha256"] if plan else None,
            "database_changed": False, "history": [{"phase": phase, "at": _now()}],
            "last_error": None, "rollback_errors": [], "bus_io_performed": False}


def reconcile_legacy_journal(journal, database, *, apply=False, record_path=None):
    """Plan (default) or apply one database reconciliation for a legacy link.

    ``journal`` is a legacy journal path (or a ``VerifiedLegacyMove`` whose
    path is re-verified from disk; its fields are never trusted). The journal
    is fully re-verified before any database I/O: a stale (deleted-marker) or
    tampered journal refuses without touching the database. No bus I/O is ever
    performed and no physical request is replayed; only the database object's
    ``snapshot``/``plan``/``apply`` methods run, and only after verification.

    The database object is a minimal mapping store (fake-friendly; real
    project-file binding is future work)::

        identity() -> JSON-comparable dict
        snapshot() -> {address: serial} (fresh read, no mutation)
        plan(unit, destination) -> {"before_sha256", "expected_sha256",
                                    "source_path", "destination_path"}
        apply(unit, destination, plan) -> None (database-only mutation)

    Ordering mirrors the selected-serial lane: a dry run writes nothing (no
    record file); an apply exclusively creates and fsyncs the record
    (``physical_done``), advances it to ``db_pending`` with a further fsync,
    and only then mutates the database. A rerun after ``db_done`` is a
    read-only no-op; a rerun after ``db_pending`` whose database already shows
    the expected digest completes read-only without calling ``apply`` again.
    Records use the legacy-only format and filename suffix, so neither lane
    canonicalizes or accepts the other's files.
    """
    journal_path = Path(journal.journal_path) if isinstance(journal, VerifiedLegacyMove) else Path(journal)
    # Pre-I/O refusal: verification touches only the journal and its marker.
    move = verify_legacy_journal(journal_path)
    for method in ("identity", "snapshot", "plan", "apply"):
        if not callable(getattr(database, method, None)):
            raise ReconcileError(f"Legacy database object lacks {method}()")
    try:
        identity = database.identity()
        _json(identity)
    except (ValueError, TypeError, AttributeError) as error:
        raise ReconcileError(f"Legacy database identity is not JSON data: {error}") from error
    record_path = Path(record_path).absolute() if record_path is not None else default_legacy_record_path(journal_path)
    record = LegacyReconcileRecord.load(record_path)
    if record is not None:
        value = record.value
        if value["journal"]["sha256"] != move.journal_sha256 or value["journal"]["attempt_id"] != move.attempt_id:
            raise ReconcileError("Journal changed after legacy reconciliation started (stale or tampered)",
                                 record=str(record.path))
        if _json(value["database"]) != _json(identity):
            raise ReconcileError("Legacy reconciliation record belongs to a different database",
                                 record=str(record.path), recorded=value["database"])
    result = {"format": LEGACY_RECONCILE_RESULT_FORMAT, "mode": "apply" if apply else "dry_run",
              "journal": move.as_dict(), "move": move.move(), "database": identity, "record": None,
              "database_changed": False, "bus_io_performed": False, "hardware_programmed": False}

    def finish(outcome, *, changed=False, extra=None):
        result.update(outcome=outcome, database_changed=changed, **(extra or {}))
        if record is not None:
            result["record"] = {"path": str(record.path), "phase": record.value["phase"]}
        return result

    if record is not None and record.value["phase"] == "db_done":
        # Read-only no-op: report whether the live database still matches.
        try:
            snapshot = database.snapshot()
            matches = _legacy_db_digest(snapshot) == record.value["expected_sha256"]
        except Exception:
            matches = None
        return finish("already_reconciled", extra={"current_database_matches_record": matches})
    try:
        snapshot = database.snapshot()
    except ReconcileError:
        raise
    except Exception as error:
        raise ReconcileError(f"Legacy database snapshot stopped: {error}") from error
    unit, position = _legacy_locate(snapshot, move)
    result["unit"] = dict(unit)
    current_digest = _legacy_db_digest(snapshot)
    if position == "destination":
        # Already moved: an interrupted earlier run (db_pending) or a database
        # that recorded the destination beforehand. Nothing is written to it.
        # The live snapshot already is the expected post-move image.
        expected_digest = current_digest
    else:
        expected_map = dict(snapshot)
        del expected_map[move.source]
        expected_map[move.destination] = move.serial
        expected_digest = _legacy_db_digest(expected_map)
    before_digest = current_digest
    if position == "destination":
        if record is not None and record.value["phase"] == "db_pending":
            if record.value["expected_sha256"] != _legacy_db_digest(snapshot):
                raise ReconcileError("Database unit is at the destination but differs from the planned move; "
                                     "resolve manually", record=str(record.path), phase="db_pending")
            if apply:
                record.advance("db_done", database_changed=True, last_error=None)
                return finish("resumed_complete", changed=True)
            return finish("resume_pending", changed=True)
        if not apply:
            return finish("database_already_matches")
        record = record or LegacyReconcileRecord(record_path)
        if record.value is None:
            record.create(_legacy_record(move, identity, unit,
                                         {"before_sha256": None, "expected_sha256": current_digest},
                                         "physical_done"))
        record.advance("db_done", database_changed=False, last_error=None)
        return finish("database_already_matches")
    try:
        plan = database.plan(dict(unit), move.destination)
    except ReconcileError:
        raise
    except Exception as error:
        raise ReconcileError(f"Legacy database plan stopped: {error}") from error
    if (not isinstance(plan, dict) or plan.get("before_sha256") != before_digest or
            plan.get("expected_sha256") != expected_digest):
        raise ReconcileError("Legacy database plan differs from the single-link move")
    result["plan"] = dict(plan)
    if record is not None and record.value["phase"] == "db_pending":
        if record.value["before_sha256"] != before_digest:
            raise ReconcileError("Database changed while legacy reconciliation was pending; resolve manually",
                                 record=str(record.path), phase="db_pending")
        if record.value["expected_sha256"] != expected_digest:
            raise ReconcileError("Fresh legacy retry differs from the bound single-link candidate")
    if not apply:
        return finish("planned")
    if record is None:
        record = LegacyReconcileRecord(record_path)
        record.create(_legacy_record(move, identity, unit, plan, "physical_done"))
    elif record.value["phase"] == "physical_done":
        # No database write was marked; bind the record to the fresh plan.
        record.value.update(before_sha256=plan["before_sha256"], expected_sha256=plan["expected_sha256"])
        record._write()
    try:
        # Journal-before-send ordering: the db_pending intent is durably
        # fsynced before the single database mutation below.
        if record.value["phase"] == "physical_done":
            record.advance("db_pending")
        record.mark_attempted()
        database.apply(dict(unit), move.destination, dict(plan))
    except ReconcileError as error:
        if record.value["phase"] == "db_pending" and record.value["last_error"] is None:
            record.fail(error)
        raise
    except Exception as error:
        record.fail(error)
        raise ReconcileError(f"Legacy database move stopped: {error}; reconciliation remains {record.value['phase']}",
                             record=str(record.path), phase=record.value["phase"]) from error
    try:
        reloaded = database.snapshot()
    except Exception as error:
        record.fail(error)
        raise ReconcileError(f"Legacy database reload stopped: {error}") from error
    if _legacy_db_digest(reloaded) != expected_digest:
        failure = ReconcileError("Reloaded legacy database differs from the planned move")
        record.fail(failure)
        raise failure
    record.advance("db_done", database_changed=True, last_error=None)
    return finish("reconciled", changed=True)
