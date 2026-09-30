# Native database conversion and persistent PP namespace

The Rust C-Gate service now keeps unit metadata and programming parameters in
separate namespaces. It also reproduces the captured database results of all
15 admitted C-Gate conversion pairs in both catalogue and move modes. The
Python programming client preserves successful native range-reset advisories.

This completes a bounded database conversion and persistence component, not
full Toolkit parity. The broad ledger remains 18/42 implemented categories;
the functional denominator is incomplete and zero obligations are fully
accepted. GitHub work item P5.06 remains open for the broader unit lifecycle.

## Completed behavior

- A scalar `UnitType`, `UnitName`, `UnitAddress` or `OID` can coexist with a
  differently valued PP entry of the same name. XML import, unit/project copy,
  project rename, address replacement, saved project images, archive tables
  and cmqttd restart preserve the independent values.
- PP LOAD resolves its schema from scalar identity, seeds only the declared
  parameters and defaults when a specification is present, and validates
  consumed numeric/string/sixbit input before replacing the active session.
  A failed load preserves the prior source, parameters and raw session image.
- Database PP SAVE replaces the complete staged parameter list in schema
  order, retiring unknown old entries while retaining scalar and bounded
  OutputChannel metadata. A schema-free local save uses deterministic name
  order. These statements concern database strings, not native byte-memory
  GET/SAVE normalization.
- CONVERTUNIT catalogue mode installs target catalogue identity and a fresh
  channel skeleton where declared; move mode retains destination identity and removes the
  source. Both use the recovered mapping table and target PP order, retain
  colliding metadata/PP names and survive save/close/load.
- The database loader emits the native `462-` reset-to-default advisory while
  returning success. The Python client accepts only that exact continued
  advisory on PP LOAD ending in 200, retains the original reply, and still
  rejects terminal errors, mixed error rows and unrelated 462 responses.

Private decoded specifications, their includes, the catalogue and conversion
mapping table are supplied by the operator. No vendor specifications are
distributed. Configure cmqttd with `--cgate-unitspec`; use the existing typed
CLI [conversion workflow](conversion.md) and inspect its backup and selected
database targets before applying a conversion.

## Native and Rust comparison

Fresh original C-Gate 3.4.0.2001 ran on owned IPv4 loopback listeners with
temporary closed projects. Both successful original runs had zero connections
to the counted conversion CNI, stable input bindings and verified terminal
cleanup. No Windows VM, original Toolkit form or physical C-Bus device ran.

The original capture covers 30 positive conversions, 15 refusal cases and one
bare-source boundary, plus a separate targeted run of two conversions, two
scalar/PP collision profiles, five absent-declared-parameter probes, twelve
integer grammar probes and an independent PP/OID import. The
[sanitized native evidence](acceptance/2026-10-01-conversion-pp/native-summary.json)
retains hashes and outcomes; full native XML and wire evidence remain private.
Earlier producer failures are retained separately from successful acceptance.

Each current Rust server imported the original preconversion XML and verified
its seed before CHECK/CONVERT. All **30/30 cases per server** match exact ordered
PP values, selected identity fields and non-OID channel metadata, then preserve
their own OIDs and values through save/close/load. Generated object identifiers
are excluded only from cross-server comparison. Mode 2 checks source removal.
The owned daemon PCI simulator is measured separately from the zero-connection
conversion CNI; simulated daemon startup traffic is not physical acceptance.

Fresh current-binary replays also preserve all 40 retained SESSION_ID exchanges
and all 28 retained direct/combined Unit XML comparisons. The command-contract
inventory, SESSION applicability decisions and packaged parity register are
regenerated from these receipts, retaining every unresolved acceptance axis.

## Validation and remaining work

Focused Rust checks cover namespace/order/failed-load preservation, conversion,
XML mapping, real daemon restart and MQTT continuity. There are 60 executed
test bodies, including one documentation binding check, plus two
vendor-provisioning early-return branches; those branches
are not vendor acceptance. Formatting, workspace Clippy with warnings denied,
and the release workspace build pass. No full local test suite ran.

Focused source and fresh installed-wheel validation each passed 119 distinct
normal tests and 66 subtest reports, with zero failures or skips. Seven
explicit native/binary opt-in methods were excluded before collection.
Actual import origins,
product/input hashes and the corrected initial stale-receipt failures are in
the [batch acceptance receipt](acceptance/2026-10-01-conversion-pp/acceptance.json).
Native and hardware opt-ins excluded before execution are listed independently.

Still outstanding:

- Native database memory normalization, masking and missing-byte GET/SAVE
  semantics across the full specification matrix. In the fresh original run,
  only one conversion failed LOAD; six other conversions loaded successfully
  but had individual GET failures. A short array LOAD success is not readback
  acceptance.
- Full arbitrary unit/channel metadata, extension and namespace shapes,
  cross-network/OID-targeted copy semantics, reset and vendor-template lifecycle.
- Original Toolkit interactive conversion/tweaker workflows, physical unit
  conversion, broad device/firmware acceptance and power-cycle persistence.
- Held classic DLT and Toolkit conversion extensions await their own review
  and integration. This batch does not incorporate or count those queues.

Older durable records that already lost a metadata-colliding PP value cannot
reconstruct it from scalar identity. Reimport an authoritative complete Unit
document to restore such a value; the legacy loader does not invent one.
