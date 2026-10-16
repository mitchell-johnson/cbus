# Thermostat default names and Unicode inventories

Ordinary `thermostat settings preview|apply` loading can resolve missing output
groups even when the selected application contains Unicode names. This applies
to PC_TSA, PC_TSA5, PC_TSB and PC_TSB5, including programmable damper defaults.
Use the existing [output controls](thermostat-settings.md#output-group-controls)
and [typed Edit records](thermostat-output-edit.md) within one settings owner.

A missing output address searches the complete current application inventory
for its generated name. Comparison changes only ASCII letters and then compares
the exact remaining string. One matching object is reused with its existing
address, identity, name and metadata. No matching object creates the generated
group at the source address. More than one match refuses rather than choosing
an unproved source manager order.

For example, generated `[CG01] G (fan)` can reuse existing `[cg01] g (fan)`
while preserving unrelated names such as `Unrelated Ω`. A programmable damper
can similarly reuse `[cg01] damper zone 1`. An already resolved output object
retains its separate ordinary rename behavior; an existing damper retains its
name. Loading effects persist in the plan even when a later selection changes
the bound object.

All recovered generated labels and prefixes are ASCII: the source table has
174 rows, 48 nonempty labels and four damper labels. This does not expose a
caller-defined Unicode default-name input. Explicit Add and Edit names retain
their own source validation: `é` and `É`, `Ω` and `ω`, and `straße` and
`STRASSE` are distinct under the ASCII comparison. ASCII duplicates still
refuse. Exact Project.TagName equality and explicit UTF-16 entry limits remain
unchanged.

Existing Level.Value text remains optional and opaque, including absence and
non-byte text. A name lookup or Edit does not parse it. Whole-project freshness
still detects changes to that metadata or unrelated names; every existing OID,
Level subtree and unrelated PP field must survive the admitted transaction.
Newly created Levels retain their strict canonical-byte validation.

Preview writes nothing. Apply uses the existing exclusive-project, backup,
freshness and save workflow. A lost successful creation or quoted TagName reply
stops without automatic retry, inverse edit or a later target save. Inspect the
uncertainty receipt before a separate read-only recovery.

The [dependency receipt](../research/fixtures/thermostat-output-default-ascii-source.json)
and [extractor](../research/thermostat_output_default_ascii_static.py) pin the
source caller, ASCII LowerCase and fallback, ASCII UpperCase and exact UTF-16
equality. They inspect retained source data and do not execute original
instructions. Source and installed release outcomes are documented separately;
component tests do not establish initialized original GUI controls, native
server behavior, culture-sorted manager order or physical thermostats.
