# eDLT Page Control

`cbus_toolkit.edlt_page_control.EdltPageControl` configures the numeric Enable application group used by Page Control on **KEYGL5 / 5055EDL / firmware 5.5.00**.

```python
editor = EdltPageControl(spec)
plan = editor.plan(session.values(), group=42)
result = editor.apply(session, plan)  # stages and verifies database PP data
session.save_to_source()             # explicit persistence
```

`plan` and `configure` accept one optional keyword: `group`, an integer from 0 through 255. Values 0..254 configure a reference; 255 disables Page Control. Omitting the option preserves the existing value. Booleans, floating-point values and strings are rejected. The application is fixed at **203**, independent of the unit's primary and secondary applications.

The original control has no standby or single/multiple-page prerequisite. A reference can be edited while `ActivityDuration=0` or `NavWidgetType=0`; those settings remain unchanged. A separate Global Programming checkbox controls the enabled state of this section in the multi-unit copy dialog, which this single-unit helper does not implement.

The only dedicated PP field is `KeySetsEnableGroup`, an integer byte at **0x131**, with default 255. The helper validates that exact schema shape. It preserves adjacent colour and corridor settings, scenes, static labels and unrelated PP values. It performs the established original save-stage normalization for blank/terminator widgets and shared MRA bits, mirrors the primary/secondary applications and calculates five CRCs. Normalization changes are reported.

## Metadata boundary

The result includes `group`, `application=203`, `enabled=(group!=255)`, `database_group_created=false` and `database_group_verified=false`. It does not discover, add or rename application/group metadata. The original selector includes a Disabled entry with value 255; its internal binding uses `DisabledValue=-1`, so the original `IsEnabled` getter remains true even when Page Control is disabled. The helper's reported `enabled` describes the stored configuration, not that internal binding flag.

The original numeric setter stores the value directly. Its group getter looks up the selected group with default auto-create behavior. With additions disabled, a missing cached group is changed to 255. Constructing the original binding can also request creation of application 203. The helper avoids those lookups and side effects: it preserves explicit numeric references even when metadata is absent. The original Add/Edit buttons for metadata are separate operations.

## Documented physical behavior

The bundled Toolkit Help topics **19522, General Settings tab**, and **18965, Configuring key sets**, describe these Enable Network Variable values:

| Value | Documented behavior |
| --- | --- |
|0 | Release the page restriction |
|1..4 | Select the corresponding functional page |
|254 | Select standby |

Topic 18965 explains a value 2 example in which page 2 is selected while standby remains accessible, then value 0 restores access to the functional pages. Topic 19522 describes both single-page and multiple-page configurations. The documents do not establish behavior for values 5..253 or 255, requests for unavailable pages, power-cycle retention or every interaction with local navigation and standby settings.

These are documented device behaviors, **not physical acceptance results**. This helper configures the receiver's group reference and sends no Enable messages. It reports `physical_page_control_verified=false`. Existing Enable application transport and widget configuration are separate capabilities; neither alone proves a real eDLT changed its displayed page.

## CLI

```sh
cbus-toolkit edlt page-control-plan parameters.json --group 42

cbus-toolkit cgate --host 127.0.0.1 --port 20023 unit \
  --lock-address //MYPROJ/254 --source /db//MYPROJ/254/p/20 \
  edlt-page-control --group 255
```

The native unit workflow supports `--dry-run` for a staged, verified preview without saving the source. Normal execution saves the verified database result. Physical destinations are rejected.

## Validation and failures

`apply` validates the exact identity/schema, reconstructs the canonical plan and checks the complete source snapshot before mutation. It requires complete PP readback. Ordinary failures attempt reverse rollback of attempted parameters while the connection remains synchronized. Disconnection stops recovery I/O, and no write is automatically retried.

KeyboardInterrupt/SystemExit retain `edlt_page_control_evidence`, attempted parameters, uncertain PP state and `saved=false`. If rollback is interrupted, the original failure and preceding rollback errors are also retained. The helper does not execute the broader original `AfterLoadPPData` lifecycle or its metadata lookups and other load-time normalization.

## Acceptance evidence

The combined helper and CLI suite passed **10 tests with zero skips** on Python **3.13.14** (85.230s) and **3.10.20** (136.475s). The original Windows model matched **284 independent binding/setter vectors**. All **13 native cases** matched **874 PP fields**, all five CRCs and literal adjacent bytes, then survived database save/close/load. The compact record is [edlt-page-control-acceptance.json](../research/fixtures/edlt-page-control-acceptance.json).

[NativeEdltPageControlProbe.cs](../research/NativeEdltPageControlProbe.cs) executes the unchanged original selector/binding, save hook and CRC methods. Its independent expected vectors cover every group byte, the Disabled placeholder, cached-list order, missing-group clearing, and independence from primary application, standby and page mode. Fixture objects disable external I/O, and original methods are not patched. The new Windows backend compiles x86 probes against the exact staged Toolkit 1.18.0.2754 assemblies using native .NET Framework. The existing Docker/Mono path remains selectable and uses `--network none`.

The native PP suite uses owned disposable projects and compares complete snapshots, all five CRCs and the three bytes around 0x131. It checks both absent application 203 and explicitly created test metadata, verifies unchanged application XML subtrees and performs save/close/load. Explicit fixture metadata creation is distinguished from helper actions. Projects remain `state=new` and never open a network.

```sh
CBUS_WINDOWS_BRIDGE=1 \
CBUS_CGATE_TEST_HOST=127.0.0.1 \
CBUS_CGATE_TEST_PORT=20033 \
CBUS_UNITSPEC_DIR=research/vendor/unitspec-plain \
CBUS_TOOLKIT_EXE=research/vendor/toolkit/app/CBusToolkit.exe \
CBUS_EDLT_PAGE_CONTROL_REPORT=research/runtime/edlt-page-control-report.json \
PYTHONPATH=src:tests python3 -m unittest tests.test_edlt_page_control tests.test_cli_edlt_page_control -v
```

The core source mapping is `EDLTUnit.cs:1377`, `PPAttributeDataSourceLogic.PPAttributeValue`, `PPAttributeLogic.IsEnabled`, `ComboBoxAddEdit.SetUpDataBindings` and `FrmBaseUnit.cs:6461..6485`. The help documents describe physical behavior separately from the configuration schema and model.

The Windows backend requires the explicitly launched, owned [Windows research bridge](windows-native-oracle.md); it does not start or configure a VM automatically. The independent C-Gate instance is version 3.4.0 build 2001 and listens only on host loopback. Windows original-model execution and Mac C-Gate database execution are recorded separately from earlier Docker/Mono acceptance.
