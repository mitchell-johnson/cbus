# eDLT Clear Dynamic Labels: original command and proposed bounded support

This is research evidence and a proposal, not a production mutation API. The original command is `LABEL CLEAREDLT <unit-object-identifier>`. It targets a physical eDLT object and sends one programming control with parameter `FF`, tag `43`, data `C1 EA`. A native `200 OK.` does **not** independently establish that labels were erased.

## Original frontend and native chain

The original `FrmBaseUnit.btnClearLabel_Click` calls `_unit.ClearEdltLabel()` and shows its success/failure dialog from the returned boolean. `CBusBaseUnit.ClearEdltLabel` passes `_strNetworkAddress + "/p/" + _strUnitAddress` to `CGateCommunicatorFactory.ClearEdltLabel`. The factory calls `connection.LabelClearEdlt` and returns whether its result status is `Succ`. The button is enabled only when `DatabaseUnit` is false. Database-dialog visibility can depend on a corresponding network unit, but visibility does not enable the action or redirect it to a database object.

Reflection against the unchanged `SharpCGateCommunicator.dll` proves that `CommandLabelClearEdlt.Prepare` produces the literal `[0] label clearedlt //OWNED/254/p/5`. The command has one address argument and no flags. The original response handler classifies code 200 as `Succ`, 300/600/408 as `Failed`, -1 as `InvalidRsp`, and timeout state as `Timeout` even when the response code is 200. It performs no subsequent label inspection.

Exact case-preserved Java TAR members provide the native chain:

- `LabelPrimaryCommand` registers `clearedlt` with `ky`.
- `ky` accepts one object identifier, resolves it through `Bk.a`, and processes every resolved object. An object must be an instance of `CBusEdlt`; otherwise the native result is 402. It contains no explicit firmware or catalog guard. A malformed address is 400; missing objects are 401. A broad identifier may therefore resolve multiple objects; a typed helper should restrict this to one complete unit path.
- `ky` creates `bk`, binds the object's network and request context, and passes its unit address with integers `{193,234}` (`C1 EA`).
- `bk` invokes `aV.a(unit,255,67,"C1EA",2)`, sends the command, and requires a completed nonnegative control response. Missing or negative acknowledgements become 408 `Control failed`.
- `aV` builds `\46<unit>0900A4FF43C1EA`. The `09 00` programming route is distinct from the ordinary CAL route. There is no application/group selector in this command.
- `aV` and `ct` accept a response with the expected source and `32FF43` prefix. `3BFF43` is negative. Neither the `C1EA` data nor the erased label contents are returned. The parser admits trailing content after the prefix. `aW.h(String)` checks packet header bits; it is not a checksum validator.

The command inherits the network's retry count and response-delay setting through `aW`; it does not force zero retries or a fixed response timeout. The probes explicitly set and read back `Retries=0` **after** network readiness and observed exactly one clear control per request.

## Independent literal wire and failure evidence

An owned synthetic network discovered unit 5 as `KEYGL5`, `Version=5.5.00`, serial `101183.1666`, `State=ok`. The separate `FirmwareVersion` property is an OEM field and is not the identity `Version` getter. No user network or physical hardware was opened.

| Case | Literal PCI wire or response | Native result |
| --- | --- | --- |
| First request | `\46050900A4FF43C1EAq\r` | One clear control |
| Normal reply | `q.860510010032FF43F0\r\n` | 200 |
| Subsequent request with cached header | `A4FF43C1EAr\r` | One clear control |
| Extra response bytes | `r.860510010032FF43DEADBEEFB8\r\n` | 200 |
| Negative response | `s.86051001003BFF43E7\r\n` | 408 |
| Wrong tag | `t.860510010032FF44EF\r\n` | 408 |
| Confirmation without reply | `u.` | 408 |
| Wrong source unit 4 | `v.860410010032FF43F1\r\n` | 408 |
| Wrong destination PCI 17 | `w.860511010032FF43EF\r\n` | 200 |
| Deliberately invalid checksum | `x.860510010032FF4300\r\n` | 200 |

Every probe deliberately left its owned label records unchanged, including every native-success case. This is direct negative evidence against treating 200 as proof of erasure. The malformed checksum case has `00` where the complete normal response requires `F0`; it was still accepted by this exact native path. These results are specific to this control and do not assert that all native readers have the same behavior.

Wrong-type unit 4 returned 402 without a clear control. A `/db//...` target returned 401 without a control; an extra argument returned 400 without a control. The [machine-readable report](edlt-label-clear-research.json) retains every reply, wire frame, unit identity, call count and artifact hash. The original preparation and response-state vectors, exact Java source members, bytecode disassembly and reproducible probes remain under ignored `research/runtime/edlt-clear-labels/`.

## Proposed next implementation

First implement an independent opt-in fixture with **per-unit** dynamic-label caches. The current simulator's network-wide `LabelState` cannot demonstrate erasure on one eDLT while preserving another unit's labels. The new fixture should keep its state separate and leave the existing simulator contract intact.

The fixture should recognize only the independently literal programming control `A4 FF 43 C1 EA` on declared eDLT units. It should carry explicit committed text, Unicode, icon and variant records for the target and another unit, plus distinguish those dynamic records from static text and PP memory. Which label kinds a real firmware clears, and whether language selection or incomplete transfer state also resets, remain unverified. Any such fixture clearing policy must be named and documented, not presented as inferred firmware behavior.

Required tests before enabling a typed helper:

1. Seed distinct unit caches, issue the actual native command, and independently inspect target and unaffected-unit state. Save, close and reload the fixture to verify its declared persistence policy; static labels and PP bytes remain unchanged.
2. Exercise explicit faults: acknowledge without clearing, clear without a reply, negative reply, wrong source/tag/destination, invalid checksum, and persistence failure. Receipt classification and observed fixture state must remain separate.
3. Validate the full saved fixture document, per-unit identity references and bounded records; atomically persist before issuing the normal acknowledgement. Preserve first interruptions and retain memory/disk/response uncertainty if persistence fails or is interrupted.
4. Exercise exact ordinary and repeated-header frames with independent literals. Reject unknown programming control words, unsupported unit profiles, invalid counts and ambiguous framing. No generic factory-default control is enabled.

A proposed typed API is `EdltDynamicLabelClear(client).plan(unit, *, expected_serial)` followed by `request(plan)`. The plan admits one complete physical `//project/network/p/unit` path and rejects `/db`, wildcards, groups and multi-object identifiers. It checks an already running, idle network; explicit `Retries=0`; a healthy single-unit identity from fresh native discovery; and the expected serial/type/version. The initial bounded profile can be KEYGL5/5.5.00, matching the proven fixture identity. Apply repeats the guards immediately before one request. It neither opens networks nor changes retry or synchronization settings implicitly.

The result vocabulary must distinguish `native_accepted`, `native_rejected` and `outcome_uncertain`. Fields should include the native reply, attempted command, identity evidence, `automatic_retries=0`, `labels_cleared_verified=false`, `label_persistence_verified=false` and `database_updated=false`. A transport failure or interruption after attempting the request preserves evidence and sends no retry or follow-up mutation. A complete negative native response still does not prove that no device-side effect occurred.

There is no evidenced readback operation here that inventories all physical eDLT dynamic labels. A database PP backup does not provide such an inventory, and no automatic rollback should be claimed. Resending known labels can be a separate explicit operation. Simulator persistence acceptance will establish only its declared fixture policy; it will not convert the native acknowledgement into physical-device verification.
