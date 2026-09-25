# Historical proposal: direct selected-serial movement coordinator

This document records the design contract that preceded the implemented bounded
coordinator. The current API, CLI, guards, journal, and acceptance limits are in
[Selected-serial commissioning with independent observations](pci-selected-serial.md).
The [serial-keyed fixture](serial-address-fixture.md) still provides independent
topology and persistence/fault checks. Future-tense statements below describe
the proposal at the time it was written and are retained as design history.

## First supported scope and preconditions

The narrow first case is one selected known serial among exactly two distinct
serials at source address 255, moving to an explicit currently empty nonlocal
address 2..254 on a wired network. Occupied targets, cycles, bridges, wireless,
local PCI movement and repeated identical serial identities are unsupported.
The co request has no source address field: it selects the serial network-wide.
Therefore a supplied source address alone cannot constrain its recipient.
The independent acceptance profile is KEYE1 2.5.00 with PC_CNIED 5.5.00. The
existing inventory reports serials, not an independently verified firmware/type
for each duplicate node; broader device compatibility must not be inferred from
that inventory or from the common request format.

The caller must provide the exact numeric-IP endpoint, local PCI address and
expected local PCI serial, source serial/address and destination. The process
must own exclusive access to the PCI and commissioning activity for the whole
workflow. A TCP connection or a Python process lock cannot prove that C-Gate,
another PCI, or another commissioning agent is inactive. An eventual API must
state this operational prerequisite explicitly; it cannot infer exclusivity
from an available socket.

Before a write, take a fresh full inventory using independently covered 0..255
MMI bookends and bounded per-address multi-response serial windows. Require:

* Complete, consistent collection with identical full MMI state vectors at
  both ends; known local serial at the specified PCI address and no MMI state 3.
* All present addresses have known serial responses; no serial appears at
  different addresses and no unexplained duplicate address exists.
* Source 255 contains exactly the two expected distinct serials; the selected
  serial appears only there. Record the other serial explicitly.
* Destination has state 0 in both complete MMI bookends and is absent from all
  observed serial identities. Reject cached/native partial-MMI absence.
* Fresh direct local parameter 66 RECALL returns exactly 05, with exact source,
  count, checksum and confirmation. First scope rejects all other values and
  does not change PCI options. Recheck local identity/options after the inventory
  close to transmission; reject any inconsistency without writing.

The proposed 05 precondition is a conservative scope restriction. Original
Unraveller attempts whole-byte 05/07 Local SAL changes using a cached Boolean,
ignores failure returns and does not read back its STORE. That does not prove a
hardware requirement or exact option-byte restoration. The separate exact
source audit is under `research/runtime/local-sal-audit/` and is pinned by the
codec evidence. Broader option handling needs an independently tested transaction.

## Transaction and outcome model

Suggested Python API names, not final signatures:

```python
plan = coordinator.observe_plan(serial=..., source=255, destination=6,
                                expected_local_serial=...)
result = coordinator.apply(plan)       # repeats all live preconditions
observation = coordinator.verify(plan) # read-only recovery; never sends co
```

A saved plan must include validated full initial inventory, expected exact
identity map, endpoint/local identity, timing limits, raw request, options
observation, format/version and source evidence references. Importing one must
validate every field, recompute expected changes and reject forged/inconsistent
plans. A plan file does not authorize reuse of stale observations. `apply` must
repeat live preconditions and reject a changed identity/state fingerprint.

The state sequence is `validated`, `before_observed`, `preconditions_checked`,
`write_attempted`, `receipt_collected`, `after_observed`, then an observation
outcome. A durable recovery record must exist before the write and retain the
complete plan. Recording `write_attempted` happens before invoking send, since
partial transmission can have an unknown result. The overall deadline includes
admission, connection, all read windows, transmission and verification; every
phase rechecks an absolute parent deadline before a new request.

Transmit exactly one literal co command via a fresh exclusive numeric-IP
session, with the selected serial and exact target plus the inner checksum and
optional separate SRCHK checksum. No protected address STORE, MATCHDB, fallback
destination, retry or automatic inverse operation is permitted. Capture the
entire bounded receipt window rather than returning after the first match.
Retain framing, confirmation and all received bytes; trailing partial data,
unexpected source, malformed/extra receipts and correlation conflicts remain
visible. Original wired co uses a 2000 ms response timeout and one attempt;
this is source evidence, not a guarantee that every physical delayed reply has
arrived by a deadline.

Every post-send result needs independent full inventory verification. A matched
receipt means only that the captured receipt matched the request. Even a PCI
rejection can follow a fixture persistence commit. A missing/wrong receipt can
accompany a real move. No receipt status establishes movement or non-movement.

Expected verification is the exact original serial/address map with only the
selected serial moved to the target. The other serial must remain at 255;
requiring the old address to be absent would be wrong for this case. Every
unrelated identity, local identity and relevant MMI state must remain consistent.
The selected serial must appear exactly once at the target and nowhere else.
Inspect full address sets and serial identities, not only source and target.
For the supported fixture vector, both source and target have state 2 after the
move; the full expected state vector differs only at the formerly empty target.

Return independent fields for receipt match, complete after-observation, exact
expected identity change, unexpected changes and timing. Suggested outcome
labels are `observed_expected_change`, `observed_unchanged`,
`observed_unexpected_change` and `uncertain`. Preserve both inventories regardless
of the label. An unchanged observation is not a guarantee against delayed
movement. Neither successful observation nor a fixture restart proves device
power-cycle persistence. Always report `atomic_observation: false` and
`firmware_persistence_verified: false`.

On transport failure or interruption after attempting send, close the session,
retain the original exception and complete evidence, and do no further I/O in
that call. The separate read-only `verify` path can gather recovery observations.
If a durable evidence update also fails, retain the first failure and attach the
best in-memory evidence. An inverse co is another physical operation that could
affect an unexpected node; it is never an automatic rollback.

## Required independent transport tests before implementation is exposed

* Literal peer checks ordinary/SRCHK request bytes, exactly one request and full
  capture timing. Split packets, same-read trailing fragments, late replies,
  wrong/missing confirmations, extra receipts and close failures retain evidence.
* Admission/deadline failures before sending produce no co; interruption during
  send/receipt/verification preserves the same exception object and recorded
  identities. No failure path replays or attempts rollback.
* Fixture proves move+reply, move+missing reply, no move+forged reply,
  wrong-source/serial receipt, unknown serial and persistence errors before and
  after atomic replacement. Restart and full serial inventories determine the
  actual fixture topology independently of receipt parsing.
* Changed source/local identity, hidden occupied target, missing MMI coverage,
  state 3, cross-address serial conflict, options other than fresh 05, changed
  late precondition, and changes during verification reject or remain uncertain.
* Preserve raw observations and exact expected-map differences in a bounded,
  validated recovery export/import format; run CLI recovery tests before exposing
  any mutation command.

Existing collectors are non-atomic. Identity swaps between reads, duplicate
physical units sharing an identical serial at the same address, analogue bus
collisions and concurrent topology changes cannot be eliminated by matching two
MMI vectors. This boundary must remain explicit in the eventual API and docs.
