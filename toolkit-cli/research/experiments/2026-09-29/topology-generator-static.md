# Toolkit 1.18 topology map: static review

Scope: issue #57 (P8.03), topology navigation and image export. This is a
static review only. No vendor code was executed, no project was opened, and
no C-Gate, CNI or PCI endpoint was used.

## Inputs

| Input | Identity |
| --- | --- |
| `CBusToolkit.exe` 1.18.0.2754 | SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` |
| `CBusToolkit.map` | SHA-256 `f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb` |
| `TFRMTOPOLOGYNODE` form resource | SHA-256 `f401d1e4dad01771b65f0ba371194c69fe5af8dc34c802e85db75cf39581032c` (`docs/toolkit-executable-surface.json`) |
| Help 379 *Topological node* | `05382464fcf57f25c57810a0477644b297af99966729e18ff5e912f6596efe81` |
| Help 415 *Topological toolbar* | `a513711417b0de23007a43a41c0d7103651a5e31f67e1ef8a0a43da28795cbee` |
| Help 416 *Topological window* | `a6e9b47ab668dafdf343fffee9c86e1c5965010e1976cd3b3db9acfc63390562` |
| Help 4649 *Topological functions* | `508e9543e588617be7f9719f3f92a28ee3b9c81ea0d4807d5c5e41d6582eab1b` |
| Help 4600 *Navigate to network* | `52e63ee09beef0499a4126ba39120df20955f474d220c9c99f120a33f3cecc52` |
| Help 4601 *Copy image* | `9a127811a81980ea9774f68e92025bbb7398e5160542decdbeb3bed980d78962` |
| Help 4602 *Far side* | `9bd3316fc8aac9f7c87390a4f900386aa9bbde286cbf7469ef1a056dfd360082` |
| Help 4603 *Near side* | `5e08345c44cf89da6f2c4ae755df12c0b737546262a573f80bc8e83c478f3cc7` |
| Help 4604 *Print* | `63eee606b570a25f7ebf99f75fa3e783a790db7613f109e0944ea2badf4e4e63` |

Reproduce the verification with the following command. It requires the
private original files, `capstone` and `pefile`:

```sh
python research/topology_generator_static.py --exe CBusToolkit.exe --map CBusToolkit.map
```

The script checks that the extracted literals, branch constants, colours and
resource strings match the constants in `cbus_toolkit.project_topology`. It
fails otherwise. The receipt is
[`topology-generator-static.json`](topology-generator-static.json). It holds
the method spans, which are MAP symbols with byte-span hashes, and the
recovered interface enum table.

## Findings

**Form and entry points.** `TfrmTopologyNode` returns help context 379
(0x17B). Its actions are `actNavigateToNetwork`, `actOpenNearBridge`,
`actOpenFarBridge`, `actOpenNearWG`, `actOpenFarWG`, `actCopyImage` and
`actPrint`. `GenerateAndDrawTopologyMap` calls
`CIS_TTopologyGenerator.GenerateTopologyScript`. That function builds a tag
script, which `DrawTopologyWithExpressFlowChart` draws.

**Script elements.** `Add{PCI,CNI,CNI2,CBTI,Bridge}Element` emit
`<Type>`, `<Name>`, `<Address>`, `<X>` and `<Y>`. The bridge element adds
`<Wireless>`. `AddNetwork` emits `<Type>Network`, `<Name>`, `<Address>`,
`<StartX>`, `<StartY>`, `<FinishX>`, `<FinishY>`, `<CircularJoin>` and
`<Wireless>`. Orphan warnings use `<Type>Warning` and `<Text>`.
`DrawElement` dispatches on the element types PCI, CBTI, CNI, CNI2, Bridge
and Network.

**Interface type.** `TNetworkInterface.GetInterfaceType` compares the
interface type case-insensitively:

| Interface type | Enum |
| --- | --- |
| Serial | 0 |
| CNI whose text before `:` is a valid IP | 1 |
| CNI otherwise | 4 |
| C-Bus Home Controller | 4 |
| SpaceLogicCBusHomeController | 10 |
| Lorax | 8 |
| LoraxUSB | 9 |
| Etherlite | 2 |
| Socket | 1 |
| Wiser | 4 |
| Bridge on a wireless network | 6 |
| Bridge otherwise | 5 |
| modem | 7 |
| anything else | 0 |

`FindLocalNetworks` treats enums 0–4 and 7–10 as local, so every interface
type except `Bridge` is local. `GenerateNetworkTree` draws enums 1–3 as CNI,
4 and 10 as CNI2, 7 as CBTI and every other enum as PCI. The interface label
is `NETWORK/InterfaceAddress`.

**Bridges.** `TCGateUnitCatalog.IsBridge` accepts `bridge1n`, `bridge2n`,
`bridge1f`, `bridge2f`, `gatewls`, `gatewlsn`, `gatewlsf`, `wgate5n`,
`wgate5f`, `wgate5xn` and `wgate5xf`.

- `IsNearBridge` accepts `bridge1f`, `bridge2n`, `gatewlsn`, `wgate5n` and
  `wgate5xn`.
- `IsBridgeFarSide` accepts `bridge1f`, `bridge2f`, `gatewlsf`, `wgate5f` and
  `wgate5xf`. `bridge1f` appears in both lists, and `bridge1n` and `gatewls`
  appear in neither.
- `IsWirelessGateway` accepts the seven `gatewls*` and `wgate5*` names.
- `TCBusNetwork.GetIsWireless` is true when any unit type starts with `w` or
  is `NEOI 1FL`, `NEOI 4FL` or `NEOI HHR`. When a network has no units, the
  original checks a second unit list that has no counterpart in the legacy
  XML.

**Traversal.** `ExploreNetwork` records the network as processed. It then
visits the unit manager in order. Prior research,
`research/csv_manager_order_static.py`, established that this order is
ascending by address. For each unit that passes both `IsBridge` and
`IsNearBridge`:

1. `NetworkByNetworkNumber(unit address)` selects the far network. The far
   unit is the unit in that network at the near network's address, but only
   when it passes `IsBridgeFarSide`.
2. A unit whose address string equals the parent network is skipped.
3. The bridge is placed at column `level + 2`. Its label is
   `UNIT/NETWORK-FARUNIT`.
4. A network connection runs from `(level, y)` to the bridge.
5. If the far network has not been processed, it is explored from the bridge.
   Otherwise `AddNetwork` records a `CircularJoin`.

If a network has no drawn bridge, it gets a stub from `(level, y)` to
`(level + 1, y)`. `Generate` explores each local network in turn. The
processed list is shared across those explorations.

**Layout grid.** The grid has columns 0–600 and rows 0–2400. The generator
marks one cell for each drawn element. `GetAvailableY(x, minY)` returns
`max(minY, highest occupied row + 1)` over columns `x` to `x + 2 × network
count`. A full column raises resource string 61805, `Too many networks for
Topology Map`.

**Orphans.** `CheckOrphanedNetworks` warns for every network that has no
network element in the script. The warning uses resource string 61806,
`Network "%s" is not accessible`, formatted with the network name.

**Navigation.**

- `OpenNearSideGUI` opens the unit at `UNIT` in network `NETWORK`.
- `OpenFarSideGUI` opens the unit at `FARUNIT` in network `UNIT`. When that
  unit is missing, it reports error 3122.
- `OpenUnitsNode` navigates the project tree to the selected network's units.

**Drawing.** Connections are blue (`$FF0000`) when wireless and `$8844FF`,
which is RGB `#FF4488`, otherwise. A circular join gets a width-6 arrow.
Network captions use resource string 61804, `addr=`, and warnings are
prefixed with 61803, `Warning:`. `Print` titles the page with 61777,
`C-Bus Project "%s" Network Topology Map`. `CopyToClipboard` copies the
chart's client area as a bitmap.

## Not established

The following were not captured or compared:

- original execution or the drawn chart
- exact bend points, fonts and zoom
- the print page
- the clipboard bitmap
- network-manager order, which the CLI replaces with document order
- the exact JCL `StrBefore` and `StringIsValidIP` edge cases. The CLI treats
  the text before the first `:` as the host and requires a dotted-quad IPv4
  address.
- the exact script text serialization, including `BooleanToString` casing
  and separators

Every one of these parity dimensions remains `unassessed`.
