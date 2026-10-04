# Conversion XML preservation

`cgate conversion tweak`, `tweak-replace` and `tweak-recover` check complete
project XML while protecting significant whitespace. The checks cover the source
and unrelated tree, replacement staging and final readback, backup and reopened
project. No additional command flag is required.

Use [conversion tweak](toolkit-conversion-tweakers.md) to create a replacement
at a different address. Use [tweak-replace](toolkit-tweaker-lifecycle.md) when the
reviewed workflow also needs a backup, source deletion, readdress and project
save/reopen. Their specification, firmware, supported pair and exclusive-project
requirements remain unchanged.

## What the XML checks preserve

An inherited `xml:space="preserve"` protects all character data in its scope.
A child may reset that scope with `xml:space="default"`; text following the child
still belongs to its parent. This follows the
[W3C XML whitespace contract](https://www.w3.org/TR/xml/#sec-white-space).
The conversion policy also keeps mixed-content separators, CDATA and
whitespace-only leaf values. It ignores only spaces, tabs and line breaks used
as indentation in an element-only container with no preserve scope or mixed
character data. Other `xml:space` values are rejected.

For example, the spaces between `A` and `B` below are protected. The child's
default permits formatting indentation inside `Reset`, while its following text
keeps the preserve-parent scope:

```xml
<Opaque xml:space="preserve"><A/>  <B/>
  <Reset xml:space="default"><A/>   <B/></Reset>  </Opaque>
```

Mixed text such as `<Label>before<A/>  <B/>after</Label>` retains its separator.
So do a whitespace-only leaf such as `<Description>   </Description>` and
CDATA character data such as `<![CDATA[   ]]>`. Attributes, namespace bindings,
comments and processing instructions remain part of the structural checks.
Detached Unit checks derive their whitespace scope and namespace bindings from
the actual project ancestors; a temporary parse context does not add attributes
to the stored Unit.

These are parsed-tree checks, not a byte-identical XML serialization guarantee.
They do not extend the selected service's schema. In particular, replacement
copies its documented scalar metadata and transformed PP; arbitrary source Unit
extensions are not added to the new Unit. The backup retains the removed source
document returned by the service.

## Preview, apply and inspect a stopped attempt

Review the normal preview and retain its `plan_sha256`. Apply with the existing
exclusive-project flags and, for replacement, a new private journal path. The
`xml_comparison` result reports whether formatting indentation is compared and
whether preserve scopes, mixed-content whitespace and leaf values are checked.
An XML mismatch stops the workflow at the current phase. It does not authorize
an automatic retry, scaffold deletion, rollback or restoration.

For a stopped replacement, keep the attempt and sidecar together and inspect
through the exact endpoint and TLS choice recorded in that journal:

```sh
cbus-toolkit cgate --host 127.0.0.1 --port 20023 conversion tweak-recover \
  --journal ./replacement.attempt.json
```

Recovery reads current XML, backup XML and fresh target PP when the final graph
matches. It does not edit the database, save/close/load a project, or replay a
possible send. Inspect `disposition`, `fresh_pp_verified`,
`backup_verified_fresh`, `journal_xml_preservation_verified` and
`persistence_verified`. A fresh matching graph after a lost save reply remains
an observation; an incomplete send journal cannot prove persistence.

New completed journals bind the staged/final Unit, actual ancestor scope and
complete remaining project/backup tree under `conversion-semantic-xml-v1`.
Admitted historical journals that recorded the earlier whitespace comparison
remain available for read-only classification. They are unchanged by recovery
and cannot be upgraded to semantic persistence proof.

## Compatibility boundary

The regression profile uses public synthetic specifications and owned
`cgate-mock`/`cmqttd` processes. Controlled projection faults change returned
client XML while separately retaining the upstream backend bytes; they are not
server data-loss events. The software contract does not establish Schneider
native importer retention of opaque comments, processing instructions or
extensions, original Toolkit GUI behavior, physical programming or hardware
persistence. Historical conversion reports and receipts retain their original
acceptance scope.
