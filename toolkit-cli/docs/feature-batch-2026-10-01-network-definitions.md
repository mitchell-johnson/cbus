# Closed network creation, runtime catalogue and GET dispatch

The Python Toolkit CLI can now create a closed project network through cmqttd using `cgate database network-new`, then save, close and reopen its complete database model. The new typed `cgate network definition` family provides explicit list, create, rename, delete, flush, load and save operations. cmqttd's `NET LOAD DB` reads the current numeric tag-network definitions instead of requiring an earlier internal snapshot. A fresh Cni, Serial or Bridge network can therefore enter its closed runtime catalogue immediately after `DBCREATENET`.

This is a bounded milestone for [issue 27](https://github.com/mitchell-johnson/cbus/issues/27), [issue 29](https://github.com/mitchell-johnson/cbus/issues/29) and [issue 32](https://github.com/mitchell-johnson/cbus/issues/32). It establishes the tested closed-model setup and catalogue lifecycle, while broader obligations in those issues remain open. No house network, Windows VM, real adapter or physical C-Bus device was used.

The [operator guide](network-definitions.md) gives the command syntax, DB-versus-FILE rules, recovery after incomplete creation and current limits. The [corrected acceptance receipt](acceptance/2026-10-01-network-definitions-get-dispatch/acceptance.json), SHA-256 `d27cb05bb2f93cb2ac97ba2146c75ddf636fb80f9d5a8bf51bc1001b9795fb57`, binds the final source, installed-wheel, Rust and original-server evidence described here, with 55 digest-bound public derivatives. The [earlier receipt](acceptance/2026-10-01-network-definitions/acceptance.json), SHA-256 `c9ccc9b1056d5e2227a8d8c5210a5658605e0dea5cee70b4d0c0c7f1bbcb94ce`, remains immutable historical evidence for the held `b7b4e5d` candidate. It does not clear the GET dispatch defect found during review.

## Delivered behavior

`network-new` validates its selected project and creation arguments, selects the project on the command connection, sends one `DBCREATENET` and then one `NET LOAD DB`. Creation accepts cmqttd's existing 200 completion or original C-Gate's exact `301 OID=<UUID>` receipt. Loading must return exactly 200. A different response, lost reply or interrupted load produces an error and is never replayed. A created database row may already exist after an incomplete load; the operator must inspect that row and the runtime catalogue before choosing a recovery action. There is no implicit interface open, discovery, project save, deletion or rollback.

Every typed catalogue operation requires `--project`. Project, name, type, address, selector and repeated option tokens are checked before connection. The command then selects that project and issues its single catalogue operation. LIST admits only 131 or empty 132; mutations require exactly 200. RENAME exposes the native `nofixrefs` selector through `--no-fix-references`. Options are retained in their supplied order. These commands do not silently save the project or open an interface.

DB LOAD derives current numeric definitions from the loaded tag database, refreshing matching names' interface type, endpoint and options. Unrelated and renamed active definitions remain, including a definition whose tag row was subsequently removed. Legacy internal DB snapshots restore custom names outside canonical decimal 0..255. They cannot resurrect a removed numeric row from stale snapshot data. Existing physical bindings remain immutable: refreshing or renaming catalogue metadata cannot move cmqttd's shared PCI or replace its live state and observations.

Single-property runtime GETs expose `Name`, `Type`, `InterfaceAddress`, `Interface` and `Options` only through an exact explicit `//PROJECT/NAME` catalogue path. Interface and InterfaceAddress are endpoint aliases. An edit to the database Network document leaves these catalogue fields unchanged until explicit DB LOAD; the acceptance journey verifies the old value before load and the refreshed value afterward. Legal names such as `cgate`, `projects`, `cbus` and `!<issued-OID>` remain available for catalogue definitions. Creating them preserves the established generic bare-name and issued-OID GET responses; reading their own catalogue fields requires the qualified path. Wider GET tables and other selectors retain their previous limits.

FILE selects cmqttd's durable internal snapshot. It is not a host path. A missing FILE snapshot is a successful empty load, including when active definitions already exist. A saved snapshot can restore all of its names to an empty catalogue. Existing-name collisions are refused atomically by cmqttd. Internal catalogue persistence is separate from PROJECT SAVE and project close/load.

## Current acceptance

The corrected final source and fresh installed wheel each passed **151 distinct parent tests and 661 subtests**, with no selected failure, error or skip. The focused selection includes typed definitions and public CLI wire tests, the actual daemon lifecycle, existing native grammar/network/CGL cases, the static skip census, release gates, the three differential validators and the parity register. The configured original-server classes `NativeOracleTests`, `NativeNetworksTests` and `NativeCGLTests` were deliberately unselected; the fresh original capture below is separate evidence, not a claim that those opt-in classes ran. No full suite was run.

The wheel SHA-256 is `a584f3f10cf959caf6e2ba283c80122e80850dedd0c3d74920fcee24a179e10d`. All **325 package Python/JSON files** matched the frozen current source, wheel archive and fresh installed package. The driver retained actual import origins, exact arguments, exit codes and output hashes. The producer separately imported the native and network-definition modules from the selected package. Source, package, binary and wheel bindings remained unchanged across the final executions.

The standalone producer completed **147 actual public CLI commands in each environment**. Each command owned one independently recorded, completed C-Gate connection. There were 145 exact ordinary command-sequence checks and two exact DBSETXML document checks per journey. The complete source closure contained 1,128 bindings. Both journeys verified:

- Cni, Serial and Bridge network fields, numeric identity, OIDs, runtime Name/Type/Interface and closed interface state after sequential creation;
- complete project XML equality after explicit save, close and load, plus unchanged state after duplicate creation refusal;
- eight complete before/after generic GET comparisons for Name and Type over four legal colliding catalogue names, followed by qualified catalogue metadata reads and deletion of the temporary definitions;
- empty LIST 132, empty/repeated DB loads and missing FILE loads on empty and nonempty catalogues;
- custom options through create, `nofixrefs` rename, DB snapshot restoration and FILE restoration;
- renamed/unrelated definition retention, conflicting numeric definition refresh and removal of stale numeric snapshot entries;
- independent runtime readback before and after a complete database interface edit and explicit DB LOAD;
- preservation of a previously active definition after its tag Network is removed, followed by explicit deletion and refusal to resurrect it from a stale snapshot;
- FILE restoration, duplicate/name/missing-target refusals and atomic rejection when an earlier noncolliding saved name precedes a later collision;
- explicit project isolation across two synthetic projects.

The producer required the exact complete eight-frame owned daemon initialization transcript **before** the first model command. Its PCI capture remained byte-identical throughout the catalogue workflow. The owned Cni trap received zero connections and the synthetic Serial path remained absent. Serial open syscalls were not instrumented, so absence of a created path is not represented as syscall-level proof. Daemon termination/wait, C-Gate and PCI listener closure, broker socket closure and proxy thread/port cleanup were verified.

The generic probes explicitly select NEWNET and issue GET in the same public `cgate run` connection. All eight actual generic baselines are failures: bare `cgate`, `projects` and `cbus` Name/Type return 402, while Name/Type for the issued Network OID return 401. After creation, their complete response JSON, stdout, stderr and exit status remain identical. This proves preserved dispatch for those inputs; it does not establish successful generic OID lookup or broad native GET parity.

These layers overlap. The owned producer test is inside the 151-test selection, and the standalone 147-command journey repeats that workflow while retaining full raw artifacts. Subtests, CLI command counts, source/wheel repeats, Rust cases and original raw commands are reported separately; they are not added into a larger unique-test or feature-completion count.

Sixteen focused Rust tests passed: eleven module tests, four retained service tests and one actual daemon system journey. Thirty native literal vector cases passed. The GET regression includes 48 selector checks: 20 unchanged generic responses, 20 qualified field replies and eight malformed-selector checks. These are subcases within the focused tests, not additional unique tests. Formatting, Clippy with warnings denied and the release build passed. The retained cmqttd binary SHA-256 is `c0f1ce4ec669dee12b7a779abbcfb876c34d80b613a308711bb91bab801d9445`; the mock is `a963aa5fc02fe08419e36e765e81f4a88b9598aa4348b10426656672c2576ebb`.

Six genuine current-binary SESSION_ID, tagged-session and direct/combined Unit-XML differential replays refreshed their source-bound receipts. Their frozen closure contained 1,063 bindings. The contract inventory, physical applicability and packaged parity register were regenerated from those inputs. The static skip census now accounts for 613 modules; that is repository inventory, not 613 executed test modules.

## Original C-Gate evidence

The retained disposable original C-Gate 3.4.0.2001 capture contains **135 raw commands** and **17 normalization/contract audit checks**. Its fixture SHA-256 is `32d0ea53000391dee0ee9d8b9e54496e6df916395fe8e065de78766a5397b596`. Probe and LocalCGate helper hashes are retained, together with the vendor JAR and Java 11 hashes. Generated OIDs, task-owned paths/ports, timestamps and host metadata have explicit normalization tokens. All networks remained closed and all owned original-server children were cleaned up.

That capture pins fresh, empty, repeated and sequential DB LOAD; matching-name refresh; numeric runtime conflicts; Name/Type/Interface/InterfaceAddress/Options readback; option order and unrelated-definition retention; missing FILE no-op; explicit project isolation; deleted tag/runtime retention; later FILE collision partial insertion; runtime-to-tag SAVE DB materialization; and project save/close/load. Original DBNEW returned 500 with its selected XML unchanged, so successful native DBNEW clearing is not accepted from this experiment.

Fresh corrected-package Python **3.13.14** source and installed-wheel journeys each completed **79 public CLI commands** against owned original servers. Each call has its exact wire sequence and output bound in the corrected public receipt. The three network-new operations returned actual 301 UUID receipts followed by LOAD 200. Complete Network subtrees survived native PROJECT SAVE/CLOSE/LOAD; whole Installation XML differs because original SAVE adds Config/metadata. These runs use the same frozen package as the cmqttd acceptance and verify owned listener/proxy/trap cleanup. The retained raw 135-command boundary probe used system Python 3.9; it did not exercise the Python Toolkit package. No new original-server comparison of the generic GET collision cases is claimed.

The original public CLI tests also retained a native FILE boundary: restoring a saved lowercase `cni` definition with `owned=yes second=two` returns 408 while attempting to load `CBusSecond=twoNetwork`. The task-owned serialized network definition file is byte-bound. Clean definitions without options do restore, and their original GET Options value is literal `null`. This is accepted evidence of a limitation, not a successful options roundtrip. An independent root audit checks the exact 301/200, 408 and `null` response bytes in both original journeys. cmqttd's internal snapshot can retain options; native FILE format and option restoration parity remain outside this batch.

## Retained failures and corrections

Exact-candidate review found a real GET namespace shadowing defect after the earlier acceptance. A genuine rerun with the preserved `b7b4e5d` cmqttd binary retained **48 public CLI calls through the failure**: bare `GET cgate Name` changed from a confirmed 402 refusal with CLI exit 1 to `300 cgate: Name=cgate` with exit 0 after a legal runtime definition named `cgate` was created in the selected project. The old binary, raw replies and failed receipt remain unchanged. Its owned process and proxy were cleaned up, its before/after source/package/binary bindings matched, and a separate audit confirmed no PCI traffic beyond the eight startup frames.

The correction limits catalogue lookup to exact explicit `//PROJECT/NAME` paths. It preserves generic server and issued-OID dispatch without prohibiting legal catalogue names. The corrected source and wheel journeys check the complete generic responses before and after creation in one selected session, then confirm that qualified paths return the definitions' own Name and lowercase `cni` Type. The earlier 114-command candidate did not cover this regression and remains historical evidence rather than current clearance.

The initial old-binary run reproduced the actual gap: `DBCREATENET` completed, followed by `NET LOAD DB` returning **408 “Network definitions file not found”**. The repaired daemon passes the same public creation sequence. Earlier failed receipts were preserved without editing them into successful executions.

Other attempts exposed acceptance-harness problems, each corrected in a new run:

- The first readiness parser expected a 300 JSON envelope instead of the actual `200-` continuation. It performed only readiness reads.
- The first positive wire test looked for the `code` Python property in serialized JSON; the concrete result serializes `status`.
- The first typed preflight test referenced a nonexistent parser helper. The test was corrected to the current parser entry point and rerun; its original failing and corrected JUnit records remain distinct.
- A relative `--python` path was evaluated from the CLI subprocess working directory. The producer now makes it absolute while preserving a virtual-environment symlink.
- A synthetic DBDELETE setup command omitted same-session project selection. The fixture now issues explicit PROJECT USE followed by DBDELETE through the public `cgate run` command; no product deletion behavior was changed.
- The earlier `pci_connected` checkpoint preceded completion of daemon initialization. All 114 functional CLI steps passed, but the PCI diff contained the remaining literal `|` and four setup frames. The final producer waits for the complete exact startup transcript before model commands and retains the strict unchanged-PCI check.

The original CLI preparation retained a source metadata requirement error, a sandbox-denied local-listener setup, an incorrect manual CREATE type-casing expectation and the newly observed option FILE/null boundaries. The final bounded driver records those native refusals explicitly. Initial publication privacy scans also refused literal temporary-root and system-tool paths embedded in evidence scripts; declared roles were added, and partial derivatives remain private.

The two earliest producer receipts predate after-execution binding samples, and their limitation remains explicit. Later failed runs retain unchanged before/after bindings and owned cleanup. The corrected focused public wire selection passed five parent tests and 37 subtests, including legal colliding names, native 301 creation, malformed receipt refusal, unknown completion refusal, lost replies and preconnection invalid-input refusal. These five tests are included in the final 151-test selections.

## Explicit deviations and outstanding work

Three observed native behaviors remain different in Rust:

1. cmqttd DBCREATENET retains its existing 200 creation completion; original C-Gate returns a 301 UUID OID. The CLI admits both verified shapes, but that does not make the wire receipts identical.
2. cmqttd NET SAVE DB stores an internal catalogue snapshot. Original SAVE DB can materialize missing runtime definitions as tag Network rows, including a numeric runtime name such as **42**, with its native `n42` TagName and NetworkNumber 255. This missing runtime-to-tag projection is not limited to nonnumeric custom names.
3. cmqttd FILE collision refusal is atomic. Original FILE LOAD can insert earlier noncolliding definitions before a later collision returns 408. The current Rust behavior is an intentional safety deviation.

Original-native FILE option parsing and restored `null` semantics remain outside the supported roundtrip contract. Real adapters, opening extra interfaces, broad native GET tables, bridge-reference rewrites, complete Toolkit dialog lifecycle, vendor repository interchange, physical commissioning and real-device persistence/recovery remain outside this batch. Preserving cmqttd's immutable shared PCI is an ownership boundary, rather than proof of native multi-interface behavior.

The broad ledger remains **18/42 (42.86%)**: 18 implemented areas, 22 in progress and two pending. The functional denominator is still incomplete and **zero obligations are fully accepted**. These successful bounded workflows do not establish full Toolkit or full C-Gate behavioral parity and do not change that completion assessment.
