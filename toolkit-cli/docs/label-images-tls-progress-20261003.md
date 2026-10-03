# Lighting label controls, image metadata and TLS delivery

This batch implements three independent software chunks: explicit eDLT Lighting
label/status controls, byte-backed project/DLTP image metadata with ordered
Language initialization, and C-Gate TLS event delivery while a command is still
pending. The image FILE spelling used by Toolkit also works within the owned
services' named flat-repository profile. Complete Toolkit parity, original GUI
acceptance and physical rendering remain unfinished.

The frozen 44-module source and fresh installed-wheel selections have completed:
each passed 774 parent tests and 1,254 separate subtests, with ten explicit skips
and zero failures. Publication-head GitHub CI remains separate and unverified.
The [owned release receipt](../research/fixtures/label-images-tls-owned-release-20261003.json)
binds the actual epochs and their limits. This report, the top status paragraph
and the new receipt supply outcome annotations after those frozen executions;
they change no runtime, package, test or CI input. No feature-ledger category or
functional completion percentage changes.

## Implemented workflows

The existing `lighting` parent operation now accepts ordered `label_controls`.
Each history targets `label` or `status`, optionally selects a source type and
runs explicit callbacks. Generic dynamic type10 resolves to the underlying text
or image subtype from the selected variant. The implementation preserves Byte1
masks, exact Byte13/14 getter rules and the source's asymmetric index setters:
an unchanged label index does not re-resolve its type, while an unchanged status
index does. Changing semantic type resets its index through the virtual setter,
which can change the image subtype again with notifications suppressed.

The control engine implements Enter-key preview and Leave WriteValue→ReadValue,
four-arrow suppression of one selection, exact observed row membership,
editable Text versus indexed SelectedValue bindings, detach/rebuild order and
the source's synchronous ListChanged read predicate. `enter` abbreviates an
Enter-key preview; it does not represent focus Enter. An explicitly empty
FormattedDisplay remains empty rather than falling back to Name. Logical
drawing descriptors distinguish image, text and null-name branches; Graphics
and displayed pixels are outside the admitted profile.

The automatic metadata resolver issues bindings for the owning parent, exact
post-ordinary-Lighting PP, operation position/history and ordered source rows.
Manual caches, detached receipts and forged state cannot supply those facts.
Private seals also bind the owner identity. Pending text must receive an
explicit commit/read before the parent can prepare or save. Static text uses
the shared allocator for all 64 names and the current reference set, including
the old reference during replacement. Full retained names and the saved
63-byte UTF-8 image remain separate. Final normalization, CRCs and the single
parent PP save retain their existing ownership.

Lighting reads the current selected Group's DynamicAll when its getter is
consumed. Earlier Language changes therefore supply the current causal rows
for a newly bound Lighting control. A null or 255 Group has no selectable
DynamicLabels. This differs from initial SceneManager scenes, which retain
their original label objects until a source setter or explicit refresh changes
them. No automatic Framework rebind or notification dispatch is inferred.

Use `cgate edlt-project-images PROJECT --output FILE` to read the source-shaped
FILE directory and selected project BMP bytes, then supply the export and its
SHA-256 to automatic metadata. The export binds directory order, per-file
bytes and hashes. FONT lookup uses the prefix before the first comma without
trimming; other non-ICON kinds use the complete TagValue. The first exact
project-image key match wins. ICON uses the exact DLTP integer-key spelling.
The complete TagValue remains Name. Without the required providers, unresolved
image-dependent facts still refuse.

The BMP decoder admits a 40-byte BITMAPINFOHEADER, uncompressed BI_RGB and
1/4/8-bit indexed or 16/24/32-bit RGB samples. RGB32 storage does not establish
alpha behavior. The existing bound DLTP index path remains available; explicit
`--toolkit-dltp-decode` adds this decoder to every bound file. Neither input
establishes GDI+ equivalence, font rasterization, native directory authenticity
or physical display output. See [the usable CLI workflow](edlt-label-controls-images.md).

