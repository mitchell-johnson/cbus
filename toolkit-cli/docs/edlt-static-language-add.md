# eDLT static text and Language Add histories

The closed-project parent transaction accepts `static-text-dialog` and
`add-language-dialog` operations in ordered histories with the existing widget,
SceneManager, Activation, Application Add and Reset operations. It uses the
source-established Toolkit 1.18 language factory and managed eDLT static grid.
This is a software workflow; original dialog, GUI, scanner, controller and
physical acceptance remain open.

A static grid operation supplies committed cell edits, in order:

```json
{"op":"static-text-dialog","close":"window","edits":[
  {"index":3,"text":"Kitchen"},{"index":3,"text":"Māori"}
]}
```

There are 64 existing rows, and a name permits 64 UTF-16 units. The last committed
edit to an index wins. Both window close and the close button call SaveStaticText;
the source has no accepted-result check or cancel rollback. It does not allocate,
reindex or select a label. A later edit can change a row already referenced by a
widget or scene. The PP setter retains the first 63 UTF-8 bytes, stops after a NUL
if encountered, and appends a terminator. That can split a character. The existing
label allocator keeps its separate validation policy. Evaluation of malformed
loaded UTF-8 and the GUI behavior of an uncommitted cell remain outside this
operation's contract.

Language Add requires explicit preferences and a complete native Languages
collection, or an explicitly absent collection:

```json
{"op":"add-language-dialog","preferences":"registered-defaults",
 "selected_ids":[74,1,80]}
```

`registered-defaults` means `[1,-1,-1,-1,-1,-1,-1,-1]`; alternatively supply eight
signed integer preference values that resolve in the pinned factory. The model
starts with a fresh selected-list cache: native XML rows populate it before
preference slots. This is not an inference about a running Toolkit process's
retained cache. The factory has 69 entries including ID0 `<None>`. Accepted lists
contain 1–8 distinct nonzero choices, including Chinese ID202. English ID1 cannot
be removed when already selected. `cancel:true` leaves the existing collection
and selected default unchanged. The available GUI list is sorted, but its locale
collation is unaccepted; selected order is explicit and is preserved.

Finalise removes unselected rows, preserves every matching real row with its
existing OID and custom name, and preserves the last ID0 marker identity. Missing
rows are appended with factory descriptions. A default absent from the accepted
list changes to its first selected entry. ID0 is the default marker and is not a
real selected language. Group/Level TagsDLT labels remain separate metadata.

For preview, write an operations array containing at least two operations and run:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 unit \
  --lock-address //PROJECT/254 --source /db//PROJECT/254/p/20 --dry-run \
  edlt-parent-transaction --spec-dir SPECS --auto-metadata --exclusive-project \
  --operations operations.json --display-preferences display.json
```

Apply the reviewed history by removing `--dry-run` and adding
`--backup-project BEFORE_LANGUAGES`. The existing closed-idle network, exclusive
project, full source/PP readback, stale-plan, observed OID freshness and one-save
controls apply. Language rows use the original DBADD Languages/Language,
issued-OID DBSET ID/TagValue and DBDELETE grammar. They are verified before PP
staging, followed by complete PP/XML readback and SAVE/CLOSE/LOAD. No standalone
Languages DBSETXML endpoint is assumed.

The owned service appends a newly created Languages child to the Network; an
existing collection retains its position and surviving row order. Original
serializer position has not been accepted. The original native callback and row
agents perform additional save/load and per-row project saves; this parent
workflow deliberately composes one owning PP save and one target project save.
It does not claim that original save count or cross-command atomicity. A failed
language edit before PP save uses the saved source reload boundary; it does not
delete an unidentified or foreign object. Once PP save may have been sent, the
receipt remains uncertain and the workflow does not replay or roll back the edit.

Full-tree comparison checks substantive XML, attributes, comments and processing
instructions. It ignores whitespace-only text, including opaque and
`xml:space="preserve"` content. This is a comparison limit, not full XML fidelity.
Static evidence is in `research/fixtures/edlt-static-language-add-static.json`;
owned command and byte facts are in the two static-language vectors. Issues
72–75 and original/manual/hardware acceptance are not advanced by this workflow.
