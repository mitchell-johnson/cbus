# Journaled eDLT firmware update, faults and explicit resume

`cbus-toolkit firmware update-run` runs the DFU steps of a supported
[update plan](firmware-update-plan.md) on an eDLT that is already in USB DFU
mode. `firmware update-resume --journal` continues an interrupted run only
after checking the device again. Both commands live in
`src/cbus_toolkit/firmware_update_run.py`. This is development-stage code:
tests use the memory DFU peer, directly or through real PyUSB with a fake
claimed backend. No physical device has been updated (see
[usb-dfu-hardware-runbook.md](usb-dfu-hardware-runbook.md)).

```sh
cbus-toolkit firmware update-run eDLTFirmware_1.8.0.zip --variant TivaPCI \
  --package-password-file private/password --journal private/update.journal \
  --bus 1 --address 7 --expected-serial ABC123 \
  --device-descriptor device.bin --configuration-descriptor config.bin \
  --release-policy reset-first-alternate --flash-size 262144 --external-size 131072
cbus-toolkit firmware update-resume eDLTFirmware_1.8.0.zip --journal private/update.journal \
  --package-password-file private/password --bus 1 --address 9 \
  --device-descriptor device.bin --configuration-descriptor config.bin \
  --release-policy reset-first-alternate
```

The selectors are synthetic. The exit status is 0 only when every stage has
been verified by readback and every USB session has completed cleanup.

## Stages and safe boundaries

Each plan becomes ordered stages, and every stage starts at a safe boundary:

| Stage | Erase | Program and verify |
| --- | --- | --- |
| `font` (only when the plan installs fonts) | External flash from 0, using the plan's original erase length | Font image at external address 0 with full readback |
| `main` | Internal flash from the variant address, image length rounded up to 1024 bytes | Main image at the variant address with full readback |

The explicit main erase is a deliberate difference from the original updater,
which calls `dfuprog -b -a ADDR -r` and relies on the bootloader. Without it,
a partially programmed stage could not be restarted: the DFU peer rejects
programming over nonblank flash (`errPROG`). The mode switch (`-m`), target
reset (`-r`) and Tiva/NCC serial post-check are **not** sent. The operator
enters and leaves DFU mode.

Every operation uses a fresh enumeration, claim and DFU session, like each
original `dfuprog` process. Each session repeats the client's descriptor,
extension and INFO geometry checks. The client does not retry a mutation, and
the runner never repeats an operation.

Cleanup must finish before another operation starts. `cleanup_complete`,
`cleanup_error` and `releases` include cleanup performed after a failed USB
acquisition as well as release after a DFU operation. Acquisition failure
remains the primary error; a failed release or handle close is retained
separately, with no second cleanup or claim attempt. A successful transfer
with failed cleanup stops the run and preserves its verified stage.

## Pre-inspection and variant binding

Before any destructive request, `update-run`:

1. Refuses unsupported plans, missing or wrongly sized images, stages that do
   not fit the explicit `--flash-size`/`--external-size`, and a main image
   whose Cortex-M reset vector does not lie inside the image at the variant
   address (`refusal_kind=variant-mismatch`, before any USB access).
2. Inspects internal flash and, if there is a font stage, external flash. It
   requires the expected descriptors, USB serial and INFO geometry.

INFO's application start is the only variant observable in DFU mode.
`0x2000` means Stellaris/PCI and `0x4000` means Tiva. A mismatch returns
`variant-mismatch` with the reported geometry and creates no journal. Tiva/PCI
and Tiva/NCC report the same start, so this check cannot tell them apart.
Confirm that variant first with `firmware identify` in application mode.

## Journal

After pre-inspection and before the first erase, the runner exclusively creates
the journal (`O_EXCL`, file and directory fsync). An existing path is never
overwritten. Later updates use the checked atomic replacement from the
selected-serial and physical PP journals. Before replacing the file, the writer
proves the file still holds its last bytes. Each phase is written **before** the
request it describes:

| Phase | Meaning | Reported `stage_states` |
| --- | --- | --- |
| `pending` | Not started by this journal | untouched by this journal |
| `erase-sent` | Erase may have started | unknown: erase may be partial |
| `erased` | Erase completed and read back blank | erased and read back as blank |
| `write-sent` | Program may have started | unknown: image may be partial or unverified |
| `verified` | Complete byte-for-byte readback | image read back byte-for-byte |

`cbus-edlt-firmware-update-journal-v1` binds the package name, SHA-256 and
version, variant, font option, flash sizes, every stage's ranges and image
SHA-256, the device identity (USB serial and descriptor hashes) and both INFO
geometries. `attempt_id` is SHA-256 over that binding, so an edited binding is
rejected. It always records `send_may_have_occurred=true` and
`replay_authorized=false`. `history` is an append-only event list with
sequence continuity, as in `recovery_journal.py`. The status is `in-progress`,
`interrupted` (unknown outcome), `failed` (device-reported error) or `complete`.

A failed run stops at the first failed operation and reports `failed_stage`,
`failed_phase`, `stage_states`, every operation summary (including the DFU
client stage and `outcome_known`), each USB release outcome, `retried=false`
and `resume_required`. `images_verified` distinguishes completed image
readback from successful cleanup. If all images are verified but final release
fails, the journal remains `interrupted` with those stages `verified`.

A simulated host process death during a transfer leaves the last durable
phase with status `in-progress`, which is the state a real crash leaves. A
cleanup interruption after successful readback instead preserves that
completed phase and records `interrupted` when the journal can be written.
The original interruption is re-raised with transfer and release evidence.

## Resume