Image-dependent Language initialization independently reprojects the typed
Language prefix against exact original/projected XML, PP, owner and image
inputs. Old scene label generations keep their original DataStore identities;
an ActionSelector setter or explicit trigger-current refresh adopts current
labels. Cancelled/no-op Language histories preserve the original XML and
generation. Reset starts fresh ownership; later facts cannot enter earlier
observations. The callback profile does not reproduce original per-row COM or
WinForms scheduling.

cmqttd now flushes each admitted command-connection event after its plaintext
write, sharing the existing ten-second deadline across write and TLS flush.
Previously a buffered TLS writer could accept the event without delivering its
encrypted record until the active command completed. The fix delivers eligible
events while programming is pending; a stalled flush terminates the peer and
drops the active response future. Existing event filtering, correlated
programming receipts, serial command order and first terminal result remain in
force. Owned daemon tests join TLS, a scripted PCI and a miniature MQTT broker;
they prove software event/MQTT progress before both successful and uncertain
programming outcomes, with one STORE and no replay.

The FILE service recognizes Toolkit's `%PROJ%/PROJECT/...` spelling as an alias
of the existing virtual project storage only in its declared flat-repository
profile. A real project named PROJ keeps its existing namespace precedence.
Traversal, foreign/missing projects and malformed aliases refuse. This is not
host filesystem access or universal Schneider repository-template equivalence.

## Completed evidence and retained failures

| Scope | Completed result | Qualification |
| --- | --- | --- |
| Lighting types, control engine, parent wrapper, static proof and native binder | 48 parent tests passed; 105 separate subtests passed; no failures or skips | Five focused modules, including configured static regeneration. Exact source pins stayed quiet; pytest and JUnit/trace auditor returned 0. Native binder coverage includes canonical replay and one PP SAVE. |
| Lighting/control source proof | 29 managed bodies, 23 decompiled declaration spans and 60 static checks | Pinned original bytes read statically. No original or Framework instructions executed. Sanitized [annex](../research/fixtures/edlt-label-control-source-annex.json) and independently literal [vectors](../research/fixtures/edlt-label-control-vectors.json). |
| Image/Language final author successor | 138 parent tests passed; 28 separate subtests passed; one storage-case skip | Six modules, including copied/original-seal and owner mutation regressions. All 3,912 recorded inputs stayed quiet. The skip requires case-sensitive temporary storage; no original instructions executed. |
| Image source proof | 19 managed bodies, 5 decompiled declarations and 12 static checks | Read-only [source annex](../research/fixtures/edlt-scene-language-images-static.json) and [literal image cases](../research/fixtures/edlt-scene-language-images-vectors.json); no GDI/font/rendering acceptance. |
| Timeline/cursor issuance and label memo successor — #76 | 55 parent tests passed; no failures, subtests or skips | One focused module, with ten scoped inputs unchanged and pytest/auditor 0. Exact issued identity, original owner/payload, ordered branches and retained label memo content are checked. The earlier 32-pass registry checkpoint remains a separate predecessor. |
| Rust connection event module | 10 focused tests passed | Includes buffered TLS delivery and flush-deadline cancellation. This is separate from required workspace gates. |
| Actual owned daemon TLS/programming system module | Two tests passed | Scripted PCI/MQTT/TLS; successful and uncertain programming branches. No physical or original C-Gate acceptance. |
| Rust virtual FILE module | Six focused tests passed | Includes exact flat alias/canonical wire vectors and real-PROJ precedence. |
| Required Rust workspace checks | 8,711 tests passed; one private-input test ignored | Formatting, Clippy with warnings denied, workspace tests and release build all returned 0. Focused Rust rows above overlap this workspace run and must not be added to it. |
| Final integrated source and fresh installed wheel | Each: 774 parent tests and 1,254 separate subtests passed; ten explicit skips; zero failures | All 44 selected modules present; pytest and JUnit/trace auditor returned 0. The ten skips are five native/schema environment gates, four private static regenerations and one case-sensitive-storage case. These are focused selections, not the full Python suite. |
| New public image/Lighting CLI journeys | 18 passed in each environment: nine cgate-mock and nine cmqttd | Eight literal profiles per backend plus a lost-successful-save case per backend. All 844 synthetic PP fields and the complete 32-byte target record are checked with structural project/OID/tag/order preservation. Pending histories refuse before backup/PP writes; uncertain successful saves are not replayed. |
| Final package/import/input closure | 364 source/ZIP/installed files match; 1,064 import records across 623 processes; zero violations | Actual pytest startup and terminal imports are checked. All 3,913 recorded inputs and both binaries stayed unchanged during each final run. Recorded child imports do not imply terminal instrumentation for every child. |
| Fresh owned protocol comparisons | 64 primary plus four combined checks | Six modeled comparisons consume retained original cases against owned backends; no original instructions or current CLI correctness acceptance is added. |

