# Final static database CSV report profiles

The final source-backed batch adds all **48 previously unadmitted static unit
types**, reaching **262 of 262 types**, with at least one admitted report
profile in **424 of 425 static registrations**. A registration admission
records an implemented source profile inside its range; it does not make
every firmware, stored shape, GUI lifecycle or device behavior compatible.

The new [registry receipt](../research/fixtures/toolkit-database-csv-last-registry.json)
is distinct from the historical 126-type and 214-type receipts, which remain
unchanged. The [source proof](../research/fixtures/toolkit-database-csv-last-source-proof.json)
pins 114 original method bodies by symbol, address and SHA-256 and records
their concrete VMT bindings and reviewed report facts. The
[literal vector](../../rust/testdata/vectors/toolkit_database_csv_last_profiles.json)
contains an invented complete `//LASTCSV/254` native snapshot, 62 fixture
units and independent literal CSV rows, plus 112 new registration endpoint
cases. This work read the pinned EXE/MAP; original/vendor instructions, a VM,
site services and hardware were not executed.

| Exact loader/report family | Final report associations |
| --- | --- |
| Old `TSENLL` (`SENLL` and `PE_CELL`, 1.00–2.0.00) | `LevelGroupAddress`, `OnOffGroupAddress`, `EnableGroupAddress`, in that order |
| Old `TSENTEMP` (1.00–1.2.68) | `ControlGroupAddress`, `EnableGroupAddress`, `OffsetGroupAddress`, in that order |
| `TSENTEMPPro` (`SENTEMPB`) | Primary Application25: one `TemperatureGroup`; 172: one `GroupAddress`; 228: no associations; other admitted byte applications: `GroupAddress`, `EconomyGroup`, `ControlledGroup` |
| `TIOPECGateAgent` | Eight primary `InputGroupAddress` associations, then one/two/four primary `OutputGroupAddress` associations for IOPE1R1/IOPE2R2/IOPE2C4 |
| `TCBusWirelessFanControllerCGateAgent` (WRD4F1 2.2.90–2.3.99) | Only `OutputGroup` associations, in `InstalledChannels` order, using each independent `OutputGroupSecondary` Boolean |
| `TDIMPR12L1CGateAgent` (DIMPR12 1.9.03–9) | Twelve primary `GroupAddress` associations through the inherited Bytecraft loader |
| Source-reviewed base/gateway group loaders | Fresh Unit group manager remains empty; all sixteen group columns are unavailable |

The empty manager profiles cover SHAC/NAC/AC2, bridges and wired wireless
gateway sides, all WGATE5N/F factory partitions, WTXU/WTXUP and remote aliases,
thermostats, SENCT4, scene controllers, DALI B/C, WHAA audio, wireless PCI,
DMXDO12 and SENTEMP4. Their separate auxiliary collections and parameter
graphs do not become CSV report associations. PC_GIM, SENCT4, KEYSCEN4,
SCNCTL5 and DMXDO12 still expose an independent primary Area provider despite
the empty report group manager.

Both authoritative Application objects must exist. The base formatter defaults
an empty stored `Application` to `56 255`; the exact bridge, wireless gateway
and wireless PCI formatter overrides default it to `255 255`. Application255
is a real resolved object, including when both providers name the same
Application. A single stored address defaults only secondary to255. This
batch keeps the bounded zero/one/two canonical decimal byte grammar rather
than expanding unobserved malformed-input behavior.

IOPE loads per-block references before replacing the report manager. Each
secondary bit therefore requires its corresponding secondary Group to exist
even though the final CSV row contains the primary Group at that address.
Both input/output stored arrays are bounded to 32 byte tokens; a short
nonempty array defaults each missing initialized position to primary255.
Missing consumed references refuse the whole export. In non-lighting
SENTEMPB modes, the loader also resolves three unused primary255 references
which are absent from the report manager, so that Group must still exist.
Fan profiles require complete installed output/routing arrays, keys and
channels bounded to 0–16, and a relay mask inside the installed width;
input block groups are omitted by the source fan loader. Its separate master
projection runs only for `LoadParamsFromMaster` or `LoadMasterFanTrigger`;
the database `LoadGroups` verb does not invoke it. These are resolved
report projections and do not reconstruct physical channel programming.

The public cached representation remains
`cbus-toolkit-database-cached-projection-v4`: it binds the final ordered report
manager, authoritative primary/secondary Application identities and complete
membership of both selected Applications. Temperature association count is
checked against the retained primary Application address; fan routing is
checked against each retained group’s Application membership. The native
adapter independently validates the consumed PP fields and extra lookups.
Cached v4 does not claim to replay complete auxiliary loaders, channel masks,
scene graphs, remote networks or previous original process history.

The one remaining refused static row is `KEYGL5`→`TKEYGL5`, which has no
exact-class CGate agent. The independent source-pinned KEYGL5 5.5.00/
5055EDL profile remains supported; an overlapping factory row does not
authorize choosing its class for other firmware. Static factory gaps,
invalid versions, overlapping/ambiguous selection and runtime INI classes
remain refusals. Original GUI CSV, fresh original native cold-load family
acceptance and physical behavior remain open, as does full Toolkit parity.

Regenerate the final receipts from the local pinned original bytes with
`research/csv_factory_registry_static.py`, then
`python -m research.csv_last_profiles_static --exe ... --map ... --registry
research/fixtures/toolkit-database-csv-last-registry.json --output
research/fixtures/toolkit-database-csv-last-source-proof.json`. Neither
extractor executes original instructions. The focused suite is
`tests/test_toolkit_database_csv_last_profiles.py`; public one-request export
and backend integration are separate validation layers.
