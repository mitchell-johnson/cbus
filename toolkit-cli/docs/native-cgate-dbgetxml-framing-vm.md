# Original C-Gate `DBGETXML` TCP framing: offline VM evidence

The [14-case original-service capture](../../rust/testdata/fixtures/native_cgate_dbgetxml_framing_vm.json)
records exact tagged requests and wire replies from C-Gate 3.4.0 build 2001.
The C-Gate JAR SHA-256 is
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`;
the fixture SHA-256 is
`c819303fbe8d38d552fa3aa9b80fbe60ca1161ae731f1aeb830323f0e7e6863a`.
The [eight-case exact-wire vector](../../rust/testdata/vectors/cgate_dbgetxml_wire.json)
has SHA-256 `42b22fe1933392734d33728e224c7fef597fc1d73bd827952316e83526dd1b9e`
and is checked against the source-bound capture. The guest's private raw JSON
has SHA-256 `b7e9cd47f6a05db377ff3a9ea1c2c2bcedc52eb8d18722f9bf084b1e64c8ab43`.
Its one temporary Project readback, which contained a VM hostname and clock,
was used to obtain an OID but is omitted from the public case rows.

The [capture script](../research/experiments/2026-09-28/cgate-dbgetxml-framing-vm-capture.ps1)
is hash-pinned by `test_native_cgate_dbgetxml_framing_vm.py`, along with the
[route](../research/experiments/2026-09-28/cgate-dbgetxml-framing-vm-route.json)
and [cleanup](../research/experiments/2026-09-28/cgate-dbgetxml-framing-vm-cleanup.json)
receipts. The disposable Windows guest had zero IPv4 default routes during
capture. Its owned original C-Gate process had exactly six listeners, all on
`127.0.0.1`, and Network 254 pointed to the closed CNI endpoint
`127.0.0.1:1`. Cleanup confirmed process exit, removal of the owned temporary
tree, and restoration of the original C-Gate home. No house project, broker,
Docker service, physical PCI/CNI, or C-Bus network was contacted.

For successful `DBGETXML` by Network address, Unit address, Application
address, and Unit OID, original C-Gate returned the following four rows. The
declaration row alone ended with LF; the other three ended with CRLF.

```text
[tag] 343-Begin XML snippet\r\n
[tag] 347-<?xml version="1.0" encoding="utf-8"?>\n
[tag] 347-<object document>\r\n
[tag] 344 End XML snippet\r\n
```

The absent Unit at address 21 returned one `401` row with CRLF. Two commands
sent in one TCP write, `DBGETXML` followed by `NOOP`, completed in order: the
`344` terminal row ended the XML reply and the next command returned `200`.
The `DBSETXML` submissions in this capture returned separate `301 OID=...`
write receipts. The framing observation does not change their mapper or
persistence acceptance; the [combined](native-cgate-dbsetxml-combined-vm.md)
and [Unit mapper](native-cgate-dbsetxml-unit-mapper-vm.md) records retain those
bounded write observations.

The Rust listeners now format a successful single-row `DBGETXML` model reply
with this exact TCP envelope. The in-memory model's response representation is
unchanged, and errors remain ordinary status rows. The scoped offline replay
checks 12 original direct/combined Unit mapper exchanges plus two full Network
readbacks for exact wire equality on each Rust server; a separate Python
`CGateClient` test parses the `344` terminal reply and verifies a pipelined
read on both servers. This evidence does not cover multiline XML payloads,
other XML-producing commands, broader combined replacement/conflict variants,
Schneider file/repository persistence, TLS, or physical device effects.
`full_cgate_compatibility` remains false.