The predecessor Lighting epochs remain separate: 37/73, native4/2 and33/55
parent/subtest results. Peer review then strengthened ownership seals, empty
display preservation and the 255 Group boundary before the 48/105 checkpoint.
The first native test import failed on a nonexistent helper name; it was fixed
to the actual API and its raw failure was retained. Static extraction first
failed because a declaration assertion assumed a different decompiler spelling;
the exact pinned spelling now reproduces the sanitized annex. ENOSPC preparation
failures occurred before the attempted edits/reads executed; verified generated
bytecode was reclaimed, with source and evidence preserved.

Image/Language work retains its earlier 83-test and 36-test checkpoints, plus a
128-pass/one-failure/one-storage-skip attempt whose rejection-message mismatch
was corrected in the 129-pass checkpoint. Independent review subsequently found
that a copied mutable image-provider seal could be re-fingerprinted after
changing rows. This real proof-integrity defect is corrected: issuance records
bind the exact seal identity and original payload fingerprint independently of
mutable fields. Language initializer issuance also retains the original owner.
The 138-pass successor covers copied seals, rewritten original seals and owner
mutation; the 129-pass predecessor remains separate. Its independent review
predates the distinct timeline/cursor successor and does not supply acceptance
for those changed bytes.

The #76 correction now covers five capability types: ProjectImages,
DecodedDltpImages, SceneLanguageInitializer, SceneInventoryTimeline and
SceneInventoryCursor. Timeline/cursor issuance independently binds the exact
seal identity, original owner and original payload. Review then found that
mutable retained label memo rows could supply changed names despite an intact
payload. The successor validates exact typed rows, order and all label fields
against the sealed epoch before use, preserving equal retained identities and
ordered validation/save branches. Both four-failure counterexample epochs and
the earlier 32-pass checkpoint remain retained; the current 55-pass result is
separate. These are bounded proof-integrity guards, not a hostile in-process
Python sandbox or original workflow acceptance.

TLS evidence retains a zero-test filter setup, a tiny-buffer handshake setup
failure, the actual buffered-event regression, initial system-test exact-row
oracle failures and the pre-implementation FILE alias refusal. The later scoped
passes do not erase those attempts or claim a full Rust workspace run.

The first final wheel preparation failed with ENOSPC while copying repository
references, after build/install but before pytest. It supplies no test
acceptance. The successor uses independent local APFS clones, a fresh wheel and
actual guarded pytest; source validation completed independently. The private
runner changed during these epochs to prepare safe wheel staging and correct
summary digest reporting. Each phase retains its entry runner copy separately
from the summary's end-path digest; the product/test input closures stayed quiet.
The preparation failure remains separately bound and supplies no product-test
acceptance.

The public graph comparator preserves exact scalar/attribute values, child
order, comments and processing instructions. It preserves whitespace-only leaf
text, drops whitespace-only parent text with children and all whitespace-only
tails, and does not consult xml:space. It does not assert byte-exact XML fidelity.
The Language profile permits only its declared default marker change and
selected-language removal; unrelated languages and OIDs remain intact. Fresh
snapshot reads and PROJECT SAVE/CLOSE/LOAD do not establish backend restart,
original GUI operation or physical rendering.

## Remaining work and release closure

