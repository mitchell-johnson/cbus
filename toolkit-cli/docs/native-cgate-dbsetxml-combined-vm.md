# Original C-Gate combined Network XML: disposable VM oracle

This is a narrow original-service observation for `DBSETXML` against C-Gate
3.4.0 build 2001. The [exact 16-request tagged-wire fixture](../../rust/testdata/fixtures/native_cgate_dbsetxml_combined_vm.json)
preserves each request, each response line and the XML readbacks. It is an
LF-formatted JSON normalization of the guest's raw JSON (whose SHA-256 is
`7d9c5ba9e7c15a8efc78b6796f8e599356969cf7405c4d907fe0c5e8bc91ea45`);
the fixture's SHA-256 is
`7d850980d52a05103796bfcb01ca49a4fda5db23177387c0ad1d72978953abae`.
The [capture script](../research/experiments/2026-09-28/cgate-dbsetxml-vm-capture.ps1)
has SHA-256 `eea936de6596082a17720ffb9e1ee2198df44dac254a34a7a2c53dbfe2e8d1c6`;
the [service setup and cleanup script](../research/experiments/2026-09-28/cgate-dbsetxml-vm-service.ps1)
has SHA-256 `37b9515a1ab7d0fe1e66b43390f7d12d5ad9cd4cb9b78abb809566f2fd15525d`.
The separate [cleanup receipt](../research/experiments/2026-09-28/cgate-dbsetxml-vm-cleanup.json)
is likewise LF-normalized and has SHA-256
`787757b68ea62b44623f4081eca7c07714a3337f1b89e8f3860aba4529614724`.
The three fixture tests bind these source and evidence files by hash and check
the wire, XML graph and cleanup facts.

The original `cgate.jar` SHA-256 was
`3ec483945102b1355e06163e3ec964797629eb1c5aa50a525f859e5f14ced630`;
its bundled Java 11 binary SHA-256 was
`37048fe85e763554aa104d6711531b185271905a81ff7fb055978acf8eaea5f7`.
The process ran in a disposable Windows 11 UTM guest under a temporary
`XVM24` project. The guest had **zero IPv4 default routes**. The original
service process owned only six IPv4 loopback listeners (`127.0.0.1:24100`–
`24103`, `24110`, `24111`); commands used `24110`. Its Network 254 CNI
address was the unresponsive loopback endpoint `127.0.0.1:1`. The final native
`NET LIST` reported `State=new InterfaceState=closed`. No house project,
Docker service, broker, CNI, PCI or physical C-Bus endpoint was used.
The cleanup receipt confirms the child process exited, its temporary work
tree was removed, the guest's original C-Gate home was restored and the guest
still had no default route. The disposable VM was then stopped.

The capture first selected `XVM24`, read its existing Network identity, then
replaced the Network with only its required `Interface`. Readback at tag 903
established a child-free baseline. Tags 904–907 then submitted one complete
`Network` containing a complete `Unit` and `Application`. The original service
returned `[904] 301 OID=<network OID>`; Network, Unit and Application were
readable by their paths. Network readback placed `Application` before `Unit`
and kept the submitted Unit's plain scalar fields in schema order.

The next two complete replacements each returned `301` but treated unknown
namespaced Unit markup differently from a lossless XML store:

| Tags | Submitted addition | Original Network readback |
| --- | --- | --- |
| 908–909 | `ext:flag="synthetic"` on Unit, with `xmlns:ext` on Network | Accepted; attribute and declaration absent; modeled Unit and Application unchanged |
| 910–911 | `<ext:Diagnostic>synthetic</ext:Diagnostic>` under Unit, with `xmlns:ext` on Network | Accepted; child and declaration absent; modeled Unit and Application unchanged |

Tags 912–914 replaced the Network with the same Unit and no Application.
The original returned `301`, Network readback omitted Application, and a direct
`DBGETXML //XVM24/254/56` returned `401 Bad object or device ID: Element 56
not found.` This is original evidence for replacement of that omitted child,
not a claim about every descendant class or stateful live Network. The earlier
[combined fixture](../../rust/testdata/fixtures/native_cgate_dbsetxml_combined.json)
separately pins missing-`UnitName` validation and preservation on failure.

These cases do not establish broad namespace, comment or processing-instruction
handling, all Unit fields, all combined-tree forms, physical-device behavior,
or parity of either Rust server with the original mapper. In particular, the
original's observed omission of these two unknown namespaced additions should
be assessed against Rust's modeled extension-retention policy before any
exact XML parity claim. No runtime behavior was changed by this capture.
