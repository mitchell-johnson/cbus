# Barcode scanner workflows

Toolkit 1.18.0.2754 treats the C-Bus barcode scanner as a USB keyboard wedge (help 4595). It has no scanner driver or protocol. The scanner types the barcode and Toolkit interprets the text in two places:

- **Units view, F10.** A C-Bus *software configuration* barcode adds a unit to the selected network, or selects an existing unit (help 4596/4597).
- **Unit dialog, F10.** A serial or software configuration barcode fills the Serial Number field on the Unit Identification page.

`cbus_toolkit.barcode_scanner` reproduces these rules. `cbus-toolkit barcode parse` classifies scanner text without changing any files. `cbus-toolkit project add-unit --barcode` applies a Units-view scan to an offline legacy XML/CBZ project. `cbus-toolkit cgate database barcode-add` previews or applies the same add/select policy to one loaded database project.

## Evidence

`research/barcode_scanner_original.py` requires the pinned `CBusToolkit.exe` (SHA-256 `9d01721a…655ab`) and MAP (`f96f05ce…1eb`). It performs two checks:

1. **Static check.** It disassembles 32 MAP-bound routines, requires every branch constant, UTF-16 literal and registered message listed below, and pairs `CIS_TKipperErrors`/`CIS_CBusErrors` registrations with their resource strings.
2. **Emulation.** It runs the unchanged original instructions under Unicorn: `TfrmBarcode.FormKeyPress`/`Timer1Timer`, `CIS_TfrmSoftwareLabel.IsSerialNumber`, `TfrmKipperMain.ProcessBarCode`/`AddUnitByCatalogCode`, `CIS_CBus.GetDisplayableSerialNumber`/`FormatSerialNumber`, `TCBUSUnit.SetSerialNumber` and `TCBUSUnitManager.UnitBySerialNumber`.

Delphi string runtime helpers, dialogs, the tree view, the catalogue, and the project and network objects are Python fixtures at their call boundaries. The receipt lists each fixture. The committed receipt, `research/fixtures/barcode-scanner-original-vectors.json`, contains method start/end addresses and code hashes, not instruction bytes. `tests/test_barcode_scanner.py` replays all 73 emulated vectors against the Python model.

This is original-instruction evidence. It is not a GUI run, a native C-Gate project edit, a physical scanner capture or hardware acceptance.

## Scanner input (TfrmBarcode)

The Barcode Scan dialog's label is `Ready to Scan Barcode.  Press ESC to Cancel.`. The form has `KeyPreview=True` and a hidden `Edit1` focus sink. `Timer1` runs with `Interval=75`.

- `FormKeyPress` appends every character except `#13` to the buffer. Every key updates the last-keystroke tick.
- `FormKeyDown` clears `VK_RETURN`.
- `Timer1Timer` closes the dialog with `mrOk` when the buffer is not empty and more than 75 ms (`GetTickCount` difference `> 0x4b`) have passed since the last keystroke.
- **Enter does not end a scan; only the idle gap does.** A carriage return inside a scan is removed.
- Esc triggers the `Cancel` button (`ModalResult=2`). `TApplicationManager.AcquireBarCode` then returns an empty string, and both callers ignore an empty result.

The CLI cannot observe keystroke timing. `wedge_lines` therefore treats each LF-terminated line as one scan, removes CR anywhere and skips empty lines. `acquire()` replays explicit key/timer/escape events for the exact timer rule. Other characters, including interior spaces and control characters, are kept, as the original keeps them. Characters outside the Basic Multilingual Plane are rejected because Delphi's UTF-16 indexing would differ.

## Units view (TfrmKipperMain)

