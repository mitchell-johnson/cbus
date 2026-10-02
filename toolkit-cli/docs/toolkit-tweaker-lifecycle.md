# Toolkit tweaker replacement lifecycle

`cgate conversion tweak-replace` previews or applies the client-side replacement
sequence for all 243 currently admitted Toolkit tweaker pairs. It uses the same
specification, firmware, transformation and unsupported-registration checks as
`conversion tweak`. Existing `conversion replace`, `recover` and native
`CONVERTUNIT` workflows keep their separate contracts.

The recovered Toolkit routine stages a new Unit at the first free address from
1 through 255. It copies the source database TagName, Description, SerialNumber
and UnitName; a blank TagName becomes `NEWUNIT`. A blank UnitName uses the
recovered uppercase/legal-name/first-eight-character fallback. This portable
fallback admits ASCII tags only. Source catalogue metadata is not copied.
The original clears the target catalogue and may resolve a default through its
software catalogue lookup. Here `--catalog-number` explicitly selects the
catalogue used for target PP defaults and the target scalar CatalogNumber;
that input does not establish parity with the original catalogue lookup.

The reviewed plan includes the exact endpoint and TLS choice, project snapshot,
source identity and PP, specification hashes, staging address, copied metadata,
raw transformation assignments, submitted native schema values, expected PP and
backup name. Preview reads the loaded database and temporary PP sessions without
persisting a project or creating a journal. Apply requires the exact preview
digest, exclusive ownership of every project Network, and a new private journal.
Every Network must be closed and idle. Numeric address aliases and ambiguous
existing Unit addresses refuse before the backup or ADD. Scalar metadata that
cannot be represented exactly by the native command grammar also refuses before
creation, including controls, significant repeated whitespace and unsupported
blank-name fallback inputs.

Use an owned or explicitly authorized C-Gate endpoint and immutable decoded
specifications. For example, after reviewing a DIMDN8 to DIMDU4 preview:

```sh
umask 077
cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak-replace \
  //PROJECT/254/p/20 --source-type DIMDN8 --target-type DIMDU4 \
  --source-spec DIMDN8.xml --target-spec DIMDU4.xml --spec-dir ./specs \
  --firmware 2.7.00 --catalog-number TARGET --backup-project PRETWEAK \
  > preview.json

cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak-replace \
  //PROJECT/254/p/20 --source-type DIMDN8 --target-type DIMDU4 \
  --source-spec DIMDN8.xml --target-spec DIMDU4.xml --spec-dir ./specs \
  --firmware 2.7.00 --catalog-number TARGET --backup-project PRETWEAK \
  --apply --exclusive-project --expect-plan-sha256 REVIEWED_DIGEST \
  --journal ./replacement.attempt.json
```

The journal's directory must already exist without symbolic links. The attempt
file is created exclusively with mode `0600`; an existing attempt path refuses
reapply. A dedicated `.toolkit-tweaker.json` sidecar retains the same checked
record. Replay checks inspect only these sidecars in the same directory and
reject an unresolved attempt for the same project. Keep both files together;
this local guard does not coordinate other clients or directories.

Apply creates and freshly checks one `PROJECT COPY` backup before Unit ADD.
The backup keeps the source's full XML and PP. The new Unit receives a fresh UUID
absent from every OID exposed in baseline XML, including Project OID when emitted;
this does not prove the contents of an opaque server identity index. The issued
identity must resolve at the exact staging address before any initializer.
Initialization uses narrow scalar commands, so an unrelated raw Level or opaque
Network subtree is not resubmitted as a whole Network document.

After the tweaker PP save, the workflow checks the new Unit, fresh target PP,
source PP and complete unrelated project tree. A declared assignment refusal
keeps the source and scaffold, returns nonzero, and records the original reviewed
plan separately from fallback readback. It does not proceed to source deletion.
When the planned assignments are complete, the source is deleted once, the new
Unit is readdressed to the original source address with `DBSET`, and fresh XML
and PP are checked again. One `PROJECT SAVE`, `PROJECT CLOSE` and `PROJECT LOAD`
then verify the reopened project, destination identity, metadata, PP and backup.
The unrelated structural XML comparison retains attributes, namespaces,
comments, processing instructions and non-whitespace text. Whitespace-only text
is outside this comparison bound, including opaque and `xml:space="preserve"`
content. The replacement copies the listed scalar metadata and transformed PP;
it does not copy arbitrary source Unit extensions into the new Unit. The backup
retains the full removed source document.

A possible-send record is fsynced before each mutation and PP staging write
after the exclusive apply journal is created. Preview and the initial fresh
plan use temporary PP sessions before that journal exists; they persist no
database or project edit.
Transport loss or an uncertain error stops immediately without replay. After a
lost deletion, readdress, save, close or load reply, the journal distinguishes
what was attempted from what was confirmed. No automatic target deletion,
rollback or backup restoration occurs. The original Toolkit exception path
attempts target deletion and project save; reproducing that exception behavior
remains an open full-parity requirement.

Inspect an attempt through its exact bound endpoint and TLS choice:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak-recover \
  --journal ./replacement.attempt.json
```

Recovery validates the journal locally before connection. It reads current and
backup XML, and reads fresh target PP through a temporary session when the final
project matches. It never performs a database write, project save/close/load,
restoration or replay. Its JSON classifies `observed_before`, `observed_replaced`,
`conflict` or `read_unavailable`; the command's success exit indicates that the
observation was produced. `persistence_verified` requires a completed journal
with every lifecycle send confirmed, fresh matching target PP and a fresh
matching backup. A converted loaded tree after a lost `PROJECT SAVE` reply alone
does not prove durable persistence. Journal files are unchanged by recovery.

The sanitized static receipt is
[`toolkit-tweaker-lifecycle-source.json`](../research/fixtures/toolkit-tweaker-lifecycle-source.json).
It records input hashes, method addresses and recovered rules without vendor
bytes or original instruction execution. Owned mock/daemon subprocess tests use
public synthetic specifications and preserve literal wire replies, uncertain
send journals and independent cleanup evidence. These software checks do not
claim original GUI/history behavior, physical programming, controller handoff,
full XML whitespace fidelity or broad replacement parity. Issues #73 and #74
remain separate deferred associated-Level work and are not retried here.
