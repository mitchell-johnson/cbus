# Physical eDLT USB DFU acceptance runbook

This runbook prepares the physical acceptance for issues #65 (P10.02, complete
USB transfer and re-enumeration) and #66 (P10.03, interruption, bootloader
recovery and explicit resume). No run has taken place, and the fixture
`fixture:usb:edlt-dfu-bootloader` in
[hardware-fixture-matrix.json](../research/hardware-fixture-matrix.json)
remains `unavailable`. Fake-USB and memory-peer results
([usb-dfu.md](usb-dfu.md), [firmware-update-recovery.md](firmware-update-recovery.md))
are development evidence only.

## Fixture

| Item | Requirement |
| --- | --- |
| Device | A **disposable** eDLT (KEYGL5) unit whose variant is known from `firmware identify` in application mode. It must not be a site unit or the production network's interface. |
| Host | An owned macOS or Linux runner labelled `cbus-hardware`, with libusb 1.0 and `pyusb==1.3.1` (`usb` extra). No vendor driver is installed or changed by the tool. |
| Package | An original `eDLTFirmware_<version>.zip` package and its password file, stored privately. They must never be committed. |
| Power | A switchable supply for the unit, so power loss and a power cycle can be applied and observed. |
| Isolation | The unit is powered from an isolated C-Bus segment or bench supply. Do not use the production CNI (192.168.1.21) or LAN discovery. |

## Private manifest

Copy [hardware-usb-dfu.template.json](../research/release-gates/hardware-usb-dfu.template.json)
to a private path. Point `CBUS_HARDWARE_GATE_MANIFEST` at the copy. Keep every
value in the protected `cbus-hardware` environment:

| Variable | Kind | Value |
| --- | --- | --- |
| `CBUS_HARDWARE_ACCEPTANCE` | flag | `1` |
| `CBUS_USB_DFU_BUS`, `CBUS_USB_DFU_ADDRESS` | value | From `firmware usb-list` while the unit is in DFU mode |
| `CBUS_USB_DFU_SERIAL` | value | Exact USB serial from `firmware usb-inspect` |
| `CBUS_USB_DFU_DEVICE_DESCRIPTOR`, `CBUS_USB_DFU_CONFIGURATION_DESCRIPTOR` | file | Captured DFU-mode descriptor bytes, validated by `firmware dfu-descriptors` |
| `CBUS_USB_DFU_VARIANT` | value | `StellarisPCI`, `TivaPCI` or `TivaNCC` |
| `CBUS_USB_DFU_FLASH_SIZE`, `CBUS_USB_DFU_EXTERNAL_SIZE` | value | Geometry reported by `firmware usb-dfu-inspect` (internal, then `--external`) |
| `CBUS_EDLT_FIRMWARE_PACKAGE`, `CBUS_EDLT_PACKAGE_PASSWORD_FILE` | file | The private package and its password file |

`tests/test_firmware_update_faults.py` validates the template against
`research/release_gate.py`'s manifest schema. `make check-hardware` then
refuses a missing provision, dirty checkout, substituted wheel, zero-test
selection or skipped test.

## Automated steps (`tests/test_usb_dfu_physical.py`)

1. **Read-only identity**: USB inspection of the selected bus/address returns
   the expected serial and complete descriptors, without claiming the device.
2. **Complete transfer**: `run_update` with a fresh journal and `force_font`
   erases, programs and reads back the font and main stages. It requires every
   release to complete. A separate fresh-session `verify_device` readback then
   matches every image.
3. **Host abort and explicit resume**: a host-side process death is raised
   before the second main program block. The journal must show `in-progress`
   and main `write-sent`. `resume_update` must re-inspect, re-verify the font,
   restart main from erase and complete. A fresh-session readback must match.

## Manual steps and observables

Record each observation in private evidence (for example, photos, `usb-list`
JSON and journal copies) and keep only hashes in committed receipts.

| Step | Action | Required observable |
| --- | --- | --- |
| M1 | Enter DFU mode by the vendor procedure | `usb-list` shows exactly one 166A:0501 device, and `usb-inspect` matches the manifest serial and descriptors |
| M2 | After automated step 2, power-cycle the unit into application mode | `firmware identify` reports the package version and variant; for TivaNCC, also run `firmware ncc-versions` |
| M3 | Re-enter DFU mode and run `update-run`; unplug USB during the main write | The command exits 1 with `write-sent`; the journal is `interrupted`; nothing further is sent |
| M4 | Replug; the device may re-enumerate at a new address | `update-resume --address NEW` re-inspects, restarts main from erase and exits 0 |
| M5 | Repeat M3 by removing unit power during the external font erase | Journal `erase-sent`; resume restarts font from erase after power returns |
| M6 | Run resume against a different eDLT or with another serial | Refused as `identity-changed` or `device-unavailable`, with no erase |
| M7 | Final power cycle after a completed resume | Application mode identifies the package version, and the display renders |

## Abort criteria

Stop, keep the journal and evidence, and do not retry automatically when:

- `usb-list` shows zero or several candidate devices, or the serial or descriptors differ from the manifest;
- pre-inspection reports `variant-mismatch`, `geometry-changed` or any unexpected INFO geometry;
- a claim fails with BUSY or ACCESS (another process or driver owns the interface);
- after a power cycle, the unit neither enumerates in DFU mode nor starts its application;
- any readback mismatch occurs after a completed stage;
- the unit shows electrical faults, heat or display damage.

A completed gate is physical evidence for the selected unit, variant and
package only. It does not establish other variants, packages, Windows
`dfuprog` or driver behavior, or the original updater's behavior.
