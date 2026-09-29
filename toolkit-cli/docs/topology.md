# Project topology map and navigation

`cbus-toolkit project topology` builds the Toolkit topology map of a saved
legacy XML or CBZ project. It reads one bounded regular-file snapshot, binds
it by SHA-256, and never writes the project or opens an endpoint.

```sh
cbus-toolkit project topology house.cbz
cbus-toolkit project topology house.cbz --navigate 3
cbus-toolkit project topology house.cbz --near-side 254/3
cbus-toolkit project topology house.cbz --far-side 254/3
cbus-toolkit project topology house.cbz --format svg --output house-topology.svg
cbus-toolkit project topology house.cbz --format dot
```

## Toolkit rules reproduced

The rules come from static disassembly of Toolkit 1.18.0.2754
(`TTopologyGenerator`, `TTopologyExpressFlowChart`, `TfrmTopologyNode` and the
unit catalogue). The original was not executed. See the
[research note](../research/experiments/2026-09-29/topology-generator-static.md)
and its verified receipt.

- **Local networks.** Every network whose `InterfaceType` is not `Bridge` is
  local. The interface element is chosen case-insensitively:
  `Serial`, `Lorax`, `LoraxUSB` and unrecognized types draw **PCI**;
  `Socket`, `Etherlite` and `CNI` with a dotted IPv4 host draw **CNI**;
  `CNI` with any other host, `Wiser`, `C-Bus Home Controller` and
  `SpaceLogicCBusHomeController` draw **CNI2**; `modem` draws **CBTI**.
  Its label is `NETWORK/InterfaceAddress`.
- **Bridges.** Units are visited in ascending address order. A unit whose type
  is a near-side half (`BRIDGE2N`, `BRIDGE1F`, `GATEWLSN`, `WGATE5N`,
  `WGATE5XN`) connects to the network whose **number equals the unit address**.
  The far-side half is the unit in that network at the near network's number,
  when its type is a far-side half (`BRIDGE2F`, `BRIDGE1F`, `GATEWLSF`,
  `WGATE5F`, `WGATE5XF`). The label is `UNIT/NETWORK-FARUNIT`, with an empty
  far unit when it is absent. `BRIDGE1F` appears in both side lists in the
  original; the CLI keeps that.
- **Wireless.** `GATEWLS*` and `WGATE5*` halves are wireless gateways. A network
  is wireless when one of its unit types starts with `W` or is `NEOI 1FL`,
  `NEOI 4FL` or `NEOI HHR`.
- **Traversal.** The traversal is depth-first. A near bridge that points back
  to the parent network is not drawn again. If a bridge reaches a network that
  has already been explored, the CLI records a **circular join**. A network
  with no drawn bridge gets a one-column stub connection.
- **Layout.** Each bridge hop adds two columns. A new row is one below the
  highest occupied row in the columns to the right, as in the recovered
  `GetAvailableY`. Exhausting row 2400 raises `Too many networks for Topology Map`.
- **Warnings.** Each network that is absent from the map produces
  `Network "NAME" is not accessible`.

Networks are processed in project document order. The original
network-manager order has not been established.

## JSON model

The default output has format `cbus-project-topology-v1`. It contains:

- `project`: name, SHA-256, byte count and format.
- `networks`: each network's interface element and enum, local and wireless
  state, `in_topology_map`, and `local_root`.
- `interfaces`, `bridges` and `wireless_gateways`. Each bridge records its
  `near_side` and `far_side` unit (`/network/N/unit/U` and
  `//PROJECT/N/p/U`), whether it was drawn, whether it was skipped as the
  parent link, and whether it made a circular join.
- `orphaned_networks`, `circular_joins` and `warnings`. Warnings keep the
  exact orphan text and identify circular joins, which the original draws as
  an arrow.
- `elements`: the ordered drawing elements with the Toolkit's grid
  coordinates.
- `diagnostics`: CLI-only consistency findings that the original draws
  without comment. These include a missing or non-far-side far unit, a missing
  far network, a bridged network that has a local interface, several near
  bridges to one network, a C-Gate `Bridge` `InterfaceAddress` that is
  malformed, names another parent or unit, or has no matching near unit.
- `parity`: the evidence boundary described below.

## Navigation

- `--navigate NET` corresponds to *Navigate to network*. It returns the
  network's project path, every unit path, and the tree path of networks and
  bridges from its local network. It also returns a `route` from the
  planner used by the routed PCI commands. That planner is stricter: it
  requires a CNI or Serial root, conventional `BRIDGE2N` units, parent
  `Bridge` interface addresses, and no more than six bridges. When one of
  those conditions fails, the route reports `available: false` with a reason
  and the map is still produced.
- `--near-side NET/UNIT` and `--far-side NET/UNIT` correspond to the *Near
  side* and *Far side* functions. They name the bridge by its near-side unit.
  An unresolved far side fails with exit status 1, as the original shows an
  error for it. The CLI does not open a unit configuration form.

## Image export

`--format dot` and `--format svg` produce deterministic, dependency-free
renderings with the recovered colours: wireless `#0000FF` and wired
`#FF4488`. Without `--output`, the image is returned in the JSON `image`
field. With `--output`, a new file is created exclusively, and an existing
file is never replaced. The SVG title is the recovered print heading
`C-Bus Project "NAME" Network Topology Map`.

## Evidence boundary

`parity.original_toolkit_executed` is false. The following remain
`unassessed`: `layout_parity`, `visual_parity`, `pixel_parity` and
`print_parity`. Clipboard bitmap copy (*Copy Image*) is not implemented.
Nothing here establishes the original ExpressFlowChart rendering,
printing, network-manager order, unit-form behavior, native C-Gate 3
projects, live topology or physical bridge operation. Project and database
documentation is a separate pending ledger row, `project-documentation`.
