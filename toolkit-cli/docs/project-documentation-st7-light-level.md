# ST7 light-level stored report

`cbus-toolkit cgate database-document --project //PROJECT --output report.html`
projects the saved database snapshot. The offline native XML form is
`cbus-toolkit project document saved.xml --native-xml --output report.html`.
For SENLL firmware 2.0.01 through the factory's upper bound 9, the selected
class is TST7SENLL and the report is TST7LightLevelSensorDocumentor. Old
SENLL/PE_CELL and surface SENLLA retain their separate class contracts.

The complete light-level body uses the selected maintenance block, block 2,
the primary application's PECEnablerGroup and the selected broadcast block.
Target and margin retain the recovered Lux2550 conversion. Each consumed
application/group must resolve in the saved model; absent or malformed
consumed fields produce an explicit report marker. The snapshot is read once,
without opening the network, loading physical PP or saving the database.

TST7SENLL has zero physical keys and a virtual-key limit of -1. The inherited
limit helper interprets -1 as the physical count, so the fresh model also has
zero InputKeys. Its inherited NeoPro event loader, template refresh,
SENPILL overrides and occupancy-key loader therefore have no keys to visit.
Stored active commands and occupancy masks do not create a five-minute timer.
All eight block timers load their explicit high/low bytes. Block 4 starts with
a ten-second TimerMin; both Timer and TimerMin callbacks enforce that minimum.
Its stored values 0 through 9 report ten seconds. Other blocks retain zero,
and larger values retain the complete unsigned sixteen-bit time.

The effective derived input consumer describes the maintenance block as
`Level Group`, then block 2 as `On/Off Group`. The effective other consumer
describes the broadcast block as `Light Level Broadcast Group`, then the
primary PECEnablerGroup as `Enable Group`. These comparisons use complete
application/group identity and preserve both labels when references coincide.
They do not depend on PECFunctionActive or BroadcastActive. Output group use
and ActionSelectorUse are the empty inherited base methods.

The inherited loader builds the stored scene collection before loading keys,
including packed scene pointers, but this selected report does not visit that
collection. A nonempty saved SceneTable neither adds scene group use nor an
action-selector description. Unconsumed key, scene and other sensor fields
are preserved; this is not acceptance of malformed values by a scene editor,
physical loader, or original GUI lifecycle.

The independent current literal annex is
`research/fixtures/project-documentor-st7-light-level.json`. It contains a
complete invented native project with ten units: all eight zero broadcast
selectors, active stored key/occupancy values, eight packed nonempty scenes,
coincident roles and unused application/group objects. The static annex
`project-documentor-st7-light-level-static.json` records exact effective VMTs,
fresh counts, loader order, timer callbacks and group resource labels against
the pinned original EXE/MAP hashes. The earlier remaining-family literal and
static receipts remain historical and byte-for-byte preserved; current test
expectations use an explicit annex overlay.

Focused pure and actual CLI tests cover both owned Rust servers, literal body
bytes, ordered usage, a single DBGETXML, complete source graph preservation,
closed network traps and output/snapshot hashes. Static recovery executes no
original instructions. Original Toolkit generated-page comparison, native
Schneider server acceptance, original GUI state and physical sensor effects
remain separate acceptance gates.
