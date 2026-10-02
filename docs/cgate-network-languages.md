# Network language definitions

The embedded cmqttd C-Gate service and `cgate-mock` retain Network language
definitions separately from Group and Level `TagsDLT` labels. The Toolkit
NetworkLanguageType agent's recovered commands are now implemented in the
owned database model:

```text
DBGET !NETWORK_OID/Languages
DBADD !NETWORK_OID Languages
DBADD !NETWORK_OID/Languages Language
DBSET !LANGUAGE_OID/ID 1
DBSET !LANGUAGE_OID/TagValue English
DBGET !LANGUAGE_OID/ID
DBGET !LANGUAGE_OID/TagValue
DBDELETE !LANGUAGE_OID
```

These placeholders must be replaced with identities from the selected
project. `DBADD` returns one `301 OID=UUID`; the new object must be read back
before its identity is used. Scalar reads return `342`. Writes and deletes
return `200`. These response cases are tested owned contracts composed with
the retained source calls; original C-Gate execution has not verified them.

`Languages` is a singleton Network collection. Each `Language` owns a stable
OID, an integer `ID` and a text `TagValue`. ID zero is the default marker;
its TagValue stores the selected factory ID as decimal text. Other rows
store language descriptions. The database preserves collection position,
row order, custom descriptions and repeated nonzero IDs. The typed Toolkit
workflow applies its own source-pinned selection and default rules.
IDs use the signed 32-bit database grammar, independently of the Toolkit's
factory-language catalogue. Scalar text that XML 1.0 cannot represent is
rejected before mutation, preserving the whole project and prior value.

New collections append to the owned Network tree, and new rows append to the
collection. A new row initially contains only its OID. Setting ID followed by
TagValue produces `OID, ID, TagValue` field order. This ordering is an explicit
owned contract; original native serializer ordering remains unaccepted.
Complete Network XML admits this unnamespaced subtree:

```xml
<Languages>
  <OID>11000000-0000-4000-8000-000000000001</OID>
  <Language>
    <OID>11000000-0000-4000-8000-000000000002</OID>
    <ID>0</ID><TagValue>1</TagValue>
  </Language>
  <Language>
    <OID>11000000-0000-4000-8000-000000000003</OID>
    <ID>1</ID><TagValue>English</TagValue>
  </Language>
</Languages>
```

Complete imports require all three row fields and valid, nonconflicting OIDs.
Malformed fields, duplicate collections or conflicting identities refuse
atomically. Language edits preserve unrelated Unit/Application records,
including incomplete existing Units, and do not re-admit their programming
under the complete external XML schema. Project save/reload and cmqttd's
durable JSON state preserve the language identities and values.
Legacy numeric startup projects validate their complete Languages separately,
preserving previously admitted incomplete Units and allowing an absent
Interface or NetworkNumber. Language reads resolve existing identities without
persisting an overlay; the first successful mutation installs its owned tree.
This does not broaden complete external Network XML admission.

Inspect `CMQTT CAPABILITIES` for `database_network_languages`,
`database_network_language_operations` and
`database_network_language_physical_io`. These are local database operations
and send no PCI or MQTT command. They do not establish physical label
programming, language switching on an eDLT, an original Toolkit callback,
Schneider SQLite language interchange or standalone language-subtree copying.
Do not retry a mutation after an uncertain response.

The wire vectors are
[`cgate_network_languages.json`](../rust/testdata/vectors/cgate_network_languages.json).
The retained Toolkit persistence source is in
[`classic-dlt-language-dialog-original.json`](../toolkit-cli/research/fixtures/classic-dlt-language-dialog-original.json).
Focused Rust tests cover creation and issued-OID readback, ordered scalar
updates, whole-project save/reload, malformed XML preservation, foreign-project
refusal, deletion and durable service-state restart.
