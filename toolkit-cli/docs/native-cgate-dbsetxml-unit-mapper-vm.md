# Original C-Gate direct and combined Unit XML mapper: offline VM evidence

The [21-command original fixture](../../rust/testdata/fixtures/native_cgate_dbsetxml_unit_vm.json)
records exact numeric-tag requests and wire replies from C-Gate 3.4.0 build
2001 (`cgate.jar` SHA-256
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`).
Its SHA-256 is
`6ae63e7a36de13cdd5af034ba132dcda9b452dc5bc3a5e403a3213423e9ce70d`;
the raw guest capture SHA-256 was
`783ba91dd449c90c0ef8ae3c724f9517e681883f01f2588d504e0e94fc8c03a9`.
The [capture script](../research/experiments/2026-09-28/cgate-dbsetxml-unit-vm-capture.ps1),
[route-removal script](../research/experiments/2026-09-28/cgate-dbsetxml-unit-vm-offline.ps1),
[route receipt](../research/experiments/2026-09-28/cgate-dbsetxml-unit-vm-offline.json),
and [cleanup receipt](../research/experiments/2026-09-28/cgate-dbsetxml-unit-vm-cleanup.json)
are hash-pinned in `test_native_cgate_dbsetxml_unit_vm.py`.

The disposable Windows guest booted with one saved Shared Network default
route; that route was removed **before** the original C-Gate service started.
During capture it had zero default routes, six original-service listeners bound
to `127.0.0.1`, and a temporary `XUNIT` Network 254 whose CNI was the closed
loopback endpoint `127.0.0.1:1`. `NET LIST` was
`State=new InterfaceState=closed` before and after the XML commands. Cleanup
stopped C-Gate, removed the temporary work tree, restored its home and stopped
the VM. No house project, broker, Docker service, physical CNI, PCI or C-Bus
network was contacted.

The original accepted a complete Network+Unit+Application document with
`301 OID=<network OID>` (tag 808). Direct Unit `DBSETXML` then accepted an
unknown `ext:flag` root attribute (tag 810) and an unknown
`<ext:Diagnostic>` direct child (tag 813), each with `301 OID=<unit OID>`.
Unit readbacks at 811 and 814 exactly matched the plain Unit at 809: the
unknown addition and now-unused `xmlns:ext` declaration were absent. Combined
Network replacements with the same two additions (816, 818) also returned
`301`, and Unit readbacks at 817 and 819 were the same plain XML. Network
readbacks after the direct cases (812, 815) retained the Application and Unit
without the unknown extension. This extends the separate [combined-Network
oracle](native-cgate-dbsetxml-combined-vm.md): the observed omission is not
specific to a Unit nested in a Network replacement.

The scoped [differential runner](../research/cgate_dbsetxml_unit_differential.py)
replayed tags 808–819 against fresh `cgate-mock` and `cmqttd` listeners on
owned IPv4 loopback, with a disposable PCI simulator and broker for `cmqttd`.
Only generated Network and Interface OIDs were substituted. For the two
combined submissions, the runner also compares subsequent full Network
readbacks against tags 909 and 911 of the earlier combined oracle; their
submitted XML bodies are byte-identical after Network OID substitution. The committed
[mock](../research/fixtures/cgate-dbsetxml-unit-differential-mock.json) and
[daemon](../research/fixtures/cgate-dbsetxml-unit-differential-cmqttd.json)
receipts retain original and Rust wire rows, binary digests and a transitive
Rust/source fingerprint. Both pass **12/12 direct/combined Unit mapper cases plus 2/2 full combined
Network readbacks**, including the four changed Unit readbacks. Five `301`
reply rows are byte-identical. A later [framing implementation and fresh original VM capture](native-cgate-dbgetxml-framing-vm.md) changed the Rust TCP boundary: the seven XML reads now also match the original `343/347/344` envelope, including its LF-only declaration row. The updated source-bound differential requires **12/12 exact wire matches** plus **2/2 full Network readbacks** on each server. The original mapper conclusions remain bounded to these cases.

The later [37-request original-service replacement-edge capture](native-cgate-dbsetxml-replacement-edges.md)
shows comments, processing instructions and nested namespaced markup are also
accepted and discarded by the original mapper. Rust now matches seven exact
readback vectors from that capture. The [later duplicate-OID capture](native-cgate-dbsetxml-duplicate-oids.md)
pins the Application/Unit and two-Unit cases now retained by Rust; other
duplicate shapes and ambiguous OID-based mutations remain a parity gap.
Neither capture establishes all XML variants,
TLS, ACCESS, physical units or broad `DBSETXML` parity. Offline XML/CBZ editing
in the Python Toolkit CLI is a separate lossless project-file workflow.
