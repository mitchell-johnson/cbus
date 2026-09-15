# eDLT colours and brightness

`cbus_toolkit.edlt_colours.EdltColours` edits nine fixed colour/brightness settings and six numeric control-group references for **KEYGL5 / 5055EDL / firmware 5.5.00**. It verifies database PP data and the original five CRCs. It does not measure luminance, send application commands or verify a physical display.

```python
editor = EdltColours(spec)
plan = editor.plan(
    session.values(), text_colour='white', background_colour='blue',
    indicator_on_colour='green', indicator_on_group=255,
    active_screen_brightness=200, active_screen_group=255,
)
result = editor.apply(session, plan)  # native full PP readback, no save
session.save_to_source()             # explicit database persistence
```

The `plan` and `configure` methods accept these optional keyword arguments. Omitting an option preserves its stored value.

| Options | Accepted explicit values |
| --- | --- |
| `text_colour`, `background_colour` | `black`, `white`, `red`, `green`, `blue`, `cyan`, `magenta`, `yellow` |
| `indicator_on_colour`, `indicator_off_colour`, `page_key_colour` | `none`, `white`, `red`, `green`, `blue`, `cyan`, `magenta`, `yellow`, `orange` |
| `active_screen_brightness`, `idle_screen_brightness`, `active_indicator_brightness`, `idle_indicator_brightness` | Integer levels 0..255 |
| `active_screen_group`, `idle_screen_group`, `active_indicator_group`, `idle_indicator_group`, `indicator_on_group`, `indicator_off_group` | Integer references 0..254, or 255 for fixed control |

Brightness uses exact native levels, not percentages or physical units. Screen text and background may use the same colour: the original properties and bound controls do not enforce contrast. Palette indices follow the table order, starting at zero.

## Control dependencies

For each group-backed setting, an explicit fixed value requires the resulting group to be 255. This may already be stored, or the same plan may explicitly select group 255. Setting a group to 0..254 and supplying its fixed value together is rejected. Omitted fixed values remain stored when their controls are hidden. Page-key colour and the two screen colours have no control-group switch.

Both idle brightness settings and both idle group selectors require the existing `ActivityDuration` to be nonzero. The original UI binds the parent Standby Settings panel's enabled state to `EnableStandByPage`, whose getter returns that duration. This helper preserves standby timing; use the separate standby workflow to enable it before editing idle controls.

The six group fields refer to the unit's existing primary application. The helper applies exact numeric references and reports `group_metadata_verified=false` and `database_group_created=false`. It does not create, rename or discover group tags. Each plan includes the primary application and group number in `control_groups`, with `enabled=false` for 255.

This is a deliberate boundary from the original group's UI binding. Its numeric setter stores a value directly, but its getter looks up the group and may request creation. With auto-add disabled, a missing group is changed to 255. Enabling a disabled selector without an explicit number chooses the first group in its cached list, or initially 0 when empty. This helper requires an explicit number and does not invoke those lookup, creation or first-item selection effects.

## Stored values and byte layout

An omitted stored key colour outside the selectable 0..8 palette is retained. Its colour name is reported as `null`, its numeric value remains in `raw_values`, and `colour_ui_canonical` is false. Native acceptance preserves 9, 254 and 255 this way. Screen colours remain limited by their three-bit storage. Invalid explicit palette choices are rejected.

| PP parameter | Layout | Schema default |
| --- | --- | --- |
| `LCDBackground` | `0x113`, bits 0..2 | 0, black |
| `LCDForeground` | `0x113`, bits 3..5 | 1, white |
| `IndicatorOnColour` | Byte `0x11C` | 6, magenta |
| `IndicatorOffColour` | Byte `0x11D` | 0, none |
| `NavigationIndicatorColour` | Byte `0x11E` | 1, white |
| `IdleIndicatorBrightness` | Byte `0x11F` | 10 |
| `IdleBacklightBrightness` | Byte `0x120` | 10 |
| `ActiveIndicatorBrightness` | Byte `0x121` | 128 |
| `ActiveBacklightBrightness` | Byte `0x122` | 255 |
| `IndicatorOnColourControlGroup` | Byte `0x12B` | 255 |
| `IndicatorOffColourControlGroup` | Byte `0x12C` | 255 |
| `IndicatorIdleBrightnessControlGroup` | Byte `0x12D` | 255 |
| `BacklightIdleBrightnessControlGroup` | Byte `0x12E` | 255 |
| `IndicatorActiveBrightnessControlGroup` | Byte `0x12F` | 255 |
| `BacklightActiveBrightnessControlGroup` | Byte `0x130` | 255 |

