# CNI interface discovery

`cbus-toolkit interface discover-cni` performs the read-only IPv4 UDP
discovery exchange used by CNI2 and Wiser interfaces. It does not need C-Gate,
open the advertised TCP service, initialize a PCI, or send C-Bus traffic.

```sh
cbus-toolkit interface discover-cni
```

The default exchange binds UDP `0.0.0.0:20050`, enables broadcast, sends one
query to `255.255.255.255:20050`, and collects replies for two seconds. Choose
an interface-specific local address when a host has several network adapters:

```sh
cbus-toolkit interface discover-cni --bind 192.0.2.10 --timeout 3
```

For an isolated test peer, both ports and the destination can be explicit;
local port zero asks the operating system for an ephemeral port:

```sh
cbus-toolkit interface discover-cni \
  --bind 127.0.0.1 --listen-port 0 \
  --destination 127.0.0.1 --discovery-port 29999 --timeout 0.2
```

The Rust equivalent is `cbus-tools cni-discover` with the same options. Both
commands emit `cbus-cni-discovery-v1` JSON and use the same wire vectors.

## Scan active host adapters

From the repository root, install the optional network extra to enumerate the
host's IPv4 adapters:

```sh
python -m pip install -e './toolkit-cli[network]'
cbus-toolkit interface scan-cni --auto-adapters --plan-only
cbus-toolkit interface scan-cni --auto-adapters --timeout 2
```

The first command only prints a route plan and sends no packets. The second
queries each admitted active adapter's directed broadcast address once. Use
`--interface NAME` (repeatable) to restrict both planning and scanning to
named adapters. The JSON plan shows the selected interface, local bind,
netmask, derived destination and reported broadcast, plus skipped addresses
and their reasons. Scan results attach that adapter record to each per-route
observation. Interface status and address lists are separate OS observations,
so the snapshot is not atomic; a route may change before or during scanning.

Only operational, non-loopback, non-point-to-point IPv4 addresses with a
contiguous netmask and a usable directed broadcast are selected. Inconsistent
reported broadcast addresses are skipped. Enumeration is bounded to 256
adapters and the existing 16-route/300-second scan limits; it fails before
sending if there are too many eligible routes or a requested adapter has no
usable route. The optional `psutil` package supplies the cross-platform OS
adapter inventory. Automatic scanning does not claim that an unobserved CNI
is absent. Host firewall, VLAN, routing and subnet boundaries still matter.

## Explicit multi-adapter and subnet scan

`scan-cni --probe` repeats the same captured query for each *explicit* local
IPv4 bind and destination pair. This mode does not enumerate the host's
adapters or infer broadcast addresses. Use the broadcast destination
appropriate to each selected subnet; a unicast destination is also accepted:

```sh
cbus-toolkit interface scan-cni \
  --probe 192.0.2.10@192.0.2.255 \
  --probe 198.51.100.10@198.51.100.255 \
  --timeout 2
```

The command accepts 1–16 unique pairs and validates all of them before any
socket opens. It probes sequentially; `--timeout` and `--max-datagrams` apply
to each pair, and the sum of configured reply windows cannot exceed 300
seconds. A failed local socket operation is retained for that pair and
later pairs are still scanned. The result format is
`cbus-cni-multi-discovery-v1`, with each probe's original
`cbus-cni-discovery-v1` observation nested under `observation`.

Each probe has a distinct outcome: `devices_observed`,
`no_reply_by_deadline`, `no_valid_reply_by_deadline` (only malformed replies),
`hidden_replies_by_deadline` (only valid hidden-product replies),
`filtered_replies_by_deadline` (hidden and malformed replies),
`datagram_limit`, or `transport_error`. `scan_complete=false` if any probe
reached its datagram cap or had a transport error. A transport error leaves
`query_sent_once=null`, because it may have occurred before or after sending;
the client never retries it. A zero-reply deadline is an observation window,
not proof of absence. The scan never opens the advertised TCP service or
checks exclusive ownership, and it never selects a discovered device for
project mutation.

