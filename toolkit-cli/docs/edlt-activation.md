# eDLT activation and proximity events

`cbus_toolkit.edlt_activation.EdltActivation` edits wake and proximity settings for **KEYGL5 / 5055EDL / firmware 5.5.00**, with full database PP readback and the original five CRCs. It does not wake a physical device or verify event emission.

```python
editor = EdltActivation(spec)
plan = editor.plan(session.values(), wake_mode='trigger-event', group=7, action=77)
result = editor.apply(session, plan)  # stage and verify, no save
session.save_to_source()             # explicit database persistence
```

`plan` and `configure` accept these optional keywords. Omission preserves the stored field.

| Option | Accepted value | Dependency |
| --- | --- | --- |
| `wake_mode` | `key-press`, `wake-unit`, `primary-event`, `trigger-event` | Existing standby enabled |
| `group` | Integer 0..254, or 255 for Unused | Resulting primary-event or trigger-event mode |
| `level` | Exact integer byte 0..255 | Resulting primary-event mode |
| `action` | Exact integer action selector 0..255 | Resulting trigger-event mode and group other than 255 |
| `activation_page` | `last-active`, `page-1` | Existing TimeoutPage 2 |
| `ignore_first_key_press` | Boolean | Existing TimeoutPage 0/1 and resulting key-press mode |

Every explicit option requires the existing `ActivityDuration` to be nonzero, matching the original Unit Activation Settings panel. This helper preserves standby timing and destination. Use the separate standby helper to change those first. An inactive configuration can still be inspected with a plan containing no explicit edits.

`level` and `action` target the same `ProximityLevel` byte and are mutually exclusive. The primary-event numeric level remains editable with group 255 in the original UI; this combination is accepted. The trigger action dropdown is disabled for group 255 and the helper rejects that combination. The Python planner's `level` argument uses protocol bytes. The CLI also accepts `--level-percent`, which converts an explicit decimal percentage using the original control's arithmetic before calling that planner.

## Numeric references and mode changes

Primary events use the existing primary application. Trigger events use application 202. The helper stores explicit numeric group/action references without looking up, creating or renaming database metadata. Results report `database_group_created=false`, `database_group_verified=false` and `database_action_verified=false`.

A mode change preserves an omitted group and event value. For example, a stored primary-event group 42/value 173 changed to trigger-event retains42/173 but refers to application 202. The plan reports both reference applications, `reference_application_changed`, `event_application` and `event_configured`. The latter means a supported event mode with a non255 group; it does not imply that a tag exists or an event was emitted.

This boundary is explicit because the original UI's group property getter is mutating. It looks up an application and group using their default create behavior. With automatic additions disabled, a missing group is replaced with255. Changing event modes changes that lookup context; in the independent fixture, group 42 exists in primary 56 but not trigger 202, and reading it after the switch clears it. The helper implements the direct setters and save stage while preserving numeric references; it does not reproduce automatic metadata creation or getter-induced clearing. Its native comparison uses explicitly cached original-model metadata and verifies that missing native database metadata remains missing.

## Layout and preserved values

| PP parameter | Layout | Schema default |
| --- | --- | --- |
| `IgnoreFirstKeyPress` | `0x116`, bit 0 |0 |
| `ProximityMode` | `0x117`, bits 0..2 |1, wake-unit |
| `DeafultPage` | `0x11A`, bits 0..3 |1, page1 |
| `ProximityGroup` | Byte `0x123` |255, Unused |
| `ProximityLevel` | Byte `0x124` |255 |

`DeafultPage` is the original parameter's exact spelling. Visibility dependencies read `ActivityDuration` at `0x11B` and `TimeoutPage` at `0x11A`, bits 5..6. All these layouts are validated against the supplied schema.

Stored ProximityMode 4..7 and DeafultPage 2..4 are schema-valid but absent from original selectable choices. Omitted values are preserved, their names are `null`, their raw values remain in `raw_values`, and their UI-canonical flags are false. Explicit settings accept only the original choices. Unedited hidden fields also remain stored. The plan includes an `editable` flag for each option.

