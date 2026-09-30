# Firmware failure and cancellation diagnostics

`firmware update-run` and `update-resume` now include bounded lifecycle
diagnostics on failure. Ordinary errors retain exit status 1; cancellation
retains status 130. The existing primary error remains unchanged.

The new `firmware_update_evidence` projection contains recognized operation
and stage names, transfer counters and hashes, release/close state and a
read-only validated journal snapshot. It omits identity, package/journal
bindings, history, raw bytes and USB traces. Backend error text is replaced
with fixed operation, release, close or timing labels; original attached
receipts remain intact. A snapshot is an observation and always reports
`replay_authorized=false` and `physical_device_verified=false`.

Journal reading retains the existing bounded, regular-file, nonblocking input
contract. A missing, malformed or interrupted journal becomes `snapshot_available=false`;
diagnostic failure never replaces the primary exception. This code acquires no
USB device, sends no traffic, mutates no journal and cannot resume an update.

Focused tests exercise actual CLI failure/cancellation with injected devices,
including transfer, release and persistence failures. The privacy regression
places secret-bearing 100,000-character Unicode messages in every exported
error field and checks the bounded projection. Immutable package admission,
real interrupted-journal guards, codec refusal and USB release regressions are
included in separate combined source/wheel acceptance. These tests do not
establish original updater, physical USB, bootloader or vendor payload parity.