## Wire and result boundary

The exact 19-byte query is:

```text
CB800000000000000101010B011D80010247FF
```

Replies must be exactly 30 bytes and contain each captured field tag and
length in its fixed position. The decoder exposes the four-byte `unknown1` field,
product id, advertised TCP port, one status byte, and final two bytes. The
`unknown1`, status and trailer fields stay raw because their semantics and any
trailer checksum algorithm have not been established. Product ids `1`, `2`
and `3` are labelled `cni2`, `hidden` and `wiser`; every other byte is retained
as `unknown`. Captured Toolkit behavior excludes product id 2 by default;
`--include-hidden` reports it with `visible_by_default=false`.

The `unknown1_hex` value is not a device identifier; repeated live replies can
change it while every other byte remains stable. Each device record therefore
uses the UDP source IPv4 address with the advertised TCP
port to form `endpoint`. Exact duplicates from the same UDP source are counted
once. Structurally invalid datagrams are retained under `malformed`; they are
never treated as devices. To keep a 4096-datagram scan bounded in memory,
duplicate keys use a source/length/SHA-256 fingerprint and malformed records
retain at most the first 64 raw bytes, plus `raw_length` and `raw_truncated`.
Results are sorted deterministically.

One monotonic deadline covers reply collection. `--max-datagrams` is bounded
to 1–4096. Reaching it sets `collection_complete=false`; reaching the deadline
normally sets it true. Even a complete zero-reply collection has
`absence_proven=false`: UDP broadcast loss, host routing, firewalls, interface
selection and devices on another subnet can all hide an interface. Discovery
also does not prove TCP reachability, exclusive ownership, device identity,
firmware, or attachment to the intended C-Bus network.

## Creating a native network from a selected result

Review the returned product, raw fields and source address, then pass the exact
`endpoint` to the existing native database workflow:

```sh
cbus-toolkit cgate --host CGATE_HOST project new TEST
cbus-toolkit cgate --host CGATE_HOST database network-new \
  TEST 254 Local Cni DISCOVERED_ADDRESS:DISCOVERED_PORT
cbus-toolkit cgate --host CGATE_HOST project save TEST
```

Discovery never chooses a result or mutates a project automatically. This
keeps selection review separate from `DBCREATENET`, which creates and loads a
closed native network. Opening or synchronizing that network remains an
explicit later operation.

## Evidence and tests

[`cni_discovery.jsonl`](../../rust/testdata/vectors/cni_discovery.jsonl) pins
the exact query, the two retained CNI2/Wiser replies, hidden and unknown
products, truncation, bad magic and a bad field tag. The Python suite consumes
the same vectors. Independent loopback UDP tests cover one-send behavior,
deadline completion, datagram-cap incompleteness, duplicate suppression,
hidden filtering, malformed evidence, argument validation and CLI JSON. Rust
tests cover the pure codec, transport and executable boundary. These checks do
not replace a fresh original Toolkit differential or broad real-interface and
multi-adapter acceptance.

The explicit multi-route tests cover two different local binds, independent
no-reply and device observations, malformed-only, hidden-only and capped
results, a failed adapter followed by a successful later probe, all-route
preflight, and CLI output. They use one-shot loopback UDP peers, not a native
Toolkit run or physical interface acceptance.

Injected adapter inventories test automatic route selection, adapter filters,
malformed netmasks and broadcasts, an unavailable route followed by a valid
one, and the no-I/O plan path. They are portable fixtures rather than Windows
or physical-network acceptance. The Rust `cbus-tools cni-discover` command
retains its single-route interface; automatic adapter enumeration is currently
provided by the Python CLI.

An operator-authorized read-only scan on 27 September 2026 sent one query from
each of two active Mac adapters on the house subnet. Each route received one
valid CNI2 reply advertising the same endpoint; the raw address-bearing
output remains outside the repository. This checks per-route reporting on
that host only. It does not establish original Toolkit behavior, TCP
reachability or ownership, C-Bus network identity, or other adapters/subnets.
