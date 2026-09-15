# Toolkit 1.18 scope census

This is a documentation inventory and implementation map, not a functional coverage report. The complete machine ledger is [toolkit-surface.json](toolkit-surface.json). Rebuild from the locally extracted vendor distribution with `python3 research/census.py`; use `--check` to detect changed sources or stale output and `--self-test` to test the parsers.

The exact Toolkit help navigation contains **3767 topics** in **21 branches**. The C-Gate public reference contains **209 named command blocks**. All have a generic raw CLI forwarding route; **56** have a mapped typed wrapper candidate. Neither count is proof that those workflows work. No acceptance results are imported into this ledger, so all topic and command acceptance states are `unassessed`.

## Counting rules

- One indexed topic is one HHC entry, not one implemented function. Branch pages, tutorials, duplicated model/firmware dialogs and references stay distinct.
- One public command is one named cmds.txt block, including namespace help and comment commands. Grammar alternatives are hashed and source-referenced, not counted as separate features.
- Workflow families use explicitly reviewed HHC subtree roots and intentionally overlap. Their counts must not be summed as a functional denominator.
- Device dialogs are title-based candidates within hardware branches. A differently named editor may require manual review; this list is not a complete dialog-control inventory.
- Raw CLI command forwarding provides a route to the backend; it does not verify command arguments, authorization, responses, hardware effects, or Toolkit workflows.
- Typed wrapper candidates are manually reviewed mappings to existing Python symbols. Source presence is not behavioral verification.
- Every topic and public command starts unassessed. No test result is inferred from source files; no functional coverage percentage is computed.
- A complete parity claim also requires controls/branches in the executable, undocumented/internal commands, external tool boundaries, device/firmware variants and real bus effects beyond this documentation census.
- Only short topic/heading names, product mentions, IDs, paths, line numbers and hashes are emitted. Vendor prose, images and command descriptions remain local.

The 6 HTML files outside the navigation are help-frame/index templates, not six additional established user functions. The JSON records their titles and hashes. Every indexed topic has its navigation ancestry, source file and contents line, HTML title, short headings, anchors, local topic links and source hash.

## Main help branches

| Branch | Topics including branch |
| --- | ---: |
| [Welcome](../research/vendor/toolkit-help/9682.htm) | 6 |
| [Introduction to C-Bus Toolkit](../research/vendor/toolkit-help/108.htm) | 3 |
| [C-Bus concepts](../research/vendor/toolkit-help/4375.htm) | 84 |
| [Getting started](../research/vendor/toolkit-help/392.htm) | 8 |
| [Toolkit at a glance](../research/vendor/toolkit-help/381.htm) | 91 |
| [Toolkit programming functions](../research/vendor/toolkit-help/4637.htm) | 126 |
| [Working with C-Bus Toolkit](../research/vendor/toolkit-help/4635.htm) | 212 |
| [C-Bus wired input units](../research/vendor/toolkit-help/739.htm) | 1078 |
| [C-Bus wired output units](../research/vendor/toolkit-help/740.htm) | 518 |
| [C-Bus wired input/output units](../research/vendor/toolkit-help/13689.htm) | 155 |
| [Wired C-Bus thermostat units](../research/vendor/toolkit-help/2901.htm) | 396 |
| [C-Bus controller units](../research/vendor/toolkit-help/5407.htm) | 31 |
| [C-Bus automation controller units](../research/vendor/toolkit-help/16300.htm) | 7 |
| [Wired support units](../research/vendor/toolkit-help/1056.htm) | 64 |
| [Wireless C-Bus units](../research/vendor/toolkit-help/693.htm) | 73 |
| [Wired Multi Room Audio units](../research/vendor/toolkit-help/1765.htm) | 33 |
| [Tutorials](../research/vendor/toolkit-help/691.htm) | 83 |
| [C-Bus macro function reference](../research/vendor/toolkit-help/1519.htm) | 206 |
| [Unit type reference](../research/vendor/toolkit-help/1945.htm) | 590 |
| [Error messages](../research/vendor/toolkit-help/15411.htm) | 2 |
| [Glossary of Terms](../research/vendor/toolkit-help/181.htm) | 1 |

## Toolkit navigation and menu

These are the actual navigation-tree and main-menu help subtrees.

