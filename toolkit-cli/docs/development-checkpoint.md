# Development checkpoint

Updated **27 September 2026**. Target: **C-Bus Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001**.

## Current product state

The Python CLI is an active product with local project tools, typed C-Gate and PCI workflows, unit programming helpers, eDLT editors and diagnostics. It has not reached full Toolkit parity. The packaged ledger currently contains **38 areas: 17 implemented, 19 in progress and 2 pending**. `census_complete` is `false`, so `cbus-toolkit coverage --require-complete` exits nonzero by design.

`cbus-toolkit cgate exec` sends one raw command and `cbus-toolkit cgate run` sends a batch in one session. Together they can reach the command surface exposed by the selected native C-Gate, `cgate-mock` or embedded `cmqttd` service. That transport reach does not create a typed Toolkit workflow, reproduce Toolkit GUI state, prove native-server semantics, or verify a physical effect. Each typed workflow keeps its own validation and acceptance boundary.

The earlier planned cold database-report projection, thermostat unit load/save composition and bounded Windows registry observation are now implemented within the profiles documented in [implementation status](implementation-status.md). They are no longer listed as future work.

## Current source-tree verification

The current Python 3.13 gates were run from `toolkit-cli/` on 27 September 2026:

```sh
make check
make check-interop
```

`make check` completed with **2,379 passed, 275 skipped and 18,561 passing subtests**, with no failures or errors. The skips are explicit provisioning gates for vendor software or specifications, Windows, native services and hardware. `make check-interop` completed with **14 passed and one skipped** because the external vendor unit-specification tree was not provisioned.

This is the current source-tree checkpoint. It is not a zero-skip installed-wheel audit, a complete native C-Gate differential, or physical-hardware acceptance.

The most recent complete installed-wheel audit remains the **15 September 2026** frozen snapshot in [test-acceptance.json](test-acceptance.json): 1,725 tests on Python 3.13.14 and 1,725 on Python 3.10.20, with all 14 native gates enabled and no skips. It is retained as historical evidence and predates the current tree. Python 3.13 is now the only supported runtime, and a fresh complete wheel audit is still required after the remaining work is integrated.

## Accepted current additions

The live eDLT path now supports three related typed reads through the C-Gate service embedded in `cmqttd`:

- `cgate edlt-labels` reads the supported KEYGL5 5.5.00 static label image, brackets it with physical identity reads and reports transient dynamic-label observations separately.
- `cgate edlt-widget-groups` reads the synchronized cached 44-byte `WidgetGroups` mapping under a strict response contract.
- `cgate edlt-label-audit` joins one fresh inventory, the serial-bracketed 9,216-byte physical images, CRC-checked decoded labels and the cached mappings. It can create a tamper-checked baseline or compare `exact`, `configuration` and `labels` views.

The audit fails closed on missing or changed identity, membership, image or mapping evidence. It deliberately excludes dynamic-label traffic from fingerprints because those records are transient, recipient-unverified and incomplete. Its software checkpoint does not prove display rendering, an eDLT's dynamic-label cache, power-cycle persistence or an atomic multi-device snapshot. See [eDLT label audit](edlt-label-audit.md).

Other substantial accepted areas include guarded native thermostat scheduling composition, bounded Windows registry observation, native database CSV projection for the documented unit profiles, eDLT parent and SceneManager metadata composition, project and unit editing, commissioning helpers, route codecs, update diagnostics and the device-specific functions listed in [implementation status](implementation-status.md). The linked feature documents preserve the exact source, profile and backend limits.

## Remaining completion work

The remaining work has three separate acceptance layers:

1. **Executable census.** Finish mapping every relevant Toolkit help topic, control, workflow and observed undocumented behavior to an explicit implementation, exclusion or outstanding ledger entry. The existing 3,767-topic and 209-command index is source inventory, not completed workflow acceptance.
2. **Differential acceptance.** Compare every admitted remaining operation, control, error path and device/firmware variation with independent Toolkit behavior. Raw `cgate exec`/`run`, the Rust command inventory and tests against our own code do not close this gate.
3. **Hardware acceptance.** Verify real network and device effects for programming, protection, persistence, recovery, topology, display/control/audio behavior, USB and firmware across the supported profiles. Simulator and disposable-server passes cannot establish these effects.

The concrete implementation gaps include wireless learn/join and gateway mapping, broader relay/dimmer and sensor profiles, barcode-driven commissioning, project/topology documentation and print/image export, remaining navigation and controller-integration workflows, eDLT cache/dialog/full-form behavior, project-image-dependent labels, dynamic-label cache readback, and the untested device/firmware variants called out in the ledger tables.

After those gaps are integrated, build a fresh Python 3.13 wheel and rerun every required native gate with no skips. Retain failed runs and focused evidence separately so a broad pass never erases a known platform, server or hardware limitation.
