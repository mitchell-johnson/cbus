# Issue #11 scaffold index (offline planning/validation scaffolds)

Spec-first offline scaffolds landed toward
[issue #11](https://github.com/mitchell-johnson/cbus/issues/11) boxes.
Each scaffold is pure offline logic (no I/O, endpoints, credentials, or
vendor data) with all behavioral/physical comparison slots starting
`unassessed`. **None of these establishes Toolkit parity or closes its
box**; each box's remainder needs device/firmware differential evidence
plus (where noted) hardware or vendor-gated acceptance.

| Box | Bead | Scaffold module | Tests | Remainder |
| --- | --- | --- | --- | --- |
| 1 device-dialog mapping | cbus-h22 | `device_dialogs.py`, `sensor_threshold_guard.py` | `test_device_dialogs.py`, `test_sensor_threshold_guard.py` | per-firmware valid/invalid/roundtrip mapping |
| 2 scan/unravel/commissioning/recovery | cbus-61h | `scan_topology.py`, `recovery_journal.py`, `duplicate_resolution.py` | `test_scan_topology.py`, `test_recovery_journal.py`, `test_duplicate_resolution.py` | general duplicates on live bus, occupied displacement, multi-bridge physical, hardware persistence |
| 3 scenes/macros/timers/relays/dimmers/triggers | cbus-0up | `relay_dimmer_logic.py`, `scene_sequence.py`, `timer_duration_guard.py`, `trigger_binding_guard.py` | `test_relay_dimmer_logic.py`, `test_scene_sequence.py`, `test_timer_duration_guard.py`, `test_trigger_binding_guard.py` | physical invocation, timing, learning, other profiles |
| 4 DLT/eDLT forms/labels | P-C/P-D (26c/8w7) | `form_save_order.py` + existing `edlt_*` | `test_form_save_order.py` + existing `test_edlt_*` | full form init/bindings, physical display/control |
| 5 templates/conversion | cbus-ws3 | `template_exchange.py`, `conversion_guard.py` | `test_template_exchange.py`, `test_conversion_guard.py` | vendor byte-compat, cross-type semantics, physical transfer |
| 7 project/docs/export/CGL | cbus-9me | `cgl_differential.py`, `topology_navigation.py` | `test_cgl_differential.py`, `test_topology_navigation.py` | vendor backup/restore equivalence, print/image fidelity, live routes |
| 8 thermostat/scheduling | cbus-9zz | `thermostat_settings_guard.py` | `test_thermostat_settings_guard.py` | dialog events, native order equivalence, physical behavior |
| 9 wireless learn/join | cbus-9zz | `wireless_commissioning.py` | `test_wireless_commissioning.py` | on-device learn/join, gateway transfer effects |
| 11 barcode scanner | cbus-9zz | `barcode_scanner.py` | `test_barcode_scanner.py` | vendor payload comparison, selection/creation acceptance |
| P-D auto-creation/bulk/labels | cbus-8w7 | `label_transfer_plan.py`, `scene_binding_plan.py` | `test_label_transfer_plan.py`, `test_scene_binding_plan.py` | bulk/global programming, physical transfer/invocation |
| P-E DLT variants | cbus-kxo | `dlt_variant_guard.py` | `test_dlt_variant_guard.py` | variant behavior, reset/factory physical, updater payloads |
| 10 C-Gate commands/events | cbus-pix | `event_stream.py` (offline filter/route/dedup) + Rust `cbus-cgate` (concurrent) | `test_event_stream.py` | remaining app/config commands, live monitoring streams |
| 6 eDLT firmware/USB | cbus-kxo | (concurrent `edlt_factory_default` work) | — | payload compat, bootloader, physical USB |
| 12 prefs/updates | cbus-9zz | (existing `toolkit_*update*`, `windows_*` modules) | existing | interactive user-context, trust/rollout/availability |
| 13 controller/PICED | cbus-ahr | `docs/external-boundaries.md` + `LOGIC_ENGINE_BOUNDARY` | (doc record; census evidence linked) | boundary changes need stated evidence first |
| 14 differential / 16 wheel gates | cbus-sb2/cbus-ahr | `evidence_audit.py` + `differential.py` matrix (concurrent) | `test_evidence_audit.py` + `test_differential_matrix.py` | per-op/error-path/firmware flips; live ledger currently 553 paths / 0 missing (presence ≠ acceptance) |
| 15 hardware acceptance | — | BLOCKED: no endpoint supplied | — | physical programming/protection/persistence/recovery |
| 16 fresh wheel | cbus-ahr | BLOCKED until ledger+census complete | — | installed-wheel 3.13 run, 14 gates, skip evidence |

Verification: `cbus-toolkit coverage --require-complete` still exits 1
(17 implemented / 19 in_progress / 2 pending, `census_complete: false`)
by design; these scaffolds intentionally flip no ledger status.
