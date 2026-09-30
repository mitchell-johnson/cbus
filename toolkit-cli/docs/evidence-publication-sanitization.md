# Publishing differential evidence without local coordinates

[`sanitize_evidence_receipts.py`](../research/sanitize_evidence_receipts.py)
creates a declared derivative of an existing raw receipt. It performs no replay,
native execution, hardware access or source fingerprint update. Passing this
helper proves that a permitted metadata transformation preserves the receipt;
it does not create new behavioral or physical acceptance.

The supported families are SESSION v2 (`session`), tagged SESSION v1 (`tagged`),
DBSETXML unit mapper v1 (`unit`), and the scoped closure metadata document v1
(`closure`). Both raw and derivative differential receipts must pass their
unchanged family validator against the current checkout. A stale source binding
must be replaced by a genuine producer run before sanitization.

## Transformation contract

| Input field | Published derivative | Preserved evidence |
| --- | --- | --- |
| SESSION/tagged `/rust_artifact/path` | Omitted; `/rust_artifact/name` records `product` | Artifact SHA, provenance and every other artifact field |
| Unit mapper `/binary/path` | Omitted; `/binary/name` records `product` | Artifact SHA, provenance and every other artifact field |
| Differential `/command` | Nonempty reproduction template using named environment roles | Script, flags, argument order and safe report basename |
| Closure `/receipts/N/integration/commands/M/command` | Role template only when a local coordinate is present | Selected tests and order, options, scope, counts, skips and failures |

Only these coordinates change. Whole-document payload equality is checked after
accounting for the declared field transformations. Wire bytes, native inputs,
binary hashes, source fingerprints, results, timestamps, acceptance scope,
closure claims and invalidation bindings remain unchanged. Unknown path roles
and compound shell commands are refused. The remaining-coordinate scan rejects
recognized local filesystem roots, home-relative paths and Windows drive paths,
including unmapped metadata. Synthetic loopback wire values and public original
binary provenance are retained. This scoped path check does not replace the
separate audit for private endpoints, identifiers, topology or live states.

Each derivative adds exactly one top-level `publication_sanitization` object:

| Key | Meaning |
| --- | --- |
| `format` | `cbus-evidence-sanitized-derivative-v1` |
| `raw_file_sha256` | SHA-256 of the exact original bytes, before JSON reformatting |
| `raw_retained_privately` | `true`, written only after private raw bytes are verified |
| `field_mapping` | Array of JSON pointers, `omit`/`role_template` actions and normalized path roles; artifact omission also identifies its added name pointer |
| `command_form` | Identifies the command as a reproduction template; exact invocation remains private |
| `working_directory_role` | Toolkit CLI context; source/installed acceptance scope remains in the receipt |
| `technical_payload_preserved` | `true`, after the equality check |
| `new_execution_claimed_by_sanitization` | `false` |

No raw value or private archive path appears in this marker. Closure markers stay
at the document root: the existing strict receipt, integration and command
schemas cannot accept added nested metadata. The canonical closure document
retains derivative provenance when the register imports its `receipts` array.
The regenerated register binds the canonical closure document's derivative SHA.

Raw archives must be outside every Git checkout. The helper writes immutable,
SHA-named raw copies, verifies exact bytes, and uses directory mode `0700` and
file mode `0600`. Existing matching copies are reusable; conflicts and symlink
targets are refused. Preserve these private originals according to the owner's
private evidence retention policy. Do not add them to Git or external reports.

## Producer and publication sequence

1. Finish the source changes and run the six genuine Rust replays through their
   existing producers. Keep the resulting raw receipts private. This is the
   producer's responsibility; a sanitizer run cannot refresh their fingerprints.
2. From `toolkit-cli/`, sanitize each raw receipt into its canonical fixture path,
   setting the appropriate `--kind`. Use the same process for the canonical
   [`closure-receipts.json`](../research/closure-receipts.json) when its scoped
   integration commands contain private local coordinates. Retain every raw
   original before replacing a canonical input.
3. Run `python research/build_parity_register.py` on those actual current inputs.
   This genuine offline generator updates packaged report artifact hashes,
   record hashes and source digests. Never manually replace fingerprints or
   hashes in generated evidence.
4. Run `python research/build_parity_register.py --check` and the five focused
   differential, publication and parity test modules listed below. Review the
   changed evidence and closure document for other personal setup information
   before publication.

```sh
python research/sanitize_evidence_receipts.py \
  --kind session --input "${CBUS_PRIVATE_RAW_RECEIPT}" \
  --output research/fixtures/cgate-session-differential-cmqttd.json \
  --private-raw-dir "${CBUS_PRIVATE_RAW_ARCHIVE}"

python research/build_parity_register.py
python research/build_parity_register.py --check
PYTHONPATH=src:. python -m pytest -q \
  tests/test_sanitize_evidence_receipts.py \
  tests/test_cgate_session_differential.py \
  tests/test_cgate_tagged_session_differential.py \
  tests/test_cgate_dbsetxml_unit_differential.py \
  tests/test_parity_register.py
```

Role commands use `CBUS_EVIDENCE_PYTHON`, `CBUS_ACCEPTANCE_PYTHONPATH`,
`CBUS_CGATE_MOCK_BIN`, `CBUS_CMQTTD_BIN`, `CBUS_DIFFERENTIAL_OUTPUT_DIR` and
`CBUS_TEST_ROOT` as needed. Supply them privately for reproduction; they are not
resolved by the sanitizer. The recorded acceptance context still determines
whether a source or installed package environment is required.

[`test_sanitize_evidence_receipts.py`](../tests/test_sanitize_evidence_receipts.py)
checks all six retained families, raw preservation, complete technical payload
equality, malformed/stale/unmapped rejection, and a genuine offline register
generation plus trusted artifact/source validation using temporary derivatives.
These temporary derivatives are a transformation proof, not publication of
obsolete receipts or a claim of fresh replay execution.
After sanitized receipts are committed, these tests reconstruct only synthetic
invocation metadata to exercise the publication seam; that reconstruction is
not a raw execution record and does not change the retained technical evidence.
