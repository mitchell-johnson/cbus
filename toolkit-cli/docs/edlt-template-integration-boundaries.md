# eDLT template integration boundaries

Reviewed source chain: `7a23fb5d42d6f74a443df251622ca9f5f6e46565` → `48112a9cbbd507900479a243f2aae561b5188fcc` → `10cbfa07d188ad823aa69db7f73bf973cb122d80` → `d951e88222b264509e1fa3dedde46b4fc67f089a`, after `8f1608b91d3ce155e1ce42e8b0df0dfc4ecd91d4`. Untracked save-validator investigations are excluded. This document records review/proposed acceptance; it is not a new execution receipt.

The source owns flat UTF-8 template XML (1 MiB/4,096 fields), ordered CRC and explicit export/preview. It rejects attributes, namespaces, comments, DTDs, CDATA, entities, whitespace-only/XML-sensitive values and conflicting identities. The CLI input wrapper has an independent 8 MiB bound. Ordinary duplicate XML fields retain ordered assignment history. Exact raw token arrays are necessary: short setters retain old tails, and raw inequality can mark dirty even when normalization leaves identical tokens.

Assignment staging requires caller-supplied post-BeforeChange state. Second-model construction, combined lifecycle, Reset provenance and terminal preparation each use issuer-bound immutable receipts with source/cache/spec identities and cancellation/stale/forgery guards. Terminal preparation consumes the retained model once and computes numeric PP plus five CRC fields. It does not flush active controls or execute serial, Scene-widget or unit-validity gates. Every Apply boundary remains refused before target access.

The integrated root CLI now registers `edlt-templates inspect|export|preview|apply`, and the parent exposes `template_lifecycle_stager()` as a separate local adapter. The supplied patch documents preserve historical proposed edits. Registration supplies local interfaces only; it does not admit an applying parent operation. Public Apply remains an unconditional refusal before input reads.

The separate [offline Save-validation stage](edlt-template-save-validation.md) now supplies guarded serial/Scene-widget/unit predicates with frozen caller facts and lazy getter order. It does not establish active control values or original callbacks. Concrete next implementation: join source-bound Reset, panel population and both BeforeChange phases with initialized control/binding state. Model exact callback outcomes, cancellation/interruption, stale receipts and SaveDialog/BeforeSave ordering. Only after those gates pass should an explicit owned database transaction stage the issued terminal image once, save PP/project with uncertain-save fail-stop behavior and independently reload all fields/CRCs. A retained original successful load/rebind/Apply sequence plus failure/cancel branches remains necessary for full original template parity; database durability alone cannot supply it.

## Proposed focused acceptance

Run committed `test_edlt_templates*` and `test_edlt_template_*` modules plus owning `test_edlt`, lifecycle, Reset and parent-transaction regressions against source and a fresh installed wheel. Supply `CBUS_UNITSPEC_DIR` for the exact private KEYGL5 specification when selecting the retained Reset comparison; otherwise report its skip. Keep research fixtures and helper modules explicitly available in the wheel acceptance workspace. Registering root CLI has focused public dispatch checks covering inspect/export/preview and Apply refusal without input reads or target access.

The terminal native test module itself tests cleanup/error reporting and starts no service. Fresh owned native durability is a separate helper invocation with explicit `--vendor`, `--java`, `--spec-dir` and new `--output`; keep all synthetic networks closed and require zero CNI-sentinel connections, one confirmed PP save/project save, fresh reload, five CRC/all-field equality and owned cleanup. It must not be presented as template import/Apply acceptance. Root should record actual source/wheel/native results separately.

Exclude all original-code producers, Mono/.NET probe compilation or launch, proxy execution and CPU/JIT replay pending a specifically approved network-denied harness. Static inspection and retained fixture comparison remain separate. Fresh WinForms/Windows full-form and physical transfer/rendering/power-cycle acceptance remain open.

## Historical native receipt privacy

`edlt_template_terminal_native_attempt1.json` is now a declared public derivative. The raw original is preserved privately with directory mode 0700 and file mode 0600. Only `/service/java`, `/service/argv/0` and `/service/argv/6` are normalized to runtime/vendor path roles. Original technical hashes, execution outcomes and scope are unchanged, and derivative metadata retains the original fingerprint without relabeling execution as current acceptance.

Raw historical receipt SHA-256: `7926101e597d90ed2c9110a605e07db6b7d83d8fd0be62e709360eba201de549`. Fingerprint computed by read-only inspection; no native/original execution was rerun.
