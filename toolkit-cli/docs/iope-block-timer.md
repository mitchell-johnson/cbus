# IOPE Environment block timers

`cbus_toolkit.iope_block_timer.IopeBlockTimer` implements the duration and
four simple expiry-function selections reached from the Environment tab's
existing corridor/office timer buttons. It admits IOPE1R1, IOPE2R2 and IOPE2C4
at firmware 1.0.00..1.2.99 with their exact schemas and catalogue identity.

The standalone CLI family is `block-timer`:

```json
{
  "block": 4,
  "seconds": 300,
  "expiry": "off",
  "group_cache": {
    "format": "cbus-iope-environment-groups-v1",
    "source": "current same-network database group inventory",
    "applications": [{"address": 56, "groups": [10, 11, 12, 13, 14, 15, 16, 17]}]
  }
}
```

Supply the actual groups needed by the selected unit's Environment controls;
this example inventory is synthetic. The cache must include every referenced
input/master/join group, with application identity retained. Native database
application checks belong to the CLI wrapper. A bare editor caller must establish
the cache's freshness.

```sh
python -m cbus_toolkit.iope_workflow_cli block-timer plan pp.json --edits timer.json
```

The Python interface is
`plan(current, identity=(unit_type, firmware, catalogue), block=4,
seconds=300, expiry="off", group_cache=cache)`.
Either `seconds` or `expiry` may be omitted to preserve that control.
Block numbers are one-based. `apply(session, plan)` verifies and stages the
canonical edit, and `configure(session, **options)` plans and stages it.
Neither API saves or transfers to a unit.

## Admission and source rules

The existing Environment state must already be stable under
`IopeEnvironment.plan`: any initialization rewrite is refused and requires
its own reviewed Environment operation first. Linking must be enabled, and
the selected block must be its corridor, first office or enabled second office
role. The selected block must have a positive, existing group object.
Group selection and automatic creation are outside this component.

The timer window is the specialized `TfrmIOPEEnvironmentBlockTimer`.
Its `SetBlock` forces timer-resource variant 1 before inherited initialization.
The Environment caller sets the unit and block without binding an input
source. Consequently `GetValues` commits the selected block's timer and
expiry byte without changing an input macro or either potentiometer timer.

| Role | Admitted duration |
| --- | --- |
| Corridor | 60..65535 seconds |
| First or second office | 0..65535 seconds |

The corridor caller sets a flag which makes the subclass impose a one-minute
minimum. A retained corridor duration below 60 is refused even when the request
would repair it: initial invalid-time control normalization has not been
reproduced. The office path retains the ordinary initialized block minimum
of zero. Both paths use the inherited maximum 18:12:15.

| Expiry option | Original function type | Full IOPE command byte |
| --- | --- | --- |
| `idle` | 0 | `0x00` |
| `toggle` | 11 | `0x4F` |
| `on` | 13 | `0x47` |
| `off` | 15 | `0x40` |

Both the selected block's retained command and any requested command must
belong to this table. These values come from original registrations and
encoder case branches. They are full-byte IOPE commands, distinct from
classic keypad nibble codes. The original dropdown also offers ramp, recall
and scene functions; those paths can change dependent preset or scene state
and remain excluded here. Unsupported commands in unselected blocks are
preserved byte-for-byte.

## Ownership and verification

The editor guards all Environment layout dependencies plus these arrays:

| Parameter | Address | Operation |
| --- | --- | --- |
| `TimerExpiryCommand` | `0x36`, 8 bytes | Replace selected byte only |
| `TimerHighByte` | `0x40`, 8 bytes | Selected duration's high byte |
| `TimerLowByte` | `0x48`, 8 bytes | Selected duration's low byte |

Whole arrays are sent when changed, preserving their other seven slots.
Pot1/Pot2 expiry, global recall levels, scene data, groups, input functions,
role controls and all other parameters remain outside the write set.
Saved plans are reconstructed from their canonical options before staging;
forged writes/claims, stale dependencies and mismatched profiles/schemas fail
closed. A staged write failure restores attempted parameters. No save retry
or physical operation occurs in the editor.

The sanitized receipt
`research/fixtures/iope-block-timer-source-review.json` pins the original
EXE/MAP, 38 named method ranges, four form resources and four UnitSpec files.
It includes the entry, inherited initialization, function selection,
simple encoder branches, duration validation and agent serialization chain.
Private static disassembly is retained outside the repository; no vendor
specifications or executable bytes are committed.

Focused validation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -B -m unittest -v test_iope_block_timer
```

Set `CBUS_TOOLKIT_EXE` and `CBUS_UNITSPEC_DIR` for the additional static
source-hash/resource/layout gate. The focused run passed all 12 tests with
that gate enabled, including every unsupported retained byte, all simple
command transitions for every model, exact byte preservation, duration and
role boundaries, canonical-plan refusal, stale detection and rollback.

Original GUI/CPU-runtime execution, broader input-function/scene/pot editing,
whole-dialog effects and physical acceptance remain open. Native Java C-Gate
save/reload acceptance is a separate receipt; a staged synthetic test does
not establish persistence or controller timing.
