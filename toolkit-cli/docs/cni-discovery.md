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
never treated as devices. Results are sorted deterministically.

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