- [C-Bus Toolkit navigation treeview](../research/vendor/toolkit-help/6536.htm)
  - [C-Bus projects node](../research/vendor/toolkit-help/376.htm)
    - [C-Bus projects toolbar](../research/vendor/toolkit-help/397.htm)
  - [Project node](../research/vendor/toolkit-help/378.htm)
    - [Project toolbar](../research/vendor/toolkit-help/409.htm)
    - [Project window](../research/vendor/toolkit-help/479.htm)
  - [Network node](../research/vendor/toolkit-help/407.htm)
    - [Network toolbar](../research/vendor/toolkit-help/410.htm)
    - [Network window](../research/vendor/toolkit-help/426.htm)
  - [Application log node](../research/vendor/toolkit-help/767.htm)
    - [Application log toolbar](../research/vendor/toolkit-help/425.htm)
    - [Application log window](../research/vendor/toolkit-help/419.htm)
      - [Example of log node output](../research/vendor/toolkit-help/1789.htm)
  - [Applications node](../research/vendor/toolkit-help/15827.htm)
    - [Applications toolbars](../research/vendor/toolkit-help/417.htm)
      - [Application toolbar](../research/vendor/toolkit-help/15818.htm)
      - [Application window](../research/vendor/toolkit-help/418.htm)
      - [(Applications) group toolbar](../research/vendor/toolkit-help/15819.htm)
      - [Group level toolbar](../research/vendor/toolkit-help/15820.htm)
      - [Group control and other buttons](../research/vendor/toolkit-help/15821.htm)
  - [Lighting application node](../research/vendor/toolkit-help/15747.htm)
    - [Lighting application toolbar](../research/vendor/toolkit-help/15748.htm)
    - [Lighting application window](../research/vendor/toolkit-help/15749.htm)
  - [Lighting groups node](../research/vendor/toolkit-help/422.htm)
    - [Lighting groups toolbar](../research/vendor/toolkit-help/491.htm)
    - [Lighting groups window](../research/vendor/toolkit-help/486.htm)
  - [Lighting level node](../research/vendor/toolkit-help/6766.htm)
    - [Lighting level toolbar](../research/vendor/toolkit-help/6767.htm)
    - [Lighting level window](../research/vendor/toolkit-help/6768.htm)
  - [Other Lighting Compatible group nodes](../research/vendor/toolkit-help/7207.htm)
    - [DALI node](../research/vendor/toolkit-help/7209.htm)
    - [Pool, Spas and Ponds node](../research/vendor/toolkit-help/7210.htm)
    - [HVAC Actuator node](../research/vendor/toolkit-help/7211.htm)
    - [Irrigation Control node](../research/vendor/toolkit-help/7212.htm)
    - [Ventilation Control node](../research/vendor/toolkit-help/7213.htm)
    - [Heating node](../research/vendor/toolkit-help/421.htm)
  - [Enable Control application node](../research/vendor/toolkit-help/15750.htm)
    - [Enable Control toolbar](../research/vendor/toolkit-help/15751.htm)
    - [Enable Control window](../research/vendor/toolkit-help/15752.htm)
  - [Enable network variables node](../research/vendor/toolkit-help/449.htm)
    - [Enable network variables toolbar](../research/vendor/toolkit-help/450.htm)
    - [Enable network variables window](../research/vendor/toolkit-help/810.htm)
  - [Enable network variable value node](../research/vendor/toolkit-help/6762.htm)
    - [Enable network variable value toolbar](../research/vendor/toolkit-help/6760.htm)
    - [Enable network variable value window](../research/vendor/toolkit-help/6761.htm)
  - [Trigger Control application node](../research/vendor/toolkit-help/15753.htm)
    - [Trigger Control toolbar](../research/vendor/toolkit-help/15754.htm)
    - [Trigger Control window](../research/vendor/toolkit-help/15755.htm)
  - [Trigger groups node](../research/vendor/toolkit-help/768.htm)
    - [Trigger groups toolbar](../research/vendor/toolkit-help/453.htm)
    - [Trigger groups window](../research/vendor/toolkit-help/452.htm)
  - [Trigger Control action selector node](../research/vendor/toolkit-help/6763.htm)
    - [Action selector toolbar](../research/vendor/toolkit-help/6764.htm)
    - [Action selector window](../research/vendor/toolkit-help/6765.htm)
  - [Units node](../research/vendor/toolkit-help/408.htm)
    - [Units in Database toolbar](../research/vendor/toolkit-help/412.htm)
    - [Units in Database window](../research/vendor/toolkit-help/411.htm)
    - [Units on Network window](../research/vendor/toolkit-help/20100.htm)
      - [Units in Network quick view window](../research/vendor/toolkit-help/20101.htm)
      - [Units in Network summary view window](../research/vendor/toolkit-help/413.htm)
  - [Topological node](../research/vendor/toolkit-help/379.htm)
    - [Topological toolbar](../research/vendor/toolkit-help/415.htm)
    - [Topological window](../research/vendor/toolkit-help/416.htm)

- [C-Bus Toolkit Main Menu section](../research/vendor/toolkit-help/6861.htm)
  - [File menu](../research/vendor/toolkit-help/6802.htm)
    - [Connect to local C-Gate option](../research/vendor/toolkit-help/6803.htm)
    - [Connect to a remote C-Gate option](../research/vendor/toolkit-help/6807.htm)
      - [Manipulating existing remote C-Gate connection](../research/vendor/toolkit-help/6808.htm)
      - [Setting up a new remote projects connection](../research/vendor/toolkit-help/6804.htm)
    - [Disconnect from C-Gate](../research/vendor/toolkit-help/6805.htm)
    - [Set default interface option](../research/vendor/toolkit-help/6816.htm)
    - [Preference options](../research/vendor/toolkit-help/5703.htm)
      - [Features tab](../research/vendor/toolkit-help/5704.htm)
      - [Behaviour tab](../research/vendor/toolkit-help/5705.htm)
      - [Units dialog tab](../research/vendor/toolkit-help/5706.htm)
      - [Advanced tab](../research/vendor/toolkit-help/5707.htm)
      - [Compatibility tab](../research/vendor/toolkit-help/5708.htm)
      - [C-Bus tag names tab](../research/vendor/toolkit-help/5709.htm)
    - [Restore projects... menu option](../research/vendor/toolkit-help/6821.htm)
    - [Backup Projects... menu option](../research/vendor/toolkit-help/6822.htm)
  - [Projects menu options](../research/vendor/toolkit-help/6835.htm)
    - [Add project option](../research/vendor/toolkit-help/6836.htm)
    - [Delete project option](../research/vendor/toolkit-help/6837.htm)
    - [Find C-Bus Networks... option](../research/vendor/toolkit-help/6839.htm)
    - [Repair project option](../research/vendor/toolkit-help/11083.htm)
    - [Refresh option](../research/vendor/toolkit-help/6840.htm)
    - [Import projects option](../research/vendor/toolkit-help/6841.htm)
    - [Export projects option](../research/vendor/toolkit-help/6842.htm)
  - [Go menu options](../research/vendor/toolkit-help/6849.htm)
  - [Help menu options](../research/vendor/toolkit-help/1300.htm)

## Workflow families

Families overlap. Root topic links establish why each family is in scope; the JSON contains all member topic IDs. Each still needs a testable behavioral specification.