`ActivityDuration`, read for the idle dependency, is byte `0x11B`. All listed layouts are validated against the supplied specification before use. The plan reports all 15 resolved options, numeric `raw_values`, per-option `editable` flags and `idle_controls_enabled`.

## CLI

```sh
cbus-toolkit edlt colours-plan parameters.json \
  --text-colour white --background-colour blue \
  --active-screen-group 255 --active-screen-brightness 200

cbus-toolkit cgate --host 127.0.0.1 --port 20023 unit \
  --lock-address //MYPROJ/254 --source /db//MYPROJ/254/p/20 \
  edlt-colours --indicator-on-group 42 --page-key-colour orange
```

All 15 keyword names have equivalent flags with hyphens. `--dry-run` on the `unit` command stages and verifies a preview without saving to the source. Normal execution saves the verified database result. Physical destinations are rejected.

## Preservation and failures

The helper preserves unrelated PP fields, scene contents, static strings and omitted values. It runs the established original save-stage normalization for functional blank/terminator widgets and MRA shared bits, updates the Application mirror and calculates five CRCs. Any normalization changes appear in the plan. It does not invoke the broader original `AfterLoadPPData` lifecycle, including configuration-version initialization, display inversion normalization or group lookup side effects.

Before mutation, `apply` verifies the exact identity and schema, reconstructs a canonical plan, and rejects changes to the complete source snapshot, including visibility dependencies. It reads back all resulting PP data. Ordinary failures attempt reverse rollback of attempted parameters only while the session remains synchronized. Disconnection stops recovery I/O. An interruption retains `edlt_colours_evidence`, attempted fields, uncertain PP state, `saved=false` and zero automatic retries. If rollback is interrupted, the original failure and prior rollback errors are retained too.

## Evidence

[NativeEdltColoursProbe.cs](../research/NativeEdltColoursProbe.cs) executes the unchanged original palette lists, scalar setters/getters, group bindings, standby getter, save hook and CRC code. Its 2,894 output rows comprise 1,084 palette/scalar vectors, 1,536 cached group vectors, 256 standby-duration vectors, three fixed-mode summaries, nine stored-colour vectors and six missing-group cases. Cached fixture objects disable automatic additions and background continuation; original methods are not patched.

The native PP test compares all 874 parameters and all five CRCs in nine scenarios: defaults, minimum and maximum values, group 0 and 254, return to fixed mode, preserved out-of-palette colours, disabled idle controls and MRA normalization. It checks the 30 raw bytes from `0x113`, database group metadata preservation and complete save/close/load equality. The fixture explicitly authors all eight scene slots before loading them into the original model, so the direct save-stage comparison includes nonempty scene data without introducing a separate scene-load normalization. Existing scenes and static text remain unchanged.

Tests also cover every palette choice, brightness boundaries, fixed/group transitions, omitted hidden values, bit-field preservation, unsupported layouts and profiles, invalid arguments, stale and forged plans, successful rollback, disconnected failures and primary/rollback interruptions. CLI tests cover offline planning, native preview/save, metadata and input guards.

Run the helper and CLI suites with an isolated native oracle and local vendor installation:

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_COLOURS_REPORT=research/runtime/edlt-colours-report.json \
PYTHONPATH=src:tests python3 -m unittest tests.test_edlt_colours tests.test_cli_edlt_colours -v
```

Original-model tests use the pinned Mono container. Native projects are disposable, remain `state=new`, and never open a physical network. The compact [acceptance fixture](../research/fixtures/edlt-colours-acceptance.json) records final interpreter results, literals, CRCs and source hashes. Vendor assemblies and data are not bundled with the CLI.

Final helper and CLI acceptance passed **11 tests with zero skips** on Python 3.13.14 (26.332s) and Python 3.10.20 (30.432s). The nine native PP reports and CLI reports were identical across interpreters.