The receipt records current source/wheel input closure, public case outcomes,
required Rust checks, independent reviews and retained author failures. Previous
image results are not rebound to the copied-seal or timeline/memo successors.
Exact publication commit and new-head CI are release-owner follow-up fields;
local validation does not infer CI success. The previous run
[37075359153](https://github.com/mitchell-johnson/cbus/actions/runs/37075359153)
is completed/cancelled: Rust and installed-wheel jobs succeeded,
source/interoperability was cancelled and native/physical jobs were skipped.
It is historical evidence, not a green full-release result.

Further parity work remains for automatic Framework binding/notification
scheduling, culture-sorted static suggestions, modal/exception behavior, broader
widget adapters and image codecs, original cold native workflows and physical
label rendering/persistence. The executable census and its functional
denominator remain incomplete. Deferred issues 72–75 retain their existing
acceptance/protected scopes; no VM, vendor instruction or real house execution
occurred in this batch. [Implementation status](implementation-status.md) and
`coverage --require-complete` remain the authoritative completeness gates.

## TLS test-certificate portability successor

Publication [CI run 37085008370](https://github.com/mitchell-johnson/cbus/actions/runs/37085008370)
for `c519ce5d8ddfa070817df202c15af9d211539dac` exposed two handshake
failures in the cbus-cgate library: **567 passed, two failed and one
private-input ignored case**. The command stopped before later workspace
crates. The retained server failure is `AlertReceived(CertificateUnknown)`;
the original CI certificate bytes and precise client verifier error were not
retained.

A clean controlled OpenSSL CA:TRUE profile reproduced both failures on the
unchanged two helper sources. Changing only basicConstraints to CA:FALSE
passed both tests. The first controlled profile instead failed with
`ExtensionValueInvalid` because its SAN setup was malformed; that setup
failure is retained separately. Attribution to a CA certificate used as a
server leaf is controlled reproduction plus verifier-source inference, not a
directly observed original-CI `CaUsedAsEndEntity` exception.

The correction changes only two Rust test certificate helpers to use an
explicit CA:FALSE, serverAuth and IP subjectAltName leaf configuration.
Production TLS verification and event flushing are unchanged. The two unit
and two daemon checks also pass while the external default profile still
declares CA:TRUE. Certificates and private keys remain ephemeral and are not
published. An initial successor format check failed before any tests;
formatting changed no lexical tokens, configuration strings or production
prefix. That predecessor and the original CI/configuration failures remain
separate evidence.

The corrected mandatory Rust gates all exit zero: `cargo fmt --check`,
workspace Clippy with warnings denied, workspace tests and release build.
Workspace tests pass **8,711 cases with zero failures and one private-input
ignored case**; all **464 inputs** stayed unchanged. Both selected release
binaries are byte-identical to the previous release. These outcomes are
separate from the controlled certificate and focused helper checks; overlapping
counts are not added.

Six fresh owned modeled comparisons pass **64 primary cases plus four combined
checks**, with seven driver commands exiting zero. Their source maps retain
**1,147 occurrences across 214 unique paths**. The contract inventory is
byte-identical. Metadata generation first changes only `parity-evidence.json`
and `parity-obligations.json`; the second generation changes nothing and keeps
all **3,914 inputs** quiet. `make check-parity-register` exits zero. These
comparisons add no original-instruction, CLI or hardware acceptance.

The focused eight-module source and fresh installed-wheel selections each
pass **174 parent tests and 587 separate subtests**, with **zero failures or
skips**. Both epochs keep all **3,914 inputs** and selected binaries unchanged.
All **364 current source/ZIP/installed package files** match: **362 retain
their previous bytes and two parity JSON resources change**. Python
implementation code is unchanged. The prior 44-module selections and their
364-file closure remain historical evidence for `c519ce5d`; they were not
rerun or newly credited. A receipt-builder preparation error also remains
retained and executed no products or tests.

The [separate successor receipt](../research/fixtures/label-images-tls-ci-leaf-successor-20261003.json)
has SHA-256
`ae447c6e6eef888f68ac28d7d505c3905515898054243289a39e5b875ebc6663`.
The earlier receipt `b5bc3bb9…` remains unchanged. This appendix and the top
status annotation were added after the frozen successor epochs; they alter
only two Markdown files. The new receipt separately records their validation
context. The correction commit and its CI await publication, so no new-head
green result is claimed. Full Toolkit parity, the complete functional
denominator and original/Framework/native/physical acceptance remain
unfinished; protected issues 72–75 are unchanged.
