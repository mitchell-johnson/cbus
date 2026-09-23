# Cached CSV projection: first original pilot

The single admitted Python 3.13 run captured all twelve prepared cases. Ten original calls returned normally. Two stopped at the deliberately denied owned storage provider; these are recorded partial phases, not successful original saves or CSV exports. The launcher reaped its one child with exit zero, empty stderr, and no cleanup or postcheck errors. No second original run, native storage, VM, registry, C-Gate or hardware operation occurred.

`original-pilot-v1/report.json` SHA256 is `4adac8a1633eaef408f301384d60aabda2ce5497ec403df80a8668170865f3a1`; its complete raw child capture is `d261344ed3b3c93e9790fc2bff171de9275706fbb43f591827e195348f011f0e`. The pre-execution archive SHA256 is `980d9fb35c2d5e04ed62771a6412b4cd8c1ca217f7478fc0583684031fec4d2e`. The independent host analysis reverified all 72 archived input entries against both before/after maps. It retains source, actual loaded runtime, original EXE, raw output and archive hashes in `analysis-v1/facts.json` (SHA256 `675dc95e029d9e87242cfd6e2bbdacdf683f95c1516fab2427d9500922fb1ccf`).

Execution used original x86 instructions under Unicorn 2.1.4 on macOS, with Capstone 5.0.7 and Python 3.13.14. The actual Unicorn library hash is `7207c8e3d7a63118fb0bca73e01816797fd51b1d8a39a4cbc7abfd562ee59c85`; Capstone is `016084c6e70d929249a2abb22f1afda95095294e6cd70f509964ffc54006bf94`. Their files and the actual interpreter hash were unchanged. Six separate host-only failure/file-admission tests passed on both Python 3.13 and 3.10; those checks did not execute original methods. This is not a fresh Python 3.10 original pilot.

## What the original instructions established

| Case family | Original result |
| --- | --- |
| Unknown supplied type; RELAY4 firmware 10 or 9.1 | Original factory selected `TCBusUnitGeneric`; no Area storage load; eight supplied groups marked as interaction groups. |
| RELAY4 4.4; lowercase relay4 with 0; RELAY4 with 9 | Original factory selected `TRELAY4`; two ordered `QuickGet` requests with `Parameter=AreaGroupAddress`; six interaction groups. The original max-channel method returns 4, while the interaction method uses at least 6. |
| Area loads 12 then 13 | The second original getter determines exported Area13. Final reference moves to group13, with its OID token and reference-list membership. |
| Invalid Area text | Original integer parsing uses fallback 255; cached group255 is selected. Raw text remains `invalid`; the Area reference is changed independently. |
| Missing group255 | The original lookup creates one group, sets address255 and `<Unused>`, requests one `GroupSave`, and only then installs the Area reference. The second getter reuses that retained group. |
| Missing group255, denied save | Group addition/address/tag have already happened. The first load and one save attempt are retained, but Area reference is still nil and CSV did not complete. No original exception unwind ran. |
| Address-only columns | Both Area loads and reference mutation still happen before producing the address-only row. Omitting the Area column does not omit its getter effects. |
| Denied first load | One load attempt; no group creation/save/reference change; no completed CSV row. |

The selected fields and all ten completed literal rows match the prewritten expectations. Cold relay Area reference state starts nil/unchanged; completed Area resolution marks the reference attribute changed, finishes with update count zero, and retains original object identity. All raw unit/group/attribute/reference snapshots and the ordered getter/storage/provider trace remain in the child report. The compact analysis omits raw byte blocks only because the raw report remains independently hash-linked.

## Scope boundary

The original builder/cache wrappers, firmware comparator, selected actual class VMT methods, Area group lookup/reference setters and CSV serializer executed unchanged within the explicit allowlist. Original full unit/group/Studio constructors, whole cached database deserialization, event publishers, storage backend and general class registration startup did not execute. Constructor returns, cached collection/attribute primitives, retained storage-agent responses and reference-list primitives were explicit bounded fixtures. The one declared registration, six source type/firmware patterns, one-unit/eight-group layout, cold Area reference and finite Area response sequences bound the proof.

Consequently this does not establish arbitrary project XML → original object equivalence or a read-only original Document Database action. The observed original row operation can mutate cached references and can request metadata persistence. A future offline adapter must report those dependencies rather than silently infer a missing group or call its output a complete native export.
