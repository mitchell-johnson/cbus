# eDLT preset restore controls

`edlt restore-levels-plan` and `cgate unit edlt-restore-levels` expose the
Toolkit 1.18 preset-level controls for KEYGL5 / 5055EDL firmware 5.5.00.
They run the explicit model load cycle, refresh the preset controls, make one
requested edit, and produce the original database save parameters and five CRCs.

```sh
cbus-toolkit edlt restore-levels-plan snapshot.json \
  --metadata restore-cache.json --widget 6 --level 128

cbus-toolkit cgate unit --lock-address //TEST/254 \
  --source /db//TEST/254/p/20 --dry-run edlt-restore-levels \
  --metadata restore-cache.json --widget 6 --level 128 --synchronise
```

Remove `--dry-run` to save the verified database result. The operation accepts
database destinations only. A native programming-session readback must match
every parameter before the CLI saves. It rejects a changed source snapshot or
altered plan, records interruptions without replay, and attempts rollback after
an ordinary write failure while the existing connection remains usable.

`--restore-mode preset|previous` and `--page-mode single|multiple` optionally
set those modes before the edit. Omitting widget and level inspects and saves
the model/control cycle without a slider edit. A supplied widget requires a
level; a level is an integer byte, 0..255. The tool rejects hidden controls,
duplicate-name representatives and edits while previous-level restore is selected.

There are exactly 16 constructed preset controls, corresponding to functional
widgets 6..21. Lighting, Shutter, Fan, Timer and Multi Level widgets with a
selected group can expose a control. Single-page mode exposes functional
widgets 6..10. The first control with a particular displayed application/group
name represents any later controls with that same text. Standby widgets have no
separate preset-level field or control.

The original change event has two distinct behaviors:

- An ordinary edit propagates to all constructed controls with the same exact
  `application name + " | " + group name` string. Duplicate names can couple
  different addresses or applications.
- `--synchronise` propagates to all 16 controls, including hidden, blank and
  otherwise ineligible controls. Setting the currently displayed value does
  not fire a change event and does not propagate.

During save, the original end-marker normalization can change a widget's type
and reset its restore level to zero. That reset takes precedence over the
control edit. Hidden widgets whose type stays unchanged retain the edited level.

## Explicit cache facts

The metadata file has format `cbus-edlt-restore-cache-v1` and contains:

```json
{
  "format": "cbus-edlt-restore-cache-v1",
  "lifecycle": {
    "format": "cbus-edlt-lifecycle-cache-v1",
    "applications": [56, 202, 203],
    "groups": [
      {"application": 56, "group": 42, "exists": true},
      {"application": 202, "group": 255, "exists": true}
    ]
  },
  "applications": [{"application": 56, "name": "Lighting"}],
  "groups": [{"application": 56, "group": 42, "name": "Kitchen"}]
}
```

This is a shape example, not a universal cache. Use
`edlt lifecycle-requirements snapshot.json` to enumerate the actual load-cycle
facts, including dynamic image and scene/action facts where required. Provide
the exact displayed names for every eligible restore group. Group addresses
must be unique within each application; duplicate display names are allowed
because the original controls use them for event coupling. The file is bounded
to 2 MiB; duplicate JSON keys and malformed cache records are rejected.

Unknown or absent binding groups are rejected. Their original getters can
change group, label, status and restore fields; that additional binding behavior
is outside this editor's current supported scope. Cached unused group 255 is a
distinct fact and produces no visible preset control. The CLI does not create
metadata or verify that supplied cache facts are fresh.

## Evidence and limits

The original Windows probe uses the unchanged Toolkit 1.18 logic model,
`eDLT.dll` controls, original binding order and the original private refresh
and change handlers. Its outer form is an uninitialized holder for those
handlers; the actual full `FrmBaseUnit` constructor is not invoked. It uses
owned model/cache objects and no physical network endpoint.

[Captured Windows vectors](../research/fixtures/edlt-restore-levels-windows-vectors.json)
contain 64 supported cases and 20 explicitly excluded observations. Supported
cases compare all 874 parameters in four phases, plus all 16 actual controls'
names, visibility and levels. Cases include all widget kinds, duplicate names,
page visibility, same-value and synchronized edits, mode changes, image-label
load effects, shared scene pointers, masked scene fields and MRA save propagation.
The captures retain original source, vendor, executable, input and output hashes.
They were collected independently of the Python editor.

The final combined suite passed **16 tests with zero skips** on Python
**3.13.14** (154.212 s) and **3.10.20** (152.113 s): ten pure tests, four CLI
tests, the independent captured-vector test, and the native matrix. The 64
supported captured cases compare **223,744 parameter values** and **1,024
actual control records** per run. The 20 exclusions remain separate observations,
not supported passes.

Each Python version also passed **15 fresh native cases** against the original
Windows controls. Every case compares all 874 fields after load, after controls,
before save and after CRC calculation, then verifies native staged values and
the complete state after **save, close and load for that case**. All five CRCs and
all 16 raw restore bytes at `0x1A0..0x1AF` are checked; those bytes are read again
after reload. This adds 78,660 parameter comparisons and 480 raw-byte comparisons
per run. Projects remain closed to physical networks (`state=new`) and are
removed afterward. The compact [acceptance record](../research/fixtures/edlt-restore-levels-acceptance.json)
contains exact source, fixture, vendor, executable and report hashes; full
backend/version-qualified transcripts remain under
`research/runtime/edlt-restore-levels/native-*`. Sources, the bridge, runner,
CLI and vector fixture were pinned before the final runs and checked unchanged.

The one-case composition pilot is retained with `complete_scope=false`; it does
not replace any final matrix case. Native testing uses the owned Windows x86
original-assembly bridge and macOS C-Gate 3.4.0 on loopback port 20033, never an
installed Toolkit session or physical unit.

The phase composition is intentionally limited to restore levels, page mode
and restore mode on unchanged loaded widget models. It preserves the lifecycle
plan's separately resolved scene objects and save result; it never reloads an
after-load parameter snapshot as though that snapshot represented all transient
model state. Application changes and other bound controls require additional
phase/state handling.

Full form initialization, missing-group normalization, programmatic edits of
hidden controls, out-of-range slider clamping, multi-edit form sessions and
physical power-cycle/mandatory preset transfer remain unverified or unsupported.