| Family | Topics | Evidence roots |
| --- | ---: | --- |
| Project lifecycle and backup | 30 | [C-Bus projects functions](../research/vendor/toolkit-help/4639.htm); [Project functions](../research/vendor/toolkit-help/4641.htm); [Working with C-Bus projects](../research/vendor/toolkit-help/7281.htm) |
| Network configuration and connections | 61 | [Network functions](../research/vendor/toolkit-help/4634.htm); [Working with networks](../research/vendor/toolkit-help/4663.htm) |
| Applications, groups and levels | 100 | [Applications functions](../research/vendor/toolkit-help/4606.htm); [Working with applications](../research/vendor/toolkit-help/4653.htm); [Working with lighting type groups](../research/vendor/toolkit-help/4657.htm); [Working with lighting based groups](../research/vendor/toolkit-help/4659.htm); [Enable network variable functions](../research/vendor/toolkit-help/6599.htm); [Enable network variable values functions](../research/vendor/toolkit-help/15928.htm); [Lighting Type group functions](../research/vendor/toolkit-help/5711.htm); [Lighting Type level functions](../research/vendor/toolkit-help/5716.htm); [Trigger group functions](../research/vendor/toolkit-help/6613.htm); [Action selector functions](../research/vendor/toolkit-help/5735.htm) |
| Application log | 11 | [Application log functions](../research/vendor/toolkit-help/4608.htm); [Application log node](../research/vendor/toolkit-help/767.htm) |
| Database unit lifecycle | 50 | [Units in database functions](../research/vendor/toolkit-help/4645.htm); [Working with units from the database view](../research/vendor/toolkit-help/4757.htm) |
| Physical unit commissioning and addressing | 37 | [Units on network functions](../research/vendor/toolkit-help/4647.htm); [Working with units from existing network installations](../research/vendor/toolkit-help/4763.htm) |
| Global programming | 7 | [Global programming function](../research/vendor/toolkit-help/4359.htm); [Global programming functions](../research/vendor/toolkit-help/16943.htm) |
| Unit templates | 6 | [Save template function](../research/vendor/toolkit-help/16945.htm); [Load template function](../research/vendor/toolkit-help/16946.htm); [Saving and loading programming templates](../research/vendor/toolkit-help/16988.htm) |
| Unit conversion | 7 | [Convert units function](../research/vendor/toolkit-help/4358.htm); [Converting units](../research/vendor/toolkit-help/1843.htm) |
| Dynamic labels | 26 | [DLT labels function](../research/vendor/toolkit-help/4321.htm); [Working with dynamic labels](../research/vendor/toolkit-help/9118.htm) |
| Scene programming | 20 | [Using C-Bus scenes](../research/vendor/toolkit-help/763.htm) |
| Timer programming | 6 | [Using timers within key input units](../research/vendor/toolkit-help/744.htm) |
| Relay and dimmer logic control | 11 | [Working with logic control](../research/vendor/toolkit-help/9433.htm) |
| Thermostat scheduling | 9 | [Programming the C-Bus thermostat scheduler](../research/vendor/toolkit-help/2782.htm); [About the scheduler](../research/vendor/toolkit-help/2791.htm); [Setting a scheduled off period](../research/vendor/toolkit-help/7036.htm) |
| Key macro and micro functions | 216 | [C-Bus macro function reference](../research/vendor/toolkit-help/1519.htm); [Customising macro commands for special effects](../research/vendor/toolkit-help/12109.htm); [Programming with input keys](../research/vendor/toolkit-help/14036.htm) |
| Wireless units and commissioning | 81 | [Wireless C-Bus units](../research/vendor/toolkit-help/693.htm); [About join mode](../research/vendor/toolkit-help/13994.htm) |
| Controller integration | 38 | [C-Bus controller units](../research/vendor/toolkit-help/5407.htm); [C-Bus automation controller units](../research/vendor/toolkit-help/16300.htm) |
| Automation controller CGL exchange | 4 | [Export CGL dialog box](../research/vendor/toolkit-help/16305.htm); [Import CGL dialog box](../research/vendor/toolkit-help/16306.htm); [Export CGL function](../research/vendor/toolkit-help/16307.htm); [Import CGL function](../research/vendor/toolkit-help/16308.htm) |
| Project, database and topology documentation | 5 | [Document project function](../research/vendor/toolkit-help/4317.htm); [Generating information about the project](../research/vendor/toolkit-help/7294.htm); [Document Database function](../research/vendor/toolkit-help/4357.htm); [Print function](../research/vendor/toolkit-help/4604.htm); [Copy image function](../research/vendor/toolkit-help/4601.htm) |
| Topology navigation | 9 | [Topological functions](../research/vendor/toolkit-help/4649.htm); [Topological node](../research/vendor/toolkit-help/379.htm) |
| eDLT firmware update | 1 | [Updating firmware via Toolkit](../research/vendor/toolkit-help/19096.htm) |
| Network diagnosis and recovery | 9 | [Resolving network issues](../research/vendor/toolkit-help/20144.htm); [Diagnosing units on a network](../research/vendor/toolkit-help/20132.htm); [Diagnostic function](../research/vendor/toolkit-help/20136.htm); [Recovering from electrical load or C-Bus signal loss](../research/vendor/toolkit-help/11808.htm) |
| Barcode scanner workflow | 7 | [C-Bus Barcode scanner](../research/vendor/toolkit-help/4590.htm) |
| C-Bus application concepts and messages | 84 | [C-Bus concepts](../research/vendor/toolkit-help/4375.htm) |
| Unit type reference | 590 | [Unit type reference](../research/vendor/toolkit-help/1945.htm) |
| Device configuration and device operation | 2355 | [C-Bus wired input units](../research/vendor/toolkit-help/739.htm); [C-Bus wired output units](../research/vendor/toolkit-help/740.htm); [C-Bus wired input/output units](../research/vendor/toolkit-help/13689.htm); [Wired C-Bus thermostat units](../research/vendor/toolkit-help/2901.htm); [C-Bus controller units](../research/vendor/toolkit-help/5407.htm); [C-Bus automation controller units](../research/vendor/toolkit-help/16300.htm); [Wired support units](../research/vendor/toolkit-help/1056.htm); [Wireless C-Bus units](../research/vendor/toolkit-help/693.htm); [Wired Multi Room Audio units](../research/vendor/toolkit-help/1765.htm) |

## Prioritized unresolved acceptance

These are open scope items, not an automated assertion that their entire implementation is missing.

- **P0: Resolve each device dialog's fields, dependencies and native serialization.** Map each dialog control to an exact unit type/firmware parameter or command; test valid and invalid settings, roundtrip serialization and preservation of unrelated values. Generic PP get/set and catalogue creation do not verify a dialog's full semantics.

