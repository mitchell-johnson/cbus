# Native catalogue acceptance

The reference is Schneider Electric C-Gate **3.4.0 build 2001** extracted from the supplied Toolkit installer. These checks exercise native unit specifications and Python programming-session wrappers in disposable projects. They do not establish hardware programming, every possible parameter value, every firmware version between catalogue boundaries, or full Toolkit parity.

The original `cbusunits.xml` contains **577 Unit entries and 3,750 Revision entries**. Its 576 declared-default revisions produce **575 distinct `(UnitType, selected firmware, CatalogNumber)` cases** after deduplication. The default selection uses each revision's minimum firmware. Four Unit entries have no declared default; three have multiple declared defaults. Their exact source indices and revision ranges remain in the report. Missing defaults are not assumed successful.

| Default-revision check | Cases | Parameter comparisons |
|---|---:|---:|
| `PP NEW` → export → reset → import → exact comparison | 548 pass | 39,292 |
| Reproducible native `PP NEW` rejection | 22 | No pass recorded |
| Native `PP NEW` cannot represent spaced UnitType | 5 | No pass recorded |
| Not run | 0 | — |

A second, independent check creates only the unit's database metadata, then uses `/db` `PP LOAD` → reset defaults → export → reset/import. **23 of the 27 original exclusions pass this alternative**, with **8,872 additional exact parameter comparisons**. Original `PP NEW` failures remain unchanged in the first report. Together these two distinct workflows verify an offline round trip for 571 of the 575 selected cases.

| Original exclusion | Cases | Catalogue status and diagnosis | `/db` alternative |
|---|---:|---|---|
| KEYGL5 / `KEYGL5.xml`, firmware 5.5.00 | 5 | Real addressable eDLT units; native default write at address 4,352 exceeds `PP NEW`'s 2,048-byte allocation | 5 pass, 874 parameters each |
| DMXDO12 / `DMXDO12.xml`, firmware 1.0.00 | 2 | Real addressable DMX gateways; native default write at address 2,048 exceeds allocation | 2 pass, 61 parameters each |
| DIMAR3 / `DIMAR3.xml`, firmware 0.0.1 or 1.0.00 | 4 | Real addressable architectural dimmers; inherited default write at address 2,304 exceeds allocation | 4 pass, 395 parameters each |
| DIMAR6 / `DIMAR6.xml`, firmware 1.0.00 | 4 | Same allocation defect | 4 pass, 395 parameters each |
| DIMAR12 / `DIMAR12.xml`, firmware 0.0.1 or 1.0.00 | 3 | Same allocation defect | 3 pass, 395 parameters each |
| WTXU 2FL, WTXU 6FL, NEOI 1FL, NEOI 4FL, NEOI HHR / `WTXU.xml`, firmware 0 | 5 | Vendor-declared non-addressable remote controls; `PP NEW` splits their internal spaces | 5 pass, 7 parameters each; still not evidence of physical programming |
| BURDEN, XC100B, XC305B / missing `DUMMY.xml`, firmware 0 | 3 | Non-addressable hardware burden and 100 m / 305 m cable catalogue entries | Missing specification; no pass |
| KEYBOARD / no specification, firmware 0 | 1 | Hidden `{unknown}` catalogue entry (`HideInCatalog=true`) | No specification; no pass |

The allocation diagnosis combines the oracle's `ArrayIndexOutOfBoundsException` events with the native `lP` implementation. Its constructor allocates 2,048 bytes. `PP NEW` applies defaults without the page-count adjustment performed by `PP LOAD`; the latter obtains `CBusUnitSpecification.getPPPageCountOverride` and resizes memory before using the schema. The alternate checks use this existing vendor path without changing vendor files.

`LOAD_FROM_FILE` does not provide a complete substitute. eDLT, DMX and architectural specifications still trigger the allocation failure. `WTXU.xml` returns `200` for loading but then `PP GET *` returns `460 Parameter not found`: the native handler applies defaults without assigning a usable session schema. `DUMMY.xml` is absent. No initial `200` response is counted as a successful workflow.

The completed minimum-and-maximum boundary run executed **all 6,497 distinct cases** across all 3,750 revisions. **6,382 passed**, with **552,391 exact parameter comparisons**. The remaining 115 are 95 native internal errors, 10 missing-specification rejections, and 10 spaced-UnitType command limitations. There were **zero client validation, transport, cleanup or comparison failures, and zero unrun cases**. This selection covers endpoints, not the firmware continuum.

