# Database CSV backend source graph

Status: source-only. No original instructions, C-Gate command, VM job or project mutation has run in this stage. The accepted earlier cached-class pilot remains unchanged: twelve captures, ten normal returns, two expected storage-provider stops. This report does not establish arbitrary XML-to-CSV equivalence.

## Exact source and reproducibility

The original Toolkit EXE is SHA256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`; its MAP is `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`. `extract_named.py` resolves exact MAP symbols before `extract_static.py` records method bytes and disassembly. These bounded static spans can include inline data/exception tables and are not execution allowlists. `strings-v4.json` pins decoded literal headers/bytes; `source-data-v1.json` pins actual VMT entries and exception-class names. Five rejected source-preparation requests are recorded there; none executed original code or created a partially admitted original run.

## Report entry point and retained state

`TfrmUnitsNode.actProduceDocumentationExecute` (`0xEB6488`, static-v9) uses the selected network and its existing unit manager, after the original scan/state and dialog conditions. It calls `TCBUSUnitManager.AsCSV` (`0xF306BC`). It does not itself invoke XMLReload, LoadAllUnitApplications or LoadAllUnitGroups. A fresh native export therefore needs a named preparation phase; the original report action alone does not specify an arbitrary cold-cache database projection.

The accepted earlier pilot already demonstrates two Area getters per relay row, including when only the address column is requested. The getters can change the Area reference and can create/save missing group metadata. Existing row-formatting support intentionally consumes captured values and does not hide these operations.

## Actual class and agent registration

The unit-type initializer at `0x1392038` registers `TRELAY4`, type `RELAY4`, firmware bounds `0` and `9`; a second separate registration is for its documentor. The original firmware comparison is inclusive and uses recursive numeric-token subtraction, not System.Version. The existing pilot covers only its declared simple version strings.

Storage-agent registration is a different initializer: `CIS_TCBus1RelayCGateAgent` at `0x1398D7C` (static-v11). It appends the same `TCBus1RelayCGateAgent` VMT for five exact classes, in order: TRELAY1, TRELAY2, TRELAY4, TDIMMER4, TAN_OUT4. Generic registration at `0x13974CC` appends `TCBusUnitGeneric -> TCBusUnitGenericCGateAgent`. The base agent initializer at `0x13835B8` registers verbs, not a catch-all unit class.

`TFlashAgentFactory.RegisterAgent` (`0x7EF350`) appends an item with exact unit-class and agent-class pointers. `GetFlashAgent` (`0x7EF2C4`) iterates forward, compares exact class identity, constructs the first matching agent and returns nil if no match. It does not walk the inheritance hierarchy. These static registration facts do not claim execution of whole startup, absence of all later registration calls, or an arbitrary global registry history.

The actual TRELAY4 and generic agent VMT `+0x94` both point to base `AgentLoad` (`0xCB5D0C`). Their unit VMT `+0x88` is original `StorageLoad`; relay `+0xEC` is `GetAreaIfAvailable` (`0xD23704`) while generic `+0xEC` is the nil-return base getter (`0xF34770`). Relay `+0x10C` is its channel/interaction test; generic uses the base test. The class pointers and slots are preserved in source-data-v1.json.

## Area: from getter to literal command and reply

1. Relay Area getter calls `StorageLoad` (`0x7F4160`) with exactly `QuickGet` and `Parameter=AreaGroupAddress`.
2. StorageLoad retains an existing agent only when its retention flag is set, otherwise obtains it from the workspace factory and eventually frees it. The factory lookup uses the actual unit class. Missing factory/agent has an original error path.
3. `AgentLoad` (`0xCB5F03..0xCB5F5C`) recognizes those two verbs, calls `QuickGetSingleParameter` (`0xCB87F4`) and stores the returned string directly at unit `+0x160`. This is not an update to a typed PP attribute. The unit-state exclusion at AgentLoad entry remains relevant.
4. `QuickGetSingleParameter` invokes `QuickGet` (`0xCC335C`) with the Boolean path option false. For a nonblank OID, the target is `GetProjectPrefix + GetOIDAsCGateID`. The prefix is `//` + project TagName + `/` when nonempty. The ID is `!` + literal OID. With a blank OID it uses the actual unit `GetAddressAsPath` VMT entry plus the same prefix. The separate true-option `/p`-first branch is not this call.
5. `TcgcppQuickGet.GenerateCommandText` (`0xCB0694`) constructs exactly lowercase `pp quickget ` + target + one space + parameter, with no added quoting. The expected usual forms are therefore `pp quickget //PROJECT/!OID AreaGroupAddress` and the corresponding path form; they still require native literal corroboration.
6. `OnProcessResults` (`0xCB070C`) first records the response through its base callback. A response starting `315` runs `ProcessParameter`. Only prefix `315 ` completes that branch; `315-` continues. `HasResponse` is a position-one prefix test, with an optional contained string test.
7. `ExtractNameAndValueFromParameter` (`0xCB0A9C`) copies after the first `]`, trims, finds the first hyphen or space, and splits the remaining text at the first `=`. `ProcessParameter` discards the extracted name and replaces the single stored result. Correlation with the requested parameter is not established by this parser. A strict native adapter must preserve command-ID association independently and must not treat a plausible value from a wrong name as verified.
8. Several original error text patterns mark the command complete. Other branches install `ECGateProgrammingSessionNotFound` or `ECGateBadUnitSpec`; the outer QuickGet catches `ECGateObjectException` and `ECGateCommand` and supplies an empty string. Do not equate completed with a successful read. Exact exceptional branching and text-case quirks are still source-only.
9. The Area getter then applies original StrToIntDef with fallback 255, resolves GroupByAddress(create=true), and changes the retained Area reference. Native integer formatting (including potential hexadecimal strings) must be fed unchanged through this path; the prior pilot supplied only `12`, `13`, `255`, and `invalid`.

