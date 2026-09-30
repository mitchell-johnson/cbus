# Original Document Project page capture: feasibility and remaining gates

Status on 2026-09-30: **no original generated page captured**. This investigation
read the pinned original EXE/MAP and existing research harnesses. It did not
launch Toolkit, submit a Windows job, open a project, start C-Gate, or access a
physical interface. The new receipt is static dependency evidence only.

## What the pinned original actually requires

Inputs are Toolkit 1.18.0.2754:

- EXE SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`
- MAP SHA-256 `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`

[The reproducible receipt](project-documentor-page-feasibility-static.json)
records ten method-span hashes, direct-call names, indirect-call counts and
three resolved VMT slots. It contains no vendor instruction bytes or source
dump. Generate a new receipt with:

```sh
python research/project_documentor_page_feasibility.py \
  --executable /explicit/pinned/CBusToolkit.exe \
  --map-file /explicit/pinned/CBusToolkit.map \
  --output /new/output/feasibility.json
```

`TProjectNodeHelper.DocumentProject` constructs a `TProjectDocumentor`, a native
`TStringList`, and a VCL `TfrmProjectDocumentor`. `SetProject` merely stores an
existing native project-object pointer; it is not an XML importer. The form's
VMT slot `+0x110` resolves to `TCustomForm.ShowModal`. Its timer calls
`OnDocumentHTMLnew`, then closes the form. After a non-cancelled result,
`DocumentProject` saves `<GetAppPath>\<project TagName>.html` through the real
`TStrings.SaveToFile` slot with `TEncoding.GetUTF8`, then calls `ShellExecute`.

Before writing the HTML lines, `OnDocumentHTMLnew` calls `GetAllProjectInfo`:

| Step | Confirmed original dependency | Capture implication |
| --- | --- | --- |
| Network inventory | `TCGateObjectManager.LoadAndSort` | Needs valid original manager/workspace objects. |
| Unit programming | `GetAllUnitProgramming` then `GetUnitProgramming` | Uses the real unit class and storage machinery. |
| Storage loads | Unit VMT `+0x88` resolves to `TPersistableObject.StorageLoad` | Loads `UnitAttributes` and `ProgrammingParameters` with `Database`; finally invokes `ProgrammingUnlock` with `Database`. |
| Application/group loading | `EnsureUnitsApplicationsGroupsLoaded` creates `TCBusNetworkCGateAgent` in the network workspace | Invokes `LoadAllUnitApplications` and each unit's `Groups` storage load. |
| C-Gate application fetch | `LoadAllUnitApplications` constructs `TcgcGetAsterisk` and calls `TCGateCommand.CommandExecute` | Even a cached-looking project does not establish a no-I/O path. The command path includes `/p` and requests `Application`. |
| Calculator | `GetAllProjectInfo` invokes `CalculatorTest` through storage dispatch | Requires original catalogue/calculator dependencies to be available. |
| Remaining inventory | Application/group/level `LoadAndSort` calls | Must preserve original collection ordering and virtual records. |
| Timestamp | `SysUtils.Now`, `DateTimeToString`, resource format | Capture the original displayed time and locale before comparing CLI bytes. |

`BURDEN`, `XC100B`, and `XC305B` bypass per-unit programming, but this does not
bypass network/application/group loading. A heading-only unit therefore does
not make a normal original GUI run safely offline by itself. Missing database
metadata can also activate original auto-add paths: previous CSV research
demonstrated an Area-group creation/save attempt. A synthetic project should
be disposable even when the intended report is observational.

## Existing harnesses: what can be reused

- [`windows_bridge.py`](../../windows_bridge.py) is an already-owned UTM file
  transport plus one-shot, hash-verified job admission. It is not a network or
  registry sandbox. `network_listener=false` describes the bridge itself;
  it does not prove that a launched Toolkit process cannot connect outward.
- `WindowsModelProbe` compiles a C# executable against staged managed DLLs.
  The inspected Toolkit executable is native x86 (`Machine=0x14c`, GUI
  subsystem 2, CLR header RVA 0). A `CBusLogicModel.dll` reflection probe does
  not expose the Delphi `TProjectDocumentor` implementation.
- [`windows_preferences_original_gui_same_user.py`](../../windows_preferences_original_gui_same_user.py)
  establishes bounded original GUI startup, staging and preference backup/
  restoration. It starts Toolkit normally under the active console user. It
  does not seed a private project, pin the selected C-Gate endpoint, exercise
  Document Project, or establish guest network isolation. Reusing its launch
  step alone would leave the critical capture boundaries unresolved.
- [`project_documentor_usage_original.py`](../../project_documentor_usage_original.py)
  executes one original ActionSelectorUse method with synthetic accessors and
  string/collection hooks. It is useful original branch evidence. It does
  not initialize the native project, run the complete documentor, execute the
  original file serializer, or capture a GUI-generated page.
- [`toolkit_database_csv_original.py`](../../toolkit_database_csv_original.py)
  demonstrates a bounded macOS process with `sandbox-exec` network denial,
  exact source/library hashes, fresh output directories and owned-process
  cleanup. Its original-instruction providers remain explicit. This pattern
  can support an offline renderer experiment, but is not a ready-made
  Document Project harness.
- [`original_workflow_capture.py`](../../original_workflow_capture.py) shows
  a managed original model talking to a freshly seeded, owned native C-Gate
  through a recording loopback relay. It is an architectural reference for
  isolated synthetic database evidence, not a Delphi GUI page capture.

## Read-only environment check

The pinned EXE and MAP at the supplied external vendor root were readable and
passed their hashes. The existing Python 3.13 environment successfully ran
the static collector and resolved all ten method spans and three VMT targets.

One read-only pull of the existing guest's exact `bridge-ready.json` was
attempted through the repository's configured `utmctl`, VM identity and owned
guest directory. `utmctl` exited **134** immediately, with no stdout or stderr.
No `.cmd`, admission file or vendor process was submitted. This result does
not establish whether the guest is stopped, the bridge is absent, or the
execution environment cannot reach UTM; it only establishes that bridge
readiness could not be verified here. No retries, guest startup, new access,
policy changes or alternate channel were attempted.

## Concrete path to a native generated-page capture

The shortest credible full-process path is the original GUI in an isolated
Windows environment backed by a disposable native database. It is not ready
to run under the present no-new-network boundary. Before any launch it needs:

1. A working read-only readiness check for the existing owned Windows runner
   and proof that no unrelated Toolkit process is active.
2. A private Windows profile or another verified isolation mechanism for
   Toolkit preferences, last project/server selection, C-Gate discovery and
   auto-start behavior. A fresh executable directory alone is insufficient.
3. A task-owned C-Gate process/repository containing only an exact synthetic
   project, plus verified guest confinement to that owned loopback service.
   No physical network may be opened. Every synthetic interface must point
   at a task-owned loopback sentinel; any attempted interface connection
   fails acceptance. No existing C-Gate listener or user repository is used.
4. A finite seed containing complete applications, groups, levels and stored
   PP needed by the chosen unit profiles, including otherwise auto-created
   sentinel/Area metadata. Begin with one network, one supported unit and
   plain labels. Record the complete pre-run project snapshot and pinned
   catalogue/unit-spec identities. Seeding is confined to this disposable
   repository and occurs before the observation boundary.
5. A verified UI route to select that exact synthetic project and invoke
   `TProjectNodeHelper.DocumentProject`, or a separately reviewed native
   process harness that creates all required original runtime objects. No
   supported headless Document Project command has been established by this
   investigation.
6. A fresh staging directory for the original `<TagName>.html` output,
   deterministic supervision of the exact owned process tree, and a bounded
   strategy for its automatic local-page viewer. Capture the file bytes
   before cleanup, plus file hash, original timestamp/locale, command trace,
   project pre/post state, process exit and sentinel observations. Never
   retry an uncertain generation in the same evidence directory.

The initial byte comparison must name its concrete synthetic fixture and
compare against the preserved original file, not against strings extracted
from the EXE. An original browser screenshot adds rendering evidence only
for its recorded browser/version/viewport/fonts. It does not establish
device coverage, printing, or visual equivalence across environments.

## Fully offline alternative and its narrower claim

A new network-denied Unicorn harness could execute `OnDocumentHTMLnew` and
the reachable original HTML writers over an explicitly constructed synthetic
object graph. It must allowlist every original span and every provider,
reject unknown calls, bound allocations/instructions, and record all supplied
getters. The least ambiguous first case is an empty-network-manager project,
followed by one network with no units, then one supported unit. Intercepting
`GetAllProjectInfo` or storage/manager calls would make the input an explicit
cached graph, not an original database load.

Such a harness can produce independent original-renderer line evidence
without Windows or any endpoint. If `TStringList.SaveToFile` or the string
runtime is replaced, it cannot claim native file-byte or GUI acceptance.
This investigation did not build or run that harness because the requested
deliverable is full original-page feasibility, and no such result should be
confused with the existing original leaf-method evidence.

The current blockers are therefore concrete: unavailable verified Windows
runner access, unproved original-process preference/network isolation, no
admitted native project-to-documentor construction/UI route, and no captured
original output. Byte and visual parity remain **unassessed**.