The 95 native internal errors affect KEYGL5 (60 cases), DMXDO12 (6), DIMAR3 (10), DIMAR6 (12), and DIMAR12 (7). Missing specifications affect KEYBOARD (2), TOUCHA (2), and the three DUMMY catalogue entries (6). The five spaced remote-control UnitTypes each contribute two endpoints.

A separate alternate database run tested all 115 excluded endpoints. **105 pass** `/db` LOAD → reset → export → reset/import, with **64,331 additional exact comparisons**. Together the original and alternate workflows verify **6,487 of 6,497 selected endpoints**, with **616,722 parameter comparisons**. The original `PP NEW` outcomes remain unchanged. All ten remaining exclusions are native missing specifications:

| UnitType | Catalogue number | Selected firmware | Native reason |
|---|---|---|---|
| KEYBOARD | `{unknown}` | 0, 9 | No unit specification; hidden catalogue entry |
| TOUCHA | `{unknown}` | 3, 9 | No unit specification; hidden catalogue entry |
| BURDEN | 5500BUR | 0, 9 | Missing `DUMMY.xml`; non-addressable burden |
| XC100B | 5005C100B | 0, 9 | Missing `DUMMY.xml`; non-addressable 100 m cable |
| XC305B | 5005C305B | 0, 9 | Missing `DUMMY.xml`; non-addressable 305 m cable |

The full results remain in `research/runtime/catalog-boundaries.json`; the durable, value-free rollup is [`catalog-acceptance-summary.json`](catalog-acceptance-summary.json).

The initial census also found 110 snapshot-import failures caused by the vendor name `EEPROM Checksum`. The fixed wrapper obtains its actual native schema, accepts only an aligned scalar 8-bit integer for this fallback, stages the declared byte with `PP SET_RAW_DATA`, and checks native readback. A real regression changes the byte from `0x00` to `0x72`, verifies adjacent bytes, resets it, and imports the snapshot to restore it. These cases now pass rather than being silently skipped.

Reproduce from `toolkit-cli` with an explicitly selected disposable C-Gate server:

```sh
.venv/bin/python research/verify_catalog.py --host 127.0.0.1
.venv/bin/python research/verify_catalog.py --host 127.0.0.1 --resume
.venv/bin/python research/verify_catalog.py --host 127.0.0.1 --all-revisions --boundaries --limit 0 --output research/runtime/catalog-boundaries.json
.venv/bin/python research/verify_catalog_parallel.py --host 127.0.0.1 --output research/runtime/catalog-boundaries.json --jobs 4
.venv/bin/python research/diagnose_catalog.py --host 127.0.0.1
.venv/bin/python research/diagnose_catalog.py --host 127.0.0.1 --source research/runtime/catalog-boundaries.json --output research/runtime/catalog-boundary-diagnostics.json
.venv/bin/python research/summarize_catalog.py
```

`--filter`, `--limit`, `--resume` and explicit `--retry-failures` allow bounded or resumed checks. Parallel workers use independent programming sessions and separate new/closed CATTEST networks 250–253; results preserve per-run source hashes. The runner refuses unowned projects, rejects live or out-of-scope operations, never opens a network, and never retries an ambiguous transport failure. A nonzero acceptance exit status means at least one selected case failed or remains unrun.

The local JSON reports preserve exact source revisions, selected firmware, native greeting, Python/client source versions, response errors, command counts, parameter-state hashes, prior failed attempts and resumed runs. Vendor XML and decompiled implementation sources are not redistributed with this summary.

| Source | SHA-256 |
|---|---|
| Original `cbusunits.xml` | `c134c752fe4ef62a659c4480cd6702dffcc0096a59b4b0b336b5c383dbea6fe7` |
| Original `cgate.jar` | `3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630` |
| Local decompilation archive used for diagnosis | `fd81e4c41b4e29b9b82f351d34e9b02a9bbcd224c869b2b4451d075226f44c6e` |
| Default acceptance JSON | `6a6c11d7139f09e02ef16ab4d21c0e0574d95a70f61ed3dc00170ebf0cf2110b` |
| Alternate workflow diagnostic JSON | `f71dbc18290a48038fc57b960486dfb76799c738597c55390604fed61abad9a7` |
| Complete all-revision boundary JSON | `fbc6fb4a8bf74eca88110660c077bd0d65182f0b00e4736c7582621283568446` |
| Complete boundary alternative JSON | `f4a0e2479cfa2b30fda8c64ffd73217ed39e95d70da74f1631fa460ac476a904` |