- **P0: Test commissioning against observable network behavior.** Implement and verify scan, unravel, serial-number readdressing, database/network reconciliation, transfer and recovery workflows with a faithful simulator or hardware fixtures. A closed-network backend acceptance cannot verify bus effects.

- **P1: Implement scene, macro and timer workflows.** Resolve native tables, sequencing, capacity limits and interdependent parameters, then compare generated programming and simulated behavior with vendor outcomes for each applicable device family.

- **P1: Verify dynamic labels and global programming.** Cover label encodings and language variants, eDLT widgets/standby/colour settings, bulk selection, partial failure reporting and preservation of per-unit differences.

- **P1: Verify vendor template exchange and unit conversion.** Compare Toolkit template files and conversion results, including compatible parameter transfer, defaults, unsupported fields and identity/address handling. A custom parameter export is not proof of the vendor template format.

- **P1: Resolve and test the eDLT firmware updater workflow.** Inventory the separate updater's inputs and protocol, version compatibility, staged transfer and recovery. The help topic establishes this surface; this ledger does not verify an implementation.

- **P1: Complete project exchange and documentation acceptance.** Exercise vendor backups/restores, CGL import/export, project/database documentation and topology operations with comparable expected outputs, preserving identities and reference integrity.

- **P2: Verify thermostat scheduling and wireless behavior.** Test schedules, zones, learn/join behavior and gateway mappings on the relevant devices. Determine which controller programming is delegated to external applications before expanding Toolkit scope.

- **P2: Verify remaining C-Gate application commands and configuration.** Turn public command grammar variants into positive/negative acceptance cases, including monitoring and event streams. Keep reference-only protocol topics separate from Toolkit editors.

- **P2: Resolve scanner input and identification behavior.** Specify scanner payloads, input handling and resulting project/unit selection or creation using vendor evidence; generic string input is insufficient evidence.

## Boundaries requiring explicit decisions

- These controller dialog topics identify PICED as the programming application. Define integration versus external-application scope before claiming controller editor parity. Evidence: [MK2 Black and White Touch Screen with logic engine configuration dialog box](../research/vendor/toolkit-help/5414.htm); [Colour C-Touch Screen configuration dialog box](../research/vendor/toolkit-help/13447.htm).
- Security is documented as an application/message reference; this evidence does not establish a Toolkit security-system editor. Evidence: [Security application](../research/vendor/toolkit-help/12335.htm); [Security application messages](../research/vendor/toolkit-help/12336.htm); [Security system control messages](../research/vendor/toolkit-help/12338.htm).
- The navigation explicitly documents thermostat scheduling; this does not establish a standalone general scheduler. Evidence: [Programming the C-Bus thermostat scheduler](../research/vendor/toolkit-help/2782.htm); [About the scheduler](../research/vendor/toolkit-help/2791.htm); [Setting a scheduled off period](../research/vendor/toolkit-help/7036.htm).
- Relay/dimmer logic control is an explicit Toolkit workflow; controller logic-engine code editing may belong to external software. Evidence: [Working with logic control](../research/vendor/toolkit-help/9433.htm); [Logic control for C-Bus dimmers](../research/vendor/toolkit-help/9855.htm); [Logic control for C-Bus relays](../research/vendor/toolkit-help/9858.htm).
- Firmware updating is explicitly documented for the eDLT updater; other device updater scope needs separate evidence. Evidence: [Updating firmware via Toolkit](../research/vendor/toolkit-help/19096.htm).

## Device dialog candidates

The hardware branches contain **118 configuration-dialog candidates** selected by their exact topic names. Model and firmware variants remain separate even when titles repeat. This inventory is a starting point for control-by-control parity; generic parameter editing is not a substitute for that assessment. The JSON lists each dialog's descendant topic IDs and direct child tabs. The separate unit catalogue contains 577 unit records, 3750 revision records and 271 unit types; none of these counts establish device acceptance.

