# Original C-Gate nested same-OID Applications

The [67-request capture](../../rust/testdata/fixtures/native_cgate_dbsetxml_nested_applications.json)
comes from the [reproducible capture script](../research/cgate_dbsetxml_nested_applications.py),
the [tagged exchange helper](../research/cgate_dbsetxml_duplicate_applications.py),
and the [owned-service harness](../research/local_cgate.py). The Python
[evidence test](../tests/test_native_cgate_dbsetxml_nested_applications.py)
pins all three source hashes, the C-Gate 3.4.0 build-2001 JAR and Java 11
hashes, exact request framing, and all tagged responses. The fixture SHA-256
is `5316e61cd7824858bcee1a0daf3df7bb20e4aa0dd0963e457d926bd9eea6db1d`;
the capture script SHA-256 is
`ea075e9f5b10ef5ddd7b69d04266e8405b7158498c203360e7547bc7eaf6090c`.
The temporary service owned six `127.0.0.1` listeners and confirmed child exit and working
directory removal. Its synthetic CNI at `127.0.0.1:1` was never opened. No
broker, site project, or physical C-Bus network was involved.

Three synthetic projects submitted a complete Network with Application
children. `XNG1` had one Application with a Group; `XNG2` had two Applications
sharing one OID, each with its own Group; `XNN2` had the same repeated
Application shape with NetVar children. Child OIDs were distinct. Original
C-Gate returned `301 OID=<Network OID>` for all three replacements. Its
Network, direct Application and child-path readbacks retained each child.
The shared Application OID selected the final submitted Application, along
with that Application's child. `PROJECT SAVE`, `CLOSE`, `LOAD` and `USE`
preserved both Application paths and all nested children.

The pair captures also replaced the first Application by direct path, with
the same Address and nested child. C-Gate returned `301 OID=<Application OID>`;
the second Application and its child remained, and shared-OID lookup still
selected the second Application. A second save/reload retained that result.
The [Rust vector](../../rust/testdata/vectors/cgate_dbsetxml_nested_applications.jsonl)
enumerates the five `DBSETXML` transactions and all XML read tags. The Rust
server test replays the 67 native requests and compares every scoped write
receipt and XML readback exactly after substituting generated Network and
Interface OIDs. The three synthetic `DBCREATENET` setup receipts have a known
older response difference and are checked only for successful local setup.
A separate service test checks nested child durability through JSON repository
restart, direct replacement, sibling isolation, OID selection and absence of
PCI traffic.

This evidence admits repeated-OID Applications with independently addressed
Group or NetVar children and a direct replacement that retains the same
Application Address. It does not establish colliding descendant OIDs,
cross-network OID collisions, other duplicated container types, delete or
Address mutation semantics, private vendor project-file interchange, or
physical behavior. Those cases retain their existing guards or remain open
under [P2.02](https://github.com/mitchell-johnson/cbus/issues/24).

The [Level-grandchild extension](native-cgate-dbsetxml-nested-levels.md)
captures unique Levels beneath the independent Group and NetVar children,
their load-time `TagsDLT` materialization, and the direct NetVar/Level error.
