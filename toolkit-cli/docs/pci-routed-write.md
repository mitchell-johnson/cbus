# Explicit routed WRITE

`RoutedWriteClient` sends one raw direct `WriteCAL` through caller-supplied
bridge bytes. Success requires both one positive PCI confirmation and one
addressed `AcknowledgeCAL` whose complete return path, parameter and tag equal
the caller's independent expectation.

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --timeout 5 routed-write \
  4 7 AABB --bridge 20 --bridge 21 \
  --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4 --expected-ack-tag 0x55
```

The unit, parameter, data, bridge values, expected path and expected ACK tag
are literal bytes. Data is zero through 30 bytes. At most six outgoing and six
incoming route entries are accepted. This operation supports direct CAL
addressing only; it does not infer programming mode, discover a route, resolve
a project network or read a unit specification.

Only numeric IPv4 or IPv6 endpoints are accepted, so the transaction performs
no DNS lookup. The client revalidates mutable settings before opening the
socket, sends one command, and never reconnects or retries. One monotonic
deadline covers connect, send and receive. A timeout, disconnect, rejection,
malformed response, interrupt or cleanup failure after send is retained as an
uncertain write outcome. Recovery is read-only and belongs to the calling
workflow.

The stream accepts explicit two-byte confirmations, CR-terminated ASCII hex
frames and idle CR/LF. Incoming frames use the strict addressed-route decoder:
headers `06` or `86`, an exact route count from zero through six, one supported
CAL and a mandatory checksum. Unmatched valid frames and confirmations remain
ordered evidence. Duplicate matching confirmations or ACKs, rejected
confirmations, malformed input and incomplete trailing data fail the operation.

A successful receipt proves the declared wire match. It sets
`physical_delivery_verified`, `parameter_commit_verified` and
`nonvolatile_persistence_verified` to false. A device-specific programming
workflow must add its own schema, protection, readback and persistence rules.

## Evidence

The existing frozen original route matrix includes direct and programming
`WriteCAL` forms at zero, small and 30-byte payload sizes, route depths zero,
one and six, checksum calculation and route overflow. The independent incoming
matrix includes exact ACK decoding across 1,142 constructor/checksum cases.
Those fixtures establish the byte transforms, not a live mutation.

Thirteen focused Python 3.13 tests add independent IPv4/IPv6 loopback peers,
both confirmation/ACK orders, every split point, every parameter and ACK tag
byte, zero and 30-byte payloads, route depths zero through six, exact path and
tag rejection, resource bounds, interruption evidence, CLI JSON and the
one-send/no-retry rule. See
[`pci-routed-write-acceptance.json`](../research/fixtures/pci-routed-write-acceptance.json).
No physical bridge or device was written for this checkpoint.