| Dialog | Parent context | Subtree topics |
| --- | --- | ---: |
| [4 channel auxiliary input unit configuration dialog box](../research/vendor/toolkit-help/11068.htm) | C-Bus auxiliary input units / 4 channel auxiliary input unit | 7 |
| [4 channel DIN rail auxiliary input unit (DINAUX4) configuration dialog box](../research/vendor/toolkit-help/11057.htm) | C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (DINAUX4) | 7 |
| [4 channel DIN rail auxiliary input unit (BCI4A) configuration dialog box](../research/vendor/toolkit-help/11037.htm) | C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (BCI4A) | 11 |
| [Decorator style 1 key input unit configuration dialog box](../research/vendor/toolkit-help/9286.htm) | C-Bus Decorator input units / Decorator style 1 key input unit | 11 |
| [Decorator style 2 key input unit configuration dialog box](../research/vendor/toolkit-help/9287.htm) | C-Bus Decorator input units / Decorator style 2 key input unit | 11 |
| [Decorator style 3 key input unit configuration dialog box](../research/vendor/toolkit-help/9289.htm) | C-Bus Decorator input units / Decorator style 3 key input unit | 11 |
| [Decorator style 4 key input unit configuration dialog box](../research/vendor/toolkit-help/9290.htm) | C-Bus Decorator input units / Decorator style 4 key input unit | 11 |
| [Saturn style 5 key DLT input unit configuration dialog box](../research/vendor/toolkit-help/9205.htm) | Dynamic Labelling Technology (DLT) key input units / Saturn style 5 key DLT input unit | 11 |
| [Neo style 5 key DLT input unit configuration dialog box](../research/vendor/toolkit-help/9209.htm) | Dynamic Labelling Technology (DLT) key input units / Neo style 5 key DLT input unit | 11 |
| [Decorator style 4 key DLT input unit configuration dialog box](../research/vendor/toolkit-help/9210.htm) | Dynamic Labelling Technology (DLT) key input units / Decorator style 4 key DLT input unit | 11 |
| [eDLT configuration dialog box](../research/vendor/toolkit-help/18865.htm) | Wired key input units / eDLT key input unit | 8 |
| [Saturn Zen key input unit configuration dialog box](../research/vendor/toolkit-help/19973.htm) | Saturn Zen series / 1 Key Saturn Zen key input unit | 11 |
| [Saturn Zen key input unit configuration dialog box](../research/vendor/toolkit-help/19973_1.htm) | Saturn Zen series / 2 Key Saturn Zen key input unit | 11 |
| [Saturn Zen key input unit configuration dialog box](../research/vendor/toolkit-help/19973_2.htm) | Saturn Zen series / 3 Key Saturn Zen key input unit | 11 |
| [Saturn Zen key input unit configuration dialog box](../research/vendor/toolkit-help/19973_3.htm) | Saturn Zen series / 4 Key Saturn Zen key input unit | 11 |
| [Saturn Zen NCC key input unit configuration dialog box](../research/vendor/toolkit-help/40007.htm) | Saturn Zen series / Saturn Zen NCC key input unit | 3 |
| [Avanti style 1 key input unit configuration dialog box](../research/vendor/toolkit-help/9294.htm) | Avanti style key input units / Avanti style 1 key input unit | 11 |
| [Avanti style 2 key input unit configuration dialog box](../research/vendor/toolkit-help/9300.htm) | Avanti style key input units / Avanti style 2 key input unit | 11 |
| [Avanti style 3 key input unit configuration dialog box](../research/vendor/toolkit-help/9301.htm) | Avanti style key input units / Avanti style 3 key input unit | 11 |
| [2 key Modena style key input unit configuration dialog box](../research/vendor/toolkit-help/8449.htm) | Modena style key input unit / 2 key Modena style key input unit | 11 |
| [4 key Modena style key input unit configuration dialog box](../research/vendor/toolkit-help/8463.htm) | Modena style key input unit / 4 key Modena style key input unit | 11 |
| [6 key Modena style key input unit configuration dialog box](../research/vendor/toolkit-help/8476.htm) | Modena style key input unit / 6 key Modena style key input unit | 11 |
| [Neo style 2 key input unit configuration dialog box](../research/vendor/toolkit-help/9302.htm) | Neo style key input units / Neo style 2 key input unit | 11 |
| [Neo style 4 key input unit configuration dialog box](../research/vendor/toolkit-help/9303.htm) | Neo style key input units / Neo style 4 key input unit | 11 |
| [Neo style 8 key input unit configuration dialog box](../research/vendor/toolkit-help/9304.htm) | Neo style key input units / Neo style 8 key input unit | 11 |
| [Reflection style 1 key input unit configuration dialog box](../research/vendor/toolkit-help/9305.htm) | Reflection style key input units / Reflection style 1 key input unit | 11 |
| [Reflection style 3 key input unit configuration dialog box](../research/vendor/toolkit-help/9311.htm) | Reflection style key input units / Reflection style 3 key input unit | 11 |
| [Reflection style 6 key input unit configuration dialog box](../research/vendor/toolkit-help/9312.htm) | Reflection style key input units / Reflection style 6 key input unit | 11 |
| [Reflection style 8 key input unit configuration dialog box](../research/vendor/toolkit-help/9313.htm) | Reflection style key input units / Reflection style 8 key input unit | 11 |
| [Reflection style 2 key vertical input unit configuration dialog box](../research/vendor/toolkit-help/9314.htm) | Reflection style key input units / Reflection style 2 key vertical input unit | 11 |
| [Reflection style 4 key vertical input unit configuration dialog box](../research/vendor/toolkit-help/9315.htm) | Reflection style key input units / Reflection style 4 key vertical input unit | 11 |
| [Saturn style 2 key input unit configuration dialog box](../research/vendor/toolkit-help/9318.htm) | Saturn style key input units / Saturn style 2 key input unit | 11 |
| [Saturn style 4 key input unit configuration dialog box](../research/vendor/toolkit-help/9319.htm) | Saturn style key input units / Saturn style 4 key input unit | 11 |
| [Saturn style 6 key input unit configuration dialog box](../research/vendor/toolkit-help/9320.htm) | Saturn style key input units / Saturn style 6 key input unit | 11 |
| [Saturn style NCC key input unit configuration dialog box](../research/vendor/toolkit-help/40001.htm) | Saturn style key input units / Saturn style NCC key input unit | 3 |
| [1 key Standard input unit configuration dialog box](../research/vendor/toolkit-help/8113.htm) | Standard KEYC series / 1 key Standard input unit | 9 |
| [2 key Standard input unit configuration dialog box](../research/vendor/toolkit-help/8122.htm) | Standard KEYC series / 2 key Standard input unit | 9 |
| [4 key Standard input unit configuration dialog box](../research/vendor/toolkit-help/8132.htm) | Standard KEYC series / 4 key Standard input unit | 9 |
| [1 key Infra Red Standard input unit configuration dialog box](../research/vendor/toolkit-help/8142.htm) | Standard KEYC series / 1 key Infra Red Standard input unit | 8 |
| [4 key Infra Red Standard input unit configuration dialog box](../research/vendor/toolkit-help/8151.htm) | Standard KEYC series / 4 key Infra Red Standard input unit | 9 |
| [Vieo style 1 key input unit configuration dialog box](../research/vendor/toolkit-help/9905.htm) | Vieo key input unit / Vieo style 1 key input unit | 11 |
| [Vieo style 2 key input unit configuration dialog box](../research/vendor/toolkit-help/9926.htm) | Vieo key input unit / Vieo style 2 key input unit | 11 |
| [Vieo style 3 key input unit configuration dialog box](../research/vendor/toolkit-help/9938.htm) | Vieo key input unit / Vieo style 3 key input unit | 11 |
| [30M 1 key input unit configuration dialog box](../research/vendor/toolkit-help/9967.htm) | 30M series key input units / 30M 1 key input unit | 11 |
| [30M 2 key input unit configuration dialog box](../research/vendor/toolkit-help/9990.htm) | 30M series key input units / 30M 2 key input unit | 11 |
| [30M 3 key input unit configuration dialog box](../research/vendor/toolkit-help/10004.htm) | 30M series key input units / 30M 3 key input unit | 11 |
| [30M 4 key input unit configuration dialog box](../research/vendor/toolkit-help/10018.htm) | 30M series key input units / 30M 4 key input unit | 11 |
| [30M infra red 1 key input unit configuration dialog box](../research/vendor/toolkit-help/10032.htm) | 30M series key input units / 30M infra red 1 key input unit | 11 |
| [30M infra red 2 key input unit configuration dialog box](../research/vendor/toolkit-help/10046.htm) | 30M series key input units / 30M infra red 2 key input unit | 11 |
| [30M infra red 3 key input unit configuration dialog box](../research/vendor/toolkit-help/10059.htm) | 30M series key input units / 30M infra red 3 key input unit | 11 |
| [30M infra red 4 key input unit configuration dialog box](../research/vendor/toolkit-help/10072.htm) | 30M series key input units / 30M infra red 4 key input unit | 11 |
| [40M 1 key input unit configuration dialog box](../research/vendor/toolkit-help/30004.htm) | 40M series key input units / 40M 1 key input unit | 11 |
| [40M 2 key input unit configuration dialog box](../research/vendor/toolkit-help/30016.htm) | 40M series key input units / 40M 2 key input unit | 11 |
| [40M 3 key input unit configuration dialog box](../research/vendor/toolkit-help/30028.htm) | 40M series key input units / 40M 3 key input unit | 11 |
| [40M 4 key input unit configuration dialog box](../research/vendor/toolkit-help/30040.htm) | 40M series key input units / 40M 4 key input unit | 11 |
| [Two channel bus coupler configuration dialog box](../research/vendor/toolkit-help/4455.htm) | C-Bus bus coupler input units / Two channel bus coupler | 11 |
| [Four channel bus coupler configuration dialog box](../research/vendor/toolkit-help/4457.htm) | C-Bus bus coupler input units / Four channel bus coupler | 11 |
| [4 channel auxiliary input unit configuration dialog box](../research/vendor/toolkit-help/11068_1.htm) | C-Bus auxiliary input units / 4 channel auxiliary input unit | 7 |
| [4 channel DIN rail auxiliary input unit (DINAUX4) configuration dialog box](../research/vendor/toolkit-help/11057_1.htm) | C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (DINAUX4) | 7 |
| [4 channel DIN rail auxiliary input unit (BCI4A) configuration dialog box](../research/vendor/toolkit-help/11037_1.htm) | C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (BCI4A) | 11 |
| [Passive infra red Occupancy Detector (1.2.67) configuration dialog box](../research/vendor/toolkit-help/10112.htm) | Passive infra red Occupancy Detectors / Passive infra red Occupancy Detector (1.2.67) | 7 |
| [Passive infra red Occupancy Detector (2.4.00) configuration dialog box](../research/vendor/toolkit-help/19832.htm) | Passive infra red Occupancy Detectors / Passive infra red Occupancy Detector (2.4.00) | 9 |
| [Multi Sensor configuration dialog box](../research/vendor/toolkit-help/11087.htm) | Wired C-Bus sensors and detectors / Multi Sensor | 13 |
| [Configuration dialog box](../research/vendor/toolkit-help/15007.htm) | Wired C-Bus sensors and detectors / Light level sensor | 9 |
| [Configuration dialog box](../research/vendor/toolkit-help/9722.htm) | Light level sensor / Light level sensor (firmware 1.00) | 5 |
| [5031RDTSL Temperature Sensor configuration dialog box](../research/vendor/toolkit-help/5239.htm) | Wired C-Bus sensors and detectors / Remote Digital Temperature Sensor (5031RDTSL) | 8 |
| [Current Measurement Unit configuration dialog box](../research/vendor/toolkit-help/14934.htm) | Wired C-Bus sensors and detectors / Current Measurement Unit | 9 |
| [Detector configuration dialog box](../research/vendor/toolkit-help/17704.htm) | Wired C-Bus sensors and detectors / Light Level Detector (5754PE) | 14 |
| [Occupancy/Light Level Detector configuration dialog box](../research/vendor/toolkit-help/17742.htm) | Wired C-Bus sensors and detectors / Occupancy/Light Level Detector (5754ODPE) | 14 |
| [Occupancy/Light Level Detector with IR configuration dialog box](../research/vendor/toolkit-help/17544.htm) | Wired C-Bus sensors and detectors / Occupancy/Light Level Detector with IR (5754ODPEIR) | 14 |
| [General input unit configuration dialog box](../research/vendor/toolkit-help/8321.htm) | C-Bus wired input units / General input unit | 11 |
| [Single channel shutter relay configuration dialog box](../research/vendor/toolkit-help/5116.htm) | Relays / Single channel shutter relay | 7 |
| [DIN rail four channel change over voltage free relay unit configuration dialog box](../research/vendor/toolkit-help/9728.htm) | Relays / DIN rail four channel change over voltage free relay unit | 10 |
| [DIN rail four (4) channel relay configuration dialog box](../research/vendor/toolkit-help/9792.htm) | Relays / DIN rail four (4) channel relay | 10 |
| [DIN rail 8 channel voltage free relay configuration dialog box](../research/vendor/toolkit-help/9808.htm) | Relays / DIN rail 8 channel voltage free relay (RELDN8) | 10 |
| [DIN rail 8 channel voltage free relay configuration dialog box](../research/vendor/toolkit-help/9824.htm) | Relays / DIN rail 8 channel voltage free relay (RELDN8B) | 10 |
| [DIN rail 12 channel voltage free relay unit configuration dialog box](../research/vendor/toolkit-help/9838.htm) | Relays / DIN rail 12 channel voltage free relay unit | 10 |
| [8 channel ELV relay configuration dialog box](../research/vendor/toolkit-help/10157.htm) | Relays / 8 channel ELV relay | 7 |
| [C-Bus ceiling sweep fan controller configuration dialog box](../research/vendor/toolkit-help/12403.htm) | Relays / C-Bus ceiling sweep fan controller | 8 |
| [4 channel standard dimmer configuration dialog box](../research/vendor/toolkit-help/9688.htm) | Dimmers / 4 channel standard dimmer | 7 |
| [4 channel DIN rail dimmer configuration dialog box](../research/vendor/toolkit-help/9702.htm) | Dimmers / 4 channel DIN rail dimmer | 9 |
| [8 channel DIN rail dimmer configuration dialog box](../research/vendor/toolkit-help/9646.htm) | Dimmers / 8 channel DIN rail dimmer | 9 |
| [C-Bus Universal dimmer configuration dialog box](../research/vendor/toolkit-help/5199.htm) | Dimmers / C-Bus Universal dimmer | 11 |
| [3 channel architectural dimmer configuration dialog box](../research/vendor/toolkit-help/8064.htm) | Dimmers / 3 channel architectural dimmer | 18 |
| [6 channel architectural dimmer configuration dialog box](../research/vendor/toolkit-help/8081.htm) | Dimmers / 6 channel architectural dimmer | 18 |
| [1 channel professional dimmer configuration dialog box](../research/vendor/toolkit-help/12053.htm) | Dimmers / 1 channel professional dimmer | 8 |
| [2 channel professional dimmer configuration dialog box](../research/vendor/toolkit-help/12064.htm) | Dimmers / 2 channel professional dimmer | 8 |
| [4 channel professional dimmer configuration dialog box](../research/vendor/toolkit-help/12074.htm) | Dimmers / 4 channel professional dimmer | 8 |
| [12 channel architectural dimmer configuration dialog box](../research/vendor/toolkit-help/7887.htm) | Dimmers / 12 channel architectural dimmer | 18 |
| [3 channel professional dimmer configuration dialog box](../research/vendor/toolkit-help/5213.htm) | Dimmers / 3 channel professional dimmer | 11 |
| [6 channel professional dimmer configuration dialog box](../research/vendor/toolkit-help/5321.htm) | Dimmers / 6 channel professional dimmer | 11 |
| [12 channel professional dimmer configuration dialog box](../research/vendor/toolkit-help/5296.htm) | Dimmers / 12 channel professional dimmer | 11 |
| [DIN rail four channel analog output unit configuration dialog box](../research/vendor/toolkit-help/12090.htm) | C-Bus wired output units / DIN rail four channel analog output unit | 7 |
| [8 channel DSI Gateway configuration dialog box](../research/vendor/toolkit-help/9617.htm) | C-Bus wired output units / 8 channel DSI Gateway | 9 |
| [C-Bus to DMX One Way Gateway configuration dialog box](../research/vendor/toolkit-help/11739.htm) | C-Bus wired output units / C-Bus to DMX One Way Gateway | 7 |
| [Occupancy Controller (1 sensor, 1 relay) configuration dialog box](../research/vendor/toolkit-help/14052.htm) | C-Bus wired input/output units / Occupancy Controller (1 sensor, 1 relay) | 23 |
| [Occupancy Controller (2 sensors, 2 relays) configuration dialog box](../research/vendor/toolkit-help/14054.htm) | C-Bus wired input/output units / Occupancy Controller (2 sensors, 2 relays) | 23 |
| [Occupancy Controller (2 sensors, 2 relays, 2 dimmers) configuration dialog box](../research/vendor/toolkit-help/14053.htm) | C-Bus wired input/output units / Occupancy Controller (2 sensors, 2 relays, 2 dimmers) | 23 |
| [C-Bus programmable thermostat configuration dialog box](../research/vendor/toolkit-help/3850.htm) | Introduction to the C-Bus thermostat / C-Bus thermostat configuration | 1 |
| [C-Bus single zone thermostat configuration dialog box](../research/vendor/toolkit-help/3851.htm) | Introduction to the C-Bus thermostat / C-Bus thermostat configuration | 1 |
| [MK2 Black and White Touch Screen configuration dialog box](../research/vendor/toolkit-help/5392.htm) | C-Bus controller units / MK2 Black and White Touch Screen | 4 |
| [MK2 Black and White Touch Screen with logic engine configuration dialog box](../research/vendor/toolkit-help/5414.htm) | C-Bus controller units / MK2 Black and White Touch Screen with logic engine | 4 |
| [Colour C-Touch Screen configuration dialog box](../research/vendor/toolkit-help/13447.htm) | C-Bus controller units / Colour C-Touch Screen | 4 |
| [Spectrum colour touch screen configuration dialog box](../research/vendor/toolkit-help/13617.htm) | C-Bus controller units / Spectrum colour touch screen | 4 |
| [Spectrum colour touch screen with logic engine configuration dialog box](../research/vendor/toolkit-help/13623.htm) | C-Bus controller units / Spectrum colour touch screen with logic engine | 4 |
| [Pascal Automation Controller configuration dialog box](../research/vendor/toolkit-help/15488.htm) | C-Bus controller units / Pascal Automation Controller | 4 |
| [C-Bus automation controller configuration dialog box](../research/vendor/toolkit-help/16301.htm) | C-Bus automation controller units | 4 |
| [PC interface configuration dialog box](../research/vendor/toolkit-help/10747.htm) | Wired network units / PC interface units | 4 |
| [Inline CNI interface (5100CN2) configuration dialog box](../research/vendor/toolkit-help/10383.htm) | Wired network units / Inline CNI interface (5100CN2) | 4 |
| [C-Bus bridges configuration dialog box](../research/vendor/toolkit-help/10751.htm) | Wired network units / C-Bus bridges | 5 |
| [DALI Gateway configuration dialog box](../research/vendor/toolkit-help/1403.htm) | Wired support units / C-Bus DALI Gateway | 5 |
| [C-Bus 7 Day Clock configuration dialog box](../research/vendor/toolkit-help/15426.htm) | Wired support units / C-Bus 7 Day Clock | 8 |
| [C-Bus infrared transmitter configuration dialog box](../research/vendor/toolkit-help/2215.htm) | Wired support units / C-Bus infrared transmitter | 3 |
| [C-Bus telephone interface configuration dialog box](../research/vendor/toolkit-help/5532.htm) | Wired support units / C-Bus telephone interface | 3 |
| [Decorator wireless input/output unit configuration dialog box](../research/vendor/toolkit-help/12558.htm) | Wireless C-Bus units / Decorator wireless input/output units | 15 |
| [C-Bus wireless to wired gateway configuration dialog box](../research/vendor/toolkit-help/13872.htm) | Wireless C-Bus units / C-Bus wireless to wired gateway | 5 |
| [C-Bus Wireless to wired gateway (2.x) configuration dialog box](../research/vendor/toolkit-help/13876.htm) | Wireless C-Bus units / C-Bus Wireless to wired gateway (2.x) | 10 |
| [MRA amplifier configuration dialog box](../research/vendor/toolkit-help/1613.htm) | Wired Multi Room Audio units / The MRA amplifier | 11 |