`FormKeyDown` handles F10 (`0x79`). If the selected tree element is not a `TCBUSUnitManager` (a network's Units node), Toolkit shows message 2300: *Barcode scanning is supported only on the Units node*. `ProcessBarCode` runs two **independent** branches, in this order:

1. If the length is at least 28, it calls `AddUnitByCatalogCode(text)`.
2. If the first character is `0`, it calls `HandleScannedSerialNumber(text, report_missing=True)`.

Any other text, including a short text that does not start with `0`, is silently ignored. Message 2097 (*Wrong barcode scanned, please scan the "Software Config Code"*) and 2095 are registered but no 1.18.0.2754 code references them. The CLI rejects ignored text with `wrong_barcode` instead of silently succeeding.

`AddUnitByCatalogCode` handles a software configuration barcode as follows:

1. It replaces every `¼` (U+00BC, a keyboard-layout artifact) with `,`.
2. It does nothing if no project is open.
3. It sets the **catalogue field** to `Trim(Copy(text, 1, 16))`. The **lookup code** is that field truncated before the first `-`, then before the first `,`, then before the first space. The **serial** is `Trim(Copy(text, 17, 255))`. `Trim` removes code units ≤ U+0020.
4. It calls `HandleScannedSerialNumber(serial, report_missing=False)`. If any network in the project contains a database or physical unit with an equal displayable serial, Toolkit selects that unit and adds nothing. **A duplicate serial is a selection, not an error.**
5. It calls `TUnitTypeManager.FindUnitByCatalogCode(lookup)`. If nothing matches, Toolkit shows message 2099: *Scanned Unit Type not known*.
6. If the selected element is not the Units node, it stops silently.
7. If the network already has 255 units, Toolkit shows message 2066: *Cannot add a new Unit as there are already 255 Units in the Database.*
8. It checks the network family. `TCBusNetwork.GetIsWireless`/`GetIsWired` test whether any unit type is, or is not, wireless. The unit type's family is the `Family=` value of its `UnitTitle`:
   - A wireless-only network with a family that does not contain `wireless` produces message 45151: *Cannot add Wired Unit to the Wireless C-Bus Network*.
   - A wired-only network with a family that contains `wireless` produces message 45152: *Cannot add Wireless Unit to the Wired C-Bus Network*.
   - An empty or mixed network accepts either family.
9. It calls `AddUnit(serial, UnitCode, catalogue field)`.

`AddUnit` then does the following:

- It takes the first free address from 1 through 255 (`GetNextAvailableAddress`/`GetMaximumPossibleAddress = 0xFF`). If none is free, it shows message 2271: *Cannot create a new Unit.  All available addresses are in use.*
- It creates the unit with:
  - `SerialNumber` from `SetSerialNumber`
  - `CatalogNumber` set to the untruncated catalogue field
  - `UnitType` set to the catalogue entry's `UnitCode`
  - `FirmwareVersion` set to `GetDefaultFirmwareForType`
  - `State=New`
  - `TagName` and unit name `NEWUNIT` when empty
- It opens the **Tag Name** dialog (`TfrmGetTagName`). The dialog shows Unit Type and Catalog Code, preselects the allocated address and offers every unoccupied address from 0 through 254. OK writes the tag and address.
- Cancel raises `EGetTagNameCancelled`, and the unit is discarded.
- After the save, a network with more than 100 units shows message 45141, the recommended-maximum warning.

`UnitCode` is the `UnitType` of the catalogue entry's **first** firmware revision (`TUnitType.CalcCategoryAndFamilyName`). Toolkit loads the catalogue through `pp get_unit_catalog`, which C-Gate 3.4 serves from `unitspec/cbusunits.xml`. `GetDefaultFirmwareForType` scans the top-level entries whose `UnitCode` matches, case-folded with `UpperCase`. It returns the `MinVersion` of the **last** revision marked `IsDefault=true`, or `1.00` if there is none.

### Catalogue matching (FindUnitByCatalogCode)

The lookup code is converted to ASCII upper case. The first matching entry wins, in this order:

1. **Each entry's own `CatalogNumber`.** The number is upper-cased and truncated before `,`; otherwise before `-`; otherwise before `*`. For `*`, a nonempty prefix that starts the code matches. The code also matches when it equals the truncated number.
2. **The entry's `AlternativeCatalogNumbers`** (`HasCatalogNumberInAlternates`). If the raw list contains `*`, its text before the first `*`, taken after the last `,`, matches as a prefix. Otherwise the code must occur inside the raw list. The list is then split on `;`, and each piece is truncated before `,`. A piece matches by `CompareText` equality or by a `*` prefix.
   - **Quirk:** the original copies the final piece one character short, so the last alternative never matches here.
3. **The entry's `SubUnits`**, searched recursively.
4. **Appended clones.** `AddAlternativeCatalogNumberUnits` appends one clone per `;`-separated alternative of each top-level entry, with that alternative as its `CatalogNumber`. The clones are searched last, which masks the final-piece quirk.

## Unit dialog serial scan (IsSerialNumber)

`TfrmCBusUnitBase.FormKeyDown` handles F10 unless the unit's `+0xDD` flag is set. It switches to the Unit Identification page and calls the frame's `StartBarcodeScan`. After a nonempty scan, `CIS_TfrmSoftwareLabel.IsSerialNumber` applies these rules:

| Scanned text | Result |
| --- | --- |
| length > 28, or length > 10 and prefix `93` (a retail EAN) | Wrong-barcode form (*To enter the Serial Number using scanner…*), no change |
| length 12 | Serial = whole text |
| length 28 | Serial = characters 17–28; Catalog Number field = `Trim(Copy(1, 16))` |
| anything else | Wrong-barcode form |

An accepted serial has every space removed, and Toolkit shows message 2150: *Serial Number was successfully scanned*. The serial field receives focus. A text of 12 spaces is therefore accepted as an empty serial. The dialog field is only staged. The existing dialog validation (`CheckSerialNumber`) and the save path (`SetSerialNumber`) apply later. `CheckSerialNumber` has not been recovered here.

`barcode parse` reports this path under `unit_dialog`, including `stored_serial`, the value `SetSerialNumber` would store. To apply a staged serial to an existing database unit offline, run `project field-set FILE /network/N/unit/A SerialNumber <stored_serial>`. This is an operator-entered serial. It differs from [database serial population](serial-population.md), Toolkit's **Get Serials**, which copies physically read serials and verifies type and firmware. The barcode path does neither.

## Serial forms

- **`FormatSerialNumber`** keeps only digits and dots.
  - With a dot, the text before the first dot is left-padded to 8 digits and the text after it to 4 digits.
  - Without a dot, the text is left-padded to 12 digits.
  - It never truncates.
- **`GetDisplayableSerialNumber`** uses the undotted form. It maps `000000000000` and `010485754095` to `No serial #`.
- **`SetSerialNumber`** stores the dotted form (`12345678.9012`) only for a nonempty value with no dot. Any other value is stored verbatim.
- **`UnitBySerialNumber`** compares displayable forms exactly. A scan whose displayable form is `No serial #` never matches.

## CLI

```sh
cbus-toolkit barcode parse '5031NL          123456789012'
printf '123456789012\r\n' | cbus-toolkit barcode parse
cbus-toolkit project add-unit site.cbz --network 254 --catalog cbusunits.xml \
  --barcode '5031NL          123456789012' [--address 12] [--tag-name Kitchen] [--output copy.cbz]
```

`--barcode -` reads exactly one wedge line from stdin. `--catalog` defaults to `CBUS_UNIT_CATALOG`.

`add-unit` reports one of two actions:

- `added`: the unit path, automatic and chosen addresses, created fields, the matched catalogue entry and the catalogue SHA-256.
- `selected_existing`: the unit path and `changed: false`. The file is not written.

A 28-plus-character scan starting with `0` also reports the second, serial-lookup branch and message 2096 when it misses, as Toolkit would.

Error codes, returned with exit status 1 and no file change:

- `wrong_barcode`
- `invalid_input`
- `non_bmp_input`
- `unknown_unit_type` (2099)
- `catalog_entry_without_type`
- `network_not_selected` (2098)
- `not_units_node` (2300)
- `database_full` (2066)
- `wired_unit_on_wireless_network` (45151)
- `wireless_unit_on_wired_network` (45152)
- `no_free_address` (2271)
- `address_unavailable`

`--address` must be the automatic address or a free address from 0 through 254, the Tag Name dialog's choices.

These differ deliberately from Toolkit:

- An ignored scan is an error.
- A catalogue entry without a revision `UnitType` is refused. Toolkit would create a unit with an empty type.
- Offline projects have no physical units, so serial lookup covers database units only.

### Loaded database project

Use an exact Network address from the loaded project's XML. A native Network can have a name such as `CustomA`; its Address is distinct from its physical `NetworkNumber`.

```sh
cbus-toolkit cgate --host HOST --port PORT database barcode-add //PROJECT/NETWORK \
  --project PROJECT --catalog cbusunits.xml --barcode '5031NL          123456789012'
```

The default is a preview. It reads the complete project after one `PROJECT USE`, then reports the plan without creating a Unit. The plan includes the catalogue and project snapshot SHA-256, matched catalogue entry, chosen address, tag and native fields. `--barcode -` accepts exactly one wedge line from stdin; `--catalog` also uses `CBUS_UNIT_CATALOG` when set. The selected project and Network must already exist.

To create the planned database Unit, repeat the command with `--apply --exclusive-project`. The latter asserts that you own project editing and reloading for this operation. `--expect-project-sha256 HASH` and `--expect-catalog-sha256 HASH` optionally bind the initial project export and exact catalogue bytes to a reviewed preview. Before creation, the command rechecks the catalogue file and project snapshot and refuses drift. These checks do not provide server-side compare-and-swap; maintain exclusive ownership through readback.

The add path sends one `DBADDSAFE` and one Unit `DBSETXML` initializer, verifies the issued fresh OID at the exact address, reads every planned scalar and Unit XML, and checks the whole project while preserving unrelated XML. `--address` uses the same first-free/dialog choices as the offline command; `--tag-name` changes `TagName` while `UnitName` remains `NEWUNIT`. Native Unit fields omit the offline editor's `State=New` marker. Existing minimal database Units still occupy their addresses and participate in serial lookup.

A duplicate serial in any project Network selects the first matching Unit in project XML order. Its path and OID are reported, and no add or initializer is sent. Valid supplied address/tag choices do not alter that selection. A serial-only miss reports `not_found` with warning 2096 and no write. A zero-prefixed software configuration scan runs the second serial branch after the conceptual creation; its result and warning order are retained in the plan.

`--auth-token-file FILE` supplies a private one-token cmqttd LOGIN credential before `PROJECT USE`. Credential values are redacted from command evidence and authentication errors. Catalogue XML, scan count/type, project/Network syntax and supplied tag text are validated before connection. Catalogue matching and address/family checks use the project snapshot after project-wide duplicate lookup.

The result uses `cbus-cgate-barcode-add-v1` and records phase, plan, attempted/confirmed writes, readback and `outcome_uncertain`. The command does not save the project, load programming defaults, or program hardware. Save separately with the existing project workflow when persistence is intended. An error after ADD can leave a new or partially initialized Unit. There is no automatic retry, rollback or delete: retain the failure evidence and inspect the reported path/OID through a fresh read before taking further action. Do not rerun an uncertain apply automatically.

The policy retains the original-instruction barcode component evidence. Database workflow tests use owned mock/cmqttd fixtures. These do not establish original Toolkit GUI behavior, Schneider native-server acceptance, physical inventory/scanner behavior or PICED integration.

Input bounds are 16 MiB for a regular-file catalogue, 4 MiB characters for a
scan and 4 MiB UTF-8 bytes for the planned Unit document. A UnitType or firmware
containing control characters and an oversized initializer refuse before ADD.

## Unresolved

- Sibling routines `TfrmKEYGL5.IsSerialNumber`/`AcquireBarCode`, `TfrmHydraWPFBase.BarCodeScan` and `THydraDataModule.BarCodeScan` were not analyzed.
- The meaning of the unit-dialog `+0xDD` guard is unresolved.
- Unit-dialog serial validation (`CheckSerialNumber`, `CIS_CBus.ValidateSerialNumber`) is unresolved.
- Emulation does not cover the Tag Name dialog's tag validation, if any.
- Emulation does not cover `FindUnitByCatalogCode` or `HasCatalogNumberInAlternates`; the model follows static disassembly only.
- It is not established that `pp get_unit_catalog` output equals the catalogue file byte for byte.
- Barcode add/select against an owned loaded database has a CLI workflow; broad Schneider native-server and original GUI acceptance remain open.
- No GUI, physical scanner or hardware acceptance exists.
