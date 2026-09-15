# Explicit routed RECALL

`RoutedRecallClient` performs one direct RECALL through caller-supplied route bytes. It requires an explicit expected incoming path, one positive PCI confirmation and one exact REPLY. This is a separate bounded transport; `PCIClient`, its stream parser, MMI, commissioning and the simulator are unchanged.

```python
from cbus_toolkit.pci import RecallCAL
from cbus_toolkit.pci_routing import RoutedCALCommand
from cbus_toolkit.pci_routed_recall import RoutedRecallClient, RoutedReplyPath

command = RoutedCALCommand(4, RecallCAL(30, 1), bridges=(40, 41))
expected = RoutedReplyPath(20, 16, (21, 4))
client = RoutedRecallClient("127.0.0.1", 10001, timeout=5.0)
# Requires an independently configured endpoint; no connection occurs above.
result = client.exchange(command, expected=expected)
print(result.data.hex())
```

The corresponding CLI accepts the same explicit bytes:

```sh
cbus-toolkit pci --host 127.0.0.1 --port 10001 --timeout 5 routed-recall 4 30 1 \
  --bridge 40 --bridge 41 --expected-source 20 --expected-destination 16 \
  --expected-route 21 --expected-route 4
```

The endpoint must be independently configured. `--bridge` and `--expected-route` repeat in their respective wire order. `--checksum` selects outgoing command checksums; incoming checksums remain mandatory. `--local-unit` is rejected for this explicit-path operation. `--max-events` and `--max-received-bytes` expose the bounded coordinator limits. CLI failures carry partial evidence, including a completed exchange if only subsequent result export fails.

Outgoing and expected incoming paths are independent inputs. The incoming outer byte, destination and complete route must match exactly. The final declared incoming path byte must equal the requested unit; this is an added consistency requirement for the selected all-bridge profile, not a resolved device identity. Byte0 remains literal and its direct/programming ambiguity is reported. No cache lookup, route discovery, topology validation or source authentication occurs.

Only numeric IPv4/IPv6 hosts without zone suffixes are accepted. Sockets use explicit `AF_INET`/`AF_INET6`; no DNS lookup is used. Inputs and current settings are revalidated before connecting. The command must be an exact direct `RecallCAL` with1..30 requested bytes. There are at most six bridge entries. Programming addressing, writes and multi-frame responses are outside this API.

A client permits one attempted exchange. It sends one complete uppercase command with a local confirmation byte and the explicit command-checksum setting. It sends no BASIC discovery, setup, cancel or retry. The local tag does not prove freshness across external traffic. A monotonic I/O deadline covers connect/send/receive, and a late final received chunk is retained as evidence but cannot succeed. Socket cleanup is recorded separately; a close error prevents success. There is no hard scheduler or close-duration guarantee.

The stream profile accepts explicit two-byte confirmations, CR-terminated hexadecimal frames and idle CR/LF separators. It does not synthesize implicit confirmation, accept LF-only frames, strip flow-control bytes or implement original receiver notification branches. Incoming positive frames use the existing [strict received-route inspector](pci-incoming-routing.md): headers06/86, route count0..6,15..87bytes, full original checksum, and exactly one supported CAL. The matching REPLY must have the requested parameter and exact data count. Other valid admitted frames/tags are retained as unmatched events.

A matching positive confirmation and REPLY can arrive in either order. Every byte in the final received chunk is processed before returning. Duplicate matching events, a rejection, malformed data or an incomplete trailing fragment fail the operation. Bytes that arrive only after that boundary are not claimed observed. Event and byte limits default to256 and32,768; callers can explicitly raise them up to4,096 events and1MiB.

A checksum-valid addressed envelope beginning with3B can be recorded as an `observed_negative_prefix` and rejected when its whole path matches. The suffix remains opaque: no new negative CAL grammar or parameter semantics are claimed, and the shared CAL decoder is unchanged. Positive success still requires the strict one-CAL inspector. Other malformed or unsupported envelopes fail as protocol errors.

The frozen result retains actual sent/received bytes, the declared expectation, ordered events, the matching response and returned data. `as_dict()` returns detached JSON-safe evidence. `last_error` preserves the exact first failure object, including `KeyboardInterrupt` and `SystemExit`; guarded exception attachment and `last_evidence` preserve partial results when attachment is refused. Cleanup/reporting failures do not replace an earlier operational error. Rejected subsequent use clears old operation evidence and performs no connection.

## Original evidence and deliberate differences

The retained-cache original matrix executes the actual `cg/cf/aO/aW` setup and matcher methods, `cj` constructor and `cr` counter, with original sender/receiver/dispatch paths uninvoked. It covers428 cases and4,708 prewritten comparisons, plus the historical12-case/108-comparison admission pilot. Network/unit cache objects bypass constructors; their identity and unchanged fields are preserved explicitly. Separate OS and Java guards deny network access.

The original matcher accepts a wider header predicate, does not compare destination or validate checksums, conditionally requires prior confirmation only when `n=true`, and recognizes negative replies by an uppercase3B prefix alone. The public path/checksum/header/count policies and dual-success return condition are stronger declared requirements. Provisional early-reply retention follows the original default `n=false` order, not the early-reply behavior of `n=true`. The implementation does not claim original cached-object correlation, asynchronous receiver timing or physical transport parity.

The original finite report is SHA256 `6a03ef1e5ee2ae8d6d54302ea6ad38899d840f36ccec31ce89313e845a2e6063`, preserved externally under `routed-recall-original-v1`; the research seal is `3b05dd73f95aede9ca70f2178d51c8d578995898dc5f7b82676108a14b36b52f`. That historical controller was Python3.9.6 observed afterward. Fresh acceptance uses pre-pinned supported interpreters, the unchanged promoted Java probe and captured per-case semantic hashes. Only nondeterministic timestamps are normalized; fresh runs check actual timestamp ordering/ranges separately.

The new original test uses existing explicit `CBUS_CGATE_JAVA`, `CBUS_CGATE_JAVAC` and `CBUS_LOCAL_CGATE_VENDOR` gates on macOS. Optional `CBUS_PCI_ROUTED_RECALL_REPORT_DIR` selects an owned report directory; otherwise it uses the copied test root's runtime directory. No VM or shared native service is needed. Peer tests create their own ephemeral IPv4/IPv6 loopback sockets, record intended command bytes independently and verify closure.

## Focused acceptance

[The pinned acceptance fixture](../research/fixtures/pci-routed-recall-acceptance.json) records73 tests passed on Python3.13.14 and3.10.20, with zero failures, errors or skips. Each run includes the six new CLI tests, one fresh428-case original process under the pre-pinned supported interpreter, and independent IPv4/IPv6 loopback peers. The selected package/harness/fixture/runtime bytes remained unchanged. This is focused source acceptance; it does not replace a complete installed-wheel run or establish physical-device compatibility.