The JSON also contains the full macro/micro-function reference tree with **179 leaves**, and **197 direct wired/wireless/remote unit-type reference entries**. Leaf and unit-type counts are documentation counts, not verified behaviors. Crosscutting title searches separately locate scene, schedule, logic, firmware, security, label, template and diagnostic topics across all branches; these search matches need manual review and do not enlarge the reviewed subtree families automatically.

## Public C-Gate command inventory

Every command block is recorded with its exact name, source line range, grammar checksum, raw route, mapped wrapper symbols and an empty acceptance-evidence list. The command descriptions and full syntax prose remain in the local vendor reference. Namespace-help commands and comment commands are included. The reference's spelling is preserved, including `SECURITY RAISE_ ALARM`.

| Command family | Public blocks | Typed wrapper candidates |
| --- | ---: | ---: |
| # | 1 | 0 |
| // | 1 | 0 |
| AIRCON | 12 | 0 |
| APIVER | 1 | 0 |
| AUDIO | 20 | 0 |
| BROADCAST_EVENT | 1 | 0 |
| CGL | 3 | 2 |
| CLOCK | 4 | 0 |
| CONFIG | 9 | 0 |
| CONFIRM | 1 | 0 |
| DB | 22 | 9 |
| DO | 1 | 0 |
| ENABLE | 4 | 3 |
| EREPORT | 2 | 0 |
| EVENT | 1 | 1 |
| GET | 1 | 1 |
| GETSTATE | 1 | 1 |
| HELP | 1 | 0 |
| LIGHTING | 3 | 2 |
| LOCK | 1 | 0 |
| LOGIN | 1 | 0 |
| LOGOUT | 1 | 0 |
| MEASUREMENT | 2 | 0 |
| MEDIATRANSPORT | 22 | 0 |
| NET | 21 | 14 |
| NETWORK | 2 | 0 |
| NEW | 1 | 0 |
| NOOP | 1 | 0 |
| OFF | 1 | 1 |
| OID | 1 | 0 |
| ON | 1 | 1 |
| PORT | 7 | 0 |
| PROJECT | 15 | 12 |
| QUIT | 1 | 0 |
| RAMP | 1 | 1 |
| REPORT | 1 | 0 |
| RUN | 1 | 0 |
| SCENE | 1 | 0 |
| SECURITY | 8 | 0 |
| SESSION_ID | 3 | 0 |
| SET | 1 | 1 |
| SHORTMESSAGE | 3 | 0 |
| SHOW | 1 | 0 |
| SHUTDOWN | 1 | 0 |
| STOP | 1 | 0 |
| TELEPHONY | 6 | 0 |
| TEMPERATURE | 2 | 0 |
| TERMINATERAMP | 1 | 1 |
| TEST_SPAM | 1 | 0 |
| TOPOLOGY | 2 | 0 |
| TREE | 1 | 1 |
| TREEXML | 1 | 1 |
| TREEXMLDETAIL | 1 | 1 |
| TRIGGER | 4 | 3 |
| UNLOCK | 1 | 0 |

