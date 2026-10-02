# Additional database CSV source profiles

The current registry admits **214 of 262 statically registered Toolkit 1.18
unit types**, adding 88 types to the previous 126-type boundary. This is a
report projection boundary. It does not mean every firmware partition of
each admitted type is supported, or that full Toolkit parity is complete.
The [current registry receipt](../research/fixtures/toolkit-database-csv-completion-registry.json)
records every exact type, firmware range, selected class, agent and refusal.
The earlier 126-type receipt and its literal vectors remain historical.

The implementation follows read-only inspection of the pinned original
EXE/MAP bytes. The committed
[completion vector](../../rust/testdata/vectors/toolkit_database_csv_completion.json)
contains method hashes, addresses, concrete virtual-method bindings and
synthetic XML with literal CSV rows. Original instructions, vendor unit
specifications, native software, VM and physical hardware were not executed
to implement these profiles.

| Loader boundary | Report associations |
| --- | --- |
| BCNC4 inputs and classic PIR sensors | Four primary blocks, in stored order |
| Multisensors, ST7 light-level/multisensors, surface sensors, couplers, dynamic-label inputs | Eight blocks; each exact agent either uses primary only or its recorded secondary block mask |
| DIMDU/DIMPR A, bus-powered DIN outputs and fan controllers | Initialized channel count, using the corresponding prefix of `GroupAddress` |
| Architectural dimmers | Initialized channels, using `ChannelOutputGroup` |
| DIMPR12 through 1.9.02 | Twelve `GroupAddress` associations |
| DIMDD4/8 and F variants in their older partitions | Individual `Ch0GroupAddress` through the final initialized channel |
| RELAY1/2, DIMMER4 and AN_OUT4 | Six ordered logic-group associations; physical-channel logic masks do not change this report-manager order |
| Exact base-lifecycle PCI, power-supply, burden/cable and NCC classes | Fresh Unit group manager remains empty; all sixteen group columns are unavailable and Area is unused |

Class selection remains important. For example, DIMDD8 through 1.2.99 uses
the eight-channel loader, while 1.3.0 through 9 selects the NCC output class
with the verified empty fresh group manager. SENLL 2.0.01 through 9 uses the
ST7 input model, while its earlier TSENLL partition remains refused. DIMPR12
1.9.03 through 9 remains refused. The registry also retains factory gaps and
ambiguous-selection refusals rather than choosing a nearby class.

## Application identity and native snapshots

All newly admitted agents bind the original base `FormatCgApplication`
and both Application providers. Within the admitted decimal-byte input
grammar, an empty stored `Application` becomes `56 255`, and one address
becomes `address 255`. Application 255 is a real resolved Application object
here. It is not an unused null reference. Both objects must already exist
in a native snapshot, including when the Secondary Application column is
omitted. Missing Application or Group dependencies refuse the whole export;
the CLI does not perform the original manager's possible creation/save.

The native adapter accepts an explicit complete Installation snapshot or
one public `DBGETXML //PROJECT` reply. Project/network selections retain the
existing document-network and numeric Unit-address ordering; an explicit
Unit selection retains the caller's order. A late unsupported class,
missing secondary Application, missing channel Group, or malformed consumed
relay logic array prevents output creation. A lost snapshot reply fails
after one request, without retry or writes. Existing output files remain
protected by the public export command.

Stored nonempty group arrays may be shorter than the initialized count:
each absent tail element resolves to primary Group 255, which must exist.
Arrays are bounded to 32 stored elements; all tokens must be valid bytes.
These profiles require the consumed parameters explicitly and do not model
empty/missing native parameter defaults outside this admitted boundary.
Only resolved association rows are cached; the cached contract does not
claim to reconstruct physical-channel programming from relay masks.

## Cached JSON v4

`cbus-toolkit-database-cached-projection-v4` is the public cached contract
for these additional source profiles. It retains the Unit's ordered Group
identities, both authoritative Application identities, each Application's
complete Group membership, routing mask, and the existing Area-provider
observation records. Application identity is an emitted OID when available,
otherwise an exact qualified path. Identity collisions, duplicate addresses,
ambiguous memberships, a missing secondary identity, or mask/loader-order
disagreement are refused before modeled operations. Historical cached
v1-v3 family contracts keep their previous domains and serialization.

Input/output Area belongs to the primary Application even when every block
uses secondary routing. Existing Area byte addresses are supported. The
cached model preserves the two ordered Area loads and reference changes,
the explicit missing-255 save outcome, and stopping after a failed load or
save. Later outcomes are not consumed after an early stop; completed
projections reject an unnecessary save outcome. Native snapshots require
the existing Area Group and never invoke that modeled save. Generic
profiles have no Area provider and no group-save operation.

The original CSV serializer has a caught error row for a verified nil
Application provider. That static fact is preserved in the vector, but
these base-formatter profiles require both resolved providers and do not
admit a nil-secondary shortcut. All successful rows preserve the original
column order, quoting, serial formatting, unavailable markers, trailing
comma and UTF-8 CRLF framing.

48 types still have no admitted registration. Some admitted types also
retain refused firmware partitions. Thermostats, SHAC/NAC, bridges,
specialized scene, wireless gateway and other remaining loaders require
their own exact state/association recovery and acceptance work. Fresh
native GUI/cold-load and hardware acceptance remain open.
