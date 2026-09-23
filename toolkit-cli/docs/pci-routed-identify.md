# Explicit routed IDENTIFY

`RoutedIdentifyClient` sends one direct IDENTIFY through caller-supplied bridge bytes and returns raw reply data. It requires an explicit expected incoming path, a positive `g.` confirmation and one matching REPLY. The existing RECALL client, `PCIClient`, MMI, commissioning and simulator are unchanged.

```python
from cbus_toolkit.pci import IdentifyCAL
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_identify import RoutedIdentifyClient, RoutedReplyPath

command = RoutedCALCommand(4, IdentifyCAL(1), bridges=(20, 21))
expected = RoutedReplyPath(20, 16, (21, 4))
client = RoutedIdentifyClient("127.0.0.1", 10001, timeout=5.0)
# This call requires an independently configured endpoint.
result = client.exchange(command, expected=expected, expected_count=1)
print(result.data.hex())
```

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --timeout 5 routed-identify 4 1 \
  --bridge 20 --bridge 21 --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4 --expected-count 1
```

`expected_count=None` (omit `--expected-count`) accepts any supported wire count from0 through30. A supplied count must match exactly; Boolean values are not integer counts. A valid zero-data REPLY returns `b''`. Attributes and route entries are literal bytes. No parameter-specific typed getter, unit-class schema, legacy eight-to-seven-byte compatibility conversion or short-form matcher is used.

Outgoing and expected incoming routes are independent declarations. The expected outer source, destination and complete route must match. The terminal incoming path byte must equal the requested unit, an additional consistency policy for this all-bridge profile. Raw unit0 retains direct/programming ambiguity. No logical network, cached object identity, authenticated device origin, physical delivery or causal freshness is inferred.

The endpoint must be a numeric IPv4/IPv6 address without a zone suffix. The client uses explicit address-family sockets and does no DNS lookup. It validates all arguments and mutable settings before connecting. `--local-unit` and programming addressing are rejected. At most six outgoing and six incoming route entries are admitted. `--checksum` selects the outgoing checksum; incoming checksums are always required.

The client permits one attempted exchange and one send, with no discovery, setup, retry, rollback or cancel. The monotonic I/O deadline is checked before operations and after each received chunk is recorded. A late final chunk remains evidence but cannot complete successfully. Socket close is attempted once; a close failure blocks success, without replacing an earlier error. There is no hard scheduler or cleanup-duration guarantee.

The stream accepts explicit two-byte confirmations, CR-terminated ASCII-hex frames and idle CR/LF separators. Each frame must satisfy the [strict incoming codec](pci-incoming-routing.md): headers06/86, direct count0..6, mandatory full-frame checksum and exactly one supported CAL. A matching `ReplyCAL` must carry the requested attribute, expected path and any declared exact count. Other valid frames/tags are retained as unmatched events. There is no special3B negative rule: unsupported3B frames fail as protocol errors, including original short-form coincidences. An explicit rejected confirmation fails separately.

Confirmation and response may arrive in either order. The complete final received chunk is processed before success; duplicates, malformed/unsupported frames or incomplete trailing fragments fail. Later unreceived bytes are outside that completion boundary. Default limits are256 events and32,768 received bytes, configurable to4,096 events and1MiB through the API or CLI flags.

Results are immutable and `as_dict()` detaches all JSON-safe evidence: sent bytes, received chunks, ordered events, response, counts and declared path. `last_error` retains the exact first exception, including `KeyboardInterrupt` or `SystemExit`; guarded attachment and `last_evidence` preserve evidence when attachment/export fails. CLI errors include partial evidence, or completed exchange evidence when subsequent result export fails.

## Original evidence and scope

The original probe invokes actual `bB/aW` setup, prepend, full/short matcher and separate pure getters, `cj` construction and the original `cr` counter. Cache objects bypass constructors; their retained identities and unchanged fields are checked. Original sender/receiver/dispatch paths remain uninvoked under OS and Java network-denial guards. The12-case admission pilot passed192 comparisons. The finite902-case matrix covers every attribute/header byte, counts, routes/cache branches, confirmation order, short/full overlap, malformed text and getter errors.

Original `bB` does not constrain full-match length/count/checksum or destination. Its inherited confirmation requirement is conditional, and its generic getter can consume trailing checksum bytes as data. Zero/nonpositive declared generic counts return null in that getter. Some accepted texts throw later getter errors. There is no dedicated3B-negative branch; an addressed frame can coincide with the short matcher for a particular source/attribute/length. Those observations are preserved in fixtures, while this public API applies the explicit stricter frame/path/count/dual-success policy described above.

The initial Python3.13 finite research capture executed all902 cases, then failed one prewritten normalized-message expectation: repeated `dl` processing changes the original substring offset from8 to10. The complete output and failed report remain immutable. Exact source inspection and independent review corrected that hypothesis; all captured rows matched post hoc, and a fresh Python3.10 run passed the corrected prewritten matrix. These are distinct historical outcomes. Fresh implementation acceptance executes all902 cases again under each supported interpreter and compares every captured semantic field, excluding only recorded nondeterministic UTC values whose ranges are checked separately.

The promoted original helper uses explicit macOS `CBUS_CGATE_JAVA`, `CBUS_CGATE_JAVAC` and `CBUS_LOCAL_CGATE_VENDOR` gates. Optional `CBUS_PCI_ROUTED_IDENTIFY_REPORT_DIR` directs owned reports; its default is relative to the copied test root. It compiles the unchanged sealed Java source and runs two bounded batches of480 and422, preserving pre-execution inputs and partial outputs without replay. No VM or shared C-Gate service is used. Socket acceptance uses independent ephemeral loopback peers.

[The pinned acceptance fixture](../research/fixtures/pci-routed-identify-acceptance.json) records104 focused tests passed on Python3.13.14 and3.10.20, with zero failures, errors or skips. Each run freshly executes902 IDENTIFY and428 unchanged RECALL original cases and includes independent IPv4/IPv6 peers plus CLI/routing regressions. All captured source and runtime hashes remained stable. The first focused3.13 run passed all104 tests but its final report-association guard rejected an incorrect report-directory selector; that run is preserved, and both final runs used the corrected selector. This is focused source acceptance, not a new installed-wheel or physical-device claim. The earlier research evidence is retained under `/Volumes/external/cbus-toolkit-research-20260915-pci-routed-cal/routed-identify-matrix-v1`; its seal is `f754b5e2830be526c52fa339e7d031e3005f8d9d6e4282fd93a1df7822c60ca9`.