## Database XML and field projection

`XMLReload` (`0xD85304`) constructs `TcgcDBGetXML` for project-prefixed network identity. Its generator (`0xD80EF4`) emits `dbgetxml ` + target. Its result handler (`0xD80FE0`) concatenates parsed response records whose code is 347 and accepts a `344`/`end xml` completion. Its event-monitoring toggles and command execution are additional dependencies, not part of a pure XML parser. The original one-exception fallback/retry is not a proposed native adapter policy.

On successful reload, the original clears units and a network collection, runs `PreProcessXML` (`0xD85498`), then `LoadFromXMLString`. Preprocessing is ordered string surgery: it wraps Application, Group, Level, Unit, NetVar and Output elements in their collection names, removes a Languages OID fragment and slices out the Network text. It is not a general tree normalization. Exact literals are pinned; StringSnip and parser corner domains remain unexecuted here.

`LoadXMLintoObject` (`0x7E1FB8`) constructs the importer; start-element callbacks build cached objects. `TFlashCachedObject.LoadIntoFlashObject` (`0x7E36B4`) visits cached attribute names in its stored order and calls `SetAttribute` (`0x7E2F00`), then installs aggregate/composite relations and invokes FinishedLoading. SetAttribute uppercases the incoming name, searches the actual target attribute manager for its first matching stored name, and invokes that attribute's original string setter. Unknown names are ignored. Type code 4 has a separate regional-number conversion. There is no justified blanket `XML tag -> same-named Python field` rule.

`TFlashUnitBuilder.CreateFlashObject` (`0xF34104`) reads cached `UNITTYPE` and `FIRMWAREVERSION`, then calls the original unit-type factory. The earlier pilot executed this cached lookup and constructor selection with explicit providers; it did not execute full constructors or the XML parser.

Relevant constructor/CSV field association, directly from `TCBUSUnit.InternalCreate` (`0xF2EF2C`) and the serializer:

| Captured CSV scalar | Unit field | Original constructor attribute |
| --- | --- | --- |
| part_name | +0x100 | UnitName |
| tag_name | +0x9C | TagName (base TCGateObject) |
| unit_type | +0x108 | UnitType |
| catalog | +0xF0 | CatalogNumber |
| serial | +0xEC | SerialNumber |
| firmware | +0xC8 | FirmwareVersion |

Address is a separate original object/address path, and application/Area/group values are references and ordered collections. Relay adds the `AreaGroup` reference and Channels/RelayLogicGroups collections. No direct `AreaGroupAddress` constructor attribute replaces the dynamic QuickGet result.

## Application and group preparation is an additional phase

`LoadApplications` (`0xCB86B8`) checks its loaded flag, QuickGets `Application`, formats the pair, resolves application objects and sets the original unit references. `FormatCgApplication` (`0xCB84C4`) converts the array and supplies 56/255 defaults when the corresponding strings are empty. This must not be inferred from an omitted cache fact.

`LoadDatabaseUnitGroups` (`0xCB8818`) checks flags, invokes LoadApplications, clears the unit group collection, obtains group-address text and optional secondary flags, resolves metadata with GroupByAddress(create=true), and adds ordered references. For the actual generic/relay agent, `LoadUnitGroupAddresses` (`0xCC3530`) QuickGets `GroupAddress` and sets the secondary-flags result to an empty string. Thus this method's normal path uses the primary application for those groups. This is distinct from a guessed mapping of all native XML Group elements.

Relay also has `LoadDBParametersForLoadGroups` (`0x1249D6C`) and `LoadLogicAssociationsAndGroups` (`0x124A1C4`). It loads GroupAddress and, when nonempty, six LogicGA association arrays; its LoadGroups then configures channel/logic references. These paths, cache flags, duplicates and group order remain relevant before a cold-cache report claim. The retained report action itself does not call them.

The prior captured plaintext RELAY4 specification agrees on Application array2 (56/255 defaults), AreaGroupAddress at0x43 and GroupAddress array16 at0x50, plus six four-bit-array association parameters. It is a supporting local input; a fresh native GET_UNIT_SPEC result must corroborate the actually selected backend spec before using it in the proposed pilot.

## Next useful boundary

First prove the literal read path against a fresh owned backend, and feed its exact responses through the original command parser/getter. Then prove a generated DBGETXML snapshot through the original cached loader/attribute setters and named group-preparation phase. A public database-report command should wait for those joined phases. The next proposal is intentionally a small corroboration pilot, with no new public API and no claim that a Python XML projection already equals the original object graph.