`update-resume` reads and validates the journal, then captures a bounded immutable
package snapshot and compares its SHA-256 with the journal's package binding
before opening an archive parser or decryption reader. It rebuilds the plan from
that admitted snapshot using the journal's variant and font option. It refuses without
device I/O if the journal is complete, malformed or tampered with, or if the
package, variant or images differ from the binding. After recording
`resume-started`, it:

1. Re-enumerates and re-inspects the device. It refuses (`resume-refused` is
   journaled; stage phases are unchanged) when the device is absent
   (`device-unavailable`), cannot be inspected (for example, a hung
   bootloader), reports a different variant, or has a different USB serial or
   descriptors (`identity-changed`) or geometry (`geometry-changed`). The USB
   address may change; `--expected-serial` defaults to the journal serial.
2. Reads back every stage that the journal marks `verified`. A mismatch changes
   that stage back to `pending`. An incomplete readback refuses the resume.
3. Restarts the first unverified stage, and every later one, **from erase**.
   It records `stage-restart` with the prior phase. A partial write is never
   continued, and a readback that was interrupted is never trusted, even if
   flash already holds the image.

After final-release failure with every stage verified, a resume only performs
fresh inspection and readback when the images still match. It sends no erase
or program request. A failed acquisition cleanup or re-verification release
stops that resume and retains the stage states and cleanup evidence.

Resume does not prove that an earlier process has exited. The USB claim fails
with BUSY when another process still owns the interface. Do not run resume
while the original process might still be alive.

`verify_device()` is the read-only equivalent of steps 1 and 2 for all stages.
The physical gate uses it for a fresh-session readback.

## Fault-injection matrix

`FaultInjectingPeer` in `dfu_simulator.py` wraps the independent memory peer.
It fires one fault at an exact observable point: ERASE command, program-stream
byte offset, readback-stream byte offset or Nth GETSTATUS. The effect is
`disconnect`, `power-loss`, `crash` (`SimulatedProcessDeath`) or `hang`
(GETSTATUS reports dfuDNBUSY until power is restored). It counts every command,
so the tests can prove that nothing was retried. `reenumerate()` models a
reconnect or power restoration and keeps flash.

`tests/test_firmware_update_faults.py` (16 tests, 6 offset subtests) asserts
device memory, the tool report and journal, and command counts for each case:

| Case | Device state asserted | Tool report | Resume |
| --- | --- | --- | --- |
| Wrong-variant device (INFO 0x2000, plan Tiva) | Unchanged hashes; no ERASE/PROGRAM | `variant-mismatch`, no journal | Not resumable |
| Wrong-variant or short image | No USB access | `variant-mismatch` / `image` | Not resumable |
| Existing journal path | No ERASE | `journal`, file unchanged | — |
| Interrupted external erase (half erased, disconnect) | First 64 KiB blank, rest old | `font`/`erase-sent`, one ERASE | Refused while absent, then restarts font from erase |
| Interrupted write at offsets 0, 17, 1023, 1024, 1124, last byte (power loss) | Exact prefix written, rest blank | `main`/`write-sent` | Re-verifies font and restarts main from erase |
| Interrupted readback | Flash holds the full image | `main`/`write-sent`, DFU stage `readback-data` | Main still restarted from erase |
| Bootloader timeout (hang after ERASE) | Old flash unchanged | Poll limit or deadline, `erase-sent` | Refused while hung; after a power cycle, completes |
| Host process death mid-write | Exact prefix written | Exception; journal `in-progress`, `write-sent` | New process resumes |
| Changed identity or variant on resume | No destructive request | `identity-changed` / `variant-mismatch` journaled | Original device then completes |
| Verified stage changed before resume | — | Re-verify mismatch at the exact address | Font restarted |
| Other package or tampered journal | No device access | `journal-binding-mismatch` / `UpdateJournalError` | — |
| Real PyUSB: disconnect, re-enumeration at a new address, then a different serial | Release failure reported; nothing sent while absent | `No such device` | Different serial is refused; same serial at the new address completes |
| CLI `update-run` then `update-resume` through fake PyUSB | Installed images | Exit 1, then 0 | Font restarted |

`tests/test_firmware_update_release.py` adds 14 tests for release failures at
each operation, initial and later acquisition cleanup, resume and read-only
verification cleanup, primary-error preservation, interruption receipts and
the CLI's nonzero exit after final release failure. They assert exact claim,
release and close counts alongside memory and journal state. These tests use
real PyUSB with the same mandatory fake backend and synthetic memory peer.

Run the matrix with:

```sh
PYTHONPATH=src:tests:. .venv/bin/python -m pytest -q tests/test_firmware_update_faults.py
```

## Limits

Package metadata and selected images now share immutable captured bytes.
Selected-image loading checks the reviewed package digest before parsing or
decryption and reproduces the plan's selection and steps. Resume additionally
checks the journal digest before its first package parser. A replacement already
present when capture occurs is rejected if it differs from the binding; replacing
the mutable filename after admission does not change the captured bytes used
by subsequent readers. These checks establish byte identity and archive integrity,
not vendor authenticity. See [firmware-package-snapshot.md](firmware-package-snapshot.md)
for the capture bounds, refusal boundary and focused regression selection.
Earlier batch reports retain the same-size replacement gap as a historical
finding; the cleanup matrix above alone does not validate its fix.

This is development evidence. The fault points follow the memory peer's
request model, not a measured bootloader. Real erase and program timing,
partial-block behavior after power loss, bootloader auto-erase, DETACH/reset,
driver re-enumeration, BUSY claims after a crash, and the Tiva/NCC post-check
remain unmodeled. No vendor payload has been installed. Physical acceptance
requires the hardware gate in
[usb-dfu-hardware-runbook.md](usb-dfu-hardware-runbook.md).