`PROJECT ARCHIVE` is constructed by the project wrapper but absent from this public command reference. Internal `PP` programming commands are also outside it. A public-command census alone therefore cannot establish either the complete backend surface or Toolkit parity.

## Evidence and completion criteria

A defensible completion claim needs a reviewed mapping from each actionable help topic and executable control to Python behavior, with positive, negative and preservation tests; device/firmware coverage; expected bus effects; and a justified disposition for reference-only topics and external applications. Record actual test artifacts against ledger IDs, with the tested vendor build and fixture. A feature must not become verified merely because a raw command or parameter name exists.

Source snapshots below make this census reproducible. Python source/test hashes in the JSON describe the inspected implementation snapshot; they do not claim that those tests were executed.

| Artifact | SHA-256 |
| --- | --- |
| [research/vendor/toolkit-help/Toolkit Help.hhc](../research/vendor/toolkit-help/Toolkit Help.hhc) | `cf93d505e0324430a09b4f702ba54c7a011f3994a0309b5f69ea5c55284df9da` |
| [research/vendor/cgate/app/help/cmds.txt](../research/vendor/cgate/app/help/cmds.txt) | `8e2ee745875de77b1aef24bfeefc669761500ff493ec3d7e7b7c57318af492d3` |
| [research/vendor/cgate/app/unitspec/cbusunits.xml](../research/vendor/cgate/app/unitspec/cbusunits.xml) | `c134c752fe4ef62a659c4480cd6702dffcc0096a59b4b0b336b5c383dbea6fe7` |
| [research/vendor/cgate/app/cgate.jar](../research/vendor/cgate/app/cgate.jar) | `3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630` |
| [research/vendor/toolkit/app/Toolkit Help.chm](../research/vendor/toolkit/app/Toolkit Help.chm) | `a189775cc95c426d0c55218f82951f9701b328e65b5dacbcfea457ed410511ab` |

Historical backend observation: `PROJECT REPAIR` returned 408 for the repository selected in the [native project probe](native-project-acceptance.json). That probe records 3 rejected repair attempts. This is not a limitation established for every repository type or for the currently running service. The separate [project repair research](project-repair-native.md) distinguishes SQLite and XML repository behavior. [Portable XML repair](project-repair.md) has separate original-code, native-load and CLI file-boundary acceptance; these results do not change this documentation census's unassessed topic states.