Unrelated packed bits, scenes, static strings and omitted PP values are preserved. The helper applies the established original save-stage normalization for blank/terminator widgets and shared MRA bits, mirrors the two applications, and calculates all five CRCs. Such normalization appears in the plan. It does not run broader `AfterLoadPPData` effects such as configuration-version initialization, display inversion changes or metadata lookups.

## CLI

Use either `--level BYTE` or `--level-percent PERCENT`. The percentage must be
exact ASCII decimal text in 0..100, with 1..3 integer digits and at most 28
fractional digits, exactly representable by a .NET Decimal. Leading zeros and
value-preserving trailing zeros are accepted; signs, exponents, percent signs,
locale separators and surrounding whitespace are rejected. Conversion uses
the original separate decimal multiplication, division and integer truncation:
`--level-percent 50` requests byte 127. It does not simulate control bindings,
text formatting, mouse/keyboard events or the full WinForms lifecycle.

Both spellings are mutually exclusive and invalid percentage input is rejected
before command execution. The [separate nine-test CLI checkpoint](../research/fixtures/edlt-percentage-cli-acceptance.json)
passes on both Python versions. It covers original numeric outputs, existing
visibility guards, a single conversion into the normal write/save path,
interrupted writes without replay, legacy byte input and JSON output. Its
database session is a fixture; the earlier native acceptance below remains a
separate checkpoint.

```sh
cbus-toolkit edlt activation-plan parameters.json \
  --wake-mode primary-event --group 42 --level 173

cbus-toolkit cgate --host 127.0.0.1 --port 20023 unit \
  --lock-address //MYPROJ/254 --source /db//MYPROJ/254/p/20 \
  edlt-activation --wake-mode trigger-event --group 7 --action-selector 77
```

The action selector flag is `--action-selector`, corresponding to the Python `action` keyword. Boolean flags are `--ignore-first-key-press` and `--no-ignore-first-key-press`. Native `--dry-run` stages and verifies a preview without saving the source. Normal native execution saves the verified database result. Physical destinations are rejected.

## Failure behavior

`apply` checks the exact identity/schema, reconstructs a canonical plan and rejects a stale full snapshot before mutation. Full PP readback is required. Ordinary failures reverse attempted writes while the session remains synchronized; disconnection stops recovery I/O. No operation is retried automatically.

KeyboardInterrupt/SystemExit retain `edlt_activation_evidence`, attempted parameter names, uncertain PP state and `saved=false`. An interrupted rollback also retains the original failure and preceding rollback errors. A verified result remains unsaved until explicitly persisted.

## Verification

The unchanged original model probe executes 422 independently checked rows covering mode/page choices, all event bytes, radio setters, visibility guards, conditional cached-group behavior, primary applications 56/127/136 and application-list filtering. Its edit phase uses `PPAttribute.bInitialiseMode=false`, because initialization mode suppresses notifications needed to update conditional lists. Explicit cached objects disable external I/O; original methods are not patched.

Native acceptance compares full PP snapshots and five CRCs against the original setter/save code, reads the 15 bytes from `0x116`, saves and reloads the database project, and checks metadata and unrelated scenes/static labels. Disposable projects remain `state=new`; no network is opened. Pure tests cover hidden-field and packed-bit preservation, bounds, stale/forged plans, identity/layout guards, readback faults, rollback, disconnect and interruptions.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20023 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_ACTIVATION_REPORT=research/runtime/edlt-activation-report.json \
PYTHONPATH=src:tests python3 -m unittest tests.test_edlt_activation tests.test_cli_edlt_activation -v
```

See the [remaining global controls](edlt-remaining-controls.md) for separate application-selection, page-control, corridor-linking and label workflows. Completion of this helper does not establish whole-Toolkit or physical-device parity.

Final helper and CLI acceptance passed **11 tests with zero skips** on Python 3.13.14 (39.476s) and Python 3.10.20 (44.049s). The 18 native reports were identical across interpreters. Every native scenario compared all 874 parameters, all five CRCs and packed raw bytes. The application comparison parses complete XML subtrees and verifies that application 56 remains unchanged while applications 127, 136 and 202 remain absent, including after save/close/load. The [compact acceptance fixture](../research/fixtures/edlt-activation-acceptance.json) records these outcomes, literal raw vectors and source hashes.
