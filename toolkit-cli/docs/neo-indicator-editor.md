# Per-unit Neo indicator editor

The `neo-indicator-editor` workflow models the ordinary Toolkit
`TfrmNeoInputIndicators8` panel for 30 exact Neo-core profiles at firmware
2.5.00. It provides per-physical-LED edits and ordered control callbacks.
The existing `neo-indicator-plan`, `neo-style-plan`, `neo-indicators` and
`neo-indicator-styles` commands retain their Unit Magic bulk behavior.

```sh
cbus-toolkit keys --spec-dir "$CBUS_UNITSPEC_DIR" \
  neo-indicator-editor-show KEYM4.xml snapshot.json
cbus-toolkit keys --spec-dir "$CBUS_UNITSPEC_DIR" \
  neo-indicator-editor-plan KEYM4.xml snapshot.json --controls controls.json > plan.json
cbus-toolkit cgate --host 127.0.0.1 --port "$PORT" unit \
  --source /db//PROJECT/254/p/1 --dry-run neo-indicator-editor \
  --spec-dir "$CBUS_UNITSPEC_DIR" --spec KEYM4.xml --plan plan.json
```

Omit `--dry-run` to save to that existing database source. Alternatively,
pass `--controls controls.json` to plan from the current database values.
The workflow refuses network sources and different destinations. It stages
and verifies PP values; the owning command saves once. A lost save response
does not cause an automatic retry. This does not program physical hardware.

Export snapshots bind unit type, firmware and catalogue number. Bare parameter
mappings use firmware 2.5.00 and no catalogue context unless `--firmware` and
`--catalog-number` are supplied. A reviewed plan must match the actual database
identity when applied; use a fresh export for a unit with a catalogue number.

Each JSON array entry represents one control action. For example:

```json
[
  {"led": 2, "on_colour": "blue"},
  {"led": 2, "style": "always_off"}
]
```

This retains the blue choice while turning the indicator off. Reversing those
actions refuses the colour edit because the colour cell is then disabled.
LED numbers are physical positions starting at 1, bounded by the profile's
indicator count. Scene-key assignment does not disable this indicator grid.
Off-colours are derived and read-only. The stored block assignment selects the
monitored block and does not reorder physical LEDs.

Standard, Saturn and Decorator profiles offer `always_off`, `always_on`,
`status_on` and `status_dual`. Reflection and Classic offer the first three;
loaded raw style 3 becomes `status_on`. Classic and Reflection on-colours
cannot be edited. Reflection displays blue and saves PrimaryColour 1 in all
eight slots, including invisible positions. Classic retains loaded colours.
Ordinary primary colours are blue/orange, catalogue 5041NMML uses blue/red,
and Avanti uses red/green. Nightlight colour ordinals reverse the primary
colour order.

Global controls also use one value per entry, for example
`{"key_press_brightness_enabled": true}` followed by
`{"nightlight_enabled": true}`. The panel view reports each control's
visibility, availability and value. It derives the initial state from the
snapshot and applies callbacks in order; no caller-provided settled-state
flag is needed. Setting a checkbox to its current value does not replay a
change callback. Disabled loaded values can remain stored, while a real
control change can clear dependent values.

| Control | Values and availability |
| --- | --- |
| `brightness_source` | `fixed`, `group`, `first_block`; choosing group preserves the existing ninth `GroupAddress` reference |
| `fixed_brightness_percent` | Integer 0..100 while fixed brightness is selected |
| `key_press_brightness_enabled` | Boolean; unavailable on Classic |
| `key_press_brightness_level` | Integer 0..15 while key-press brightening is enabled |
| `key_press_duration` | Integer 1..15 seconds while key-press brightening is enabled |
| `nightlight_enabled` | Boolean; unavailable on Classic; requires key-press brightening except ordinary Standard Neo |
| `first_press_ignored` | Boolean while both nightlight and key-press brightening are enabled |
| `timer_flash_enabled` | Boolean |
| `id_backlight_enabled` | Boolean on ordinary Standard Neo; hidden on Decorator and other families |
| `nightlight_colour` | An offered colour label on Saturn/Zen/Modena/Avanti when the nightlight control is enabled and checked |

The fixed slider preserves a loaded byte when its displayed position is
unchanged: raw 128 displays 50%; selecting 50 again keeps 128, while moving
49→50 writes 127. Classic has a separate brightness loader and writer;
its `first_block` selection retains the model brightness instead of emitting
the ordinary first-block wire code. The preview shows the resulting bytes.
Selecting or creating a different brightness group is not implemented here.

The panel owns all eight stored indicator entries, even when fewer physical
columns are visible. A plan applies their load/save normalization once after
the requested controls. An empty array `[]` previews that normalization.
Packed scene-selector, block-assignment and other unrelated bits are preserved.
The serialized plan records the source state and resulting control history;
replay, schema, identity and freshness checks run before any PP writes.

The admitted profiles are KEYM2/4/8, KEYDV1/2/3/4, KEYB2/4/6,
KEYH1/2/3/4, KEYP2/4/6, KEYV1/2/3, KEYA1/3/6/8, KEYAV2/4,
KEYC1/2/4 and KEYCIR4. KEYE1's separate physical-key remapping,
other firmware/specifications, parent-form Apply/Cancel history, and
application/group object creation remain outside this workflow.
`EnableNightlightControl` is hidden by the original form setup and is not an
offered control. Its hidden value survives ordinary profiles, while Classic
save writes the source model's false default. This bounded panel does not reproduce every parent-agent
save side effect or establish original GUI, native-runtime or hardware parity.
