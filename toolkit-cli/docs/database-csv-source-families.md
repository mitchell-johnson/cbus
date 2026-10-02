# Source-backed input families in database CSV

The native snapshot exporter and cached projection admit the classic Key, Neo,
NeoPro and wireless input families selected by the literal Toolkit 1.18 factory
registrations. The current registry admits 126 distinct types, up from the prior
35; 136 of the 262 statically registered types still have no admitted report
profile. These counts describe bounded modeled profiles, not complete Toolkit
workflow acceptance.

The family batch covers 233 registrations and 94 types: ten classic Key
registrations, sixteen older Neo registrations, thirty-four NeoPro registrations,
112 older wireless input registrations, 37 wireless eight-remote registrations
and 24 wireless decorator registrations. Types shared between these firmware
classes are counted once. Numeric firmware comparison uses the exact inclusive
registration bounds, including the old wireless partitions at 1.4.49/1.4.50,
1.4.91/1.4.92 and 1.9.99/1.10.0. Gaps and multiple matching registrations are
refused. The complete type/class/range roster is in
[`toolkit-database-csv-families-registry.json`](../research/fixtures/toolkit-database-csv-families-registry.json).
The historical September registry and the earlier 35-type NeoPro receipt remain
unchanged.

The new admission follows fresh static inspection of the pinned EXE/MAP bytes.
No vendor instructions were executed. The exact synthetic rows, registration
endpoint cases, method addresses and method byte digests are committed in
[`toolkit_database_csv_families.json`](../../rust/testdata/vectors/toolkit_database_csv_families.json).
Private disassembly is retained as supporting research; vendor executables,
assembly and unit specification files are not publication artifacts.

| Selected agent | CSV association behavior |
| --- | --- |
| Classic Key | Four stored GroupAddress blocks, primary Application only; interaction slots 0–3; primary Area. |
| Older Neo | Eight stored GroupAddress blocks, primary Application only; interaction slots 0–7; primary Area. |
| NeoPro | Eight stored blocks; each SecondApplicationBlocks bit selects its Application; interaction slots 0–7; primary Area. |
| Wireless input, eight-remotes and decorator | Init creates sixteen input block references; LoadGroups replaces the report collection with all sixteen BlockGroup associations followed by every installed OutputGroup channel. All associations are interactive. Area is absent. |

Wireless physical key count and GetBlockCount are not the size of its report
collection. The report has sixteen group columns, so output channels appended
after those sixteen blocks are outside the visible columns. They are still
resolved against their declared Application and validated before any output is
written. A missing or ambiguous channel association therefore refuses the whole
report, even when the error occurs after its last visible group column.

Native inputs require complete stored parameters rather than guessing original
loader defaults. Key and Neo require Application, GroupAddress and
AreaGroupAddress; NeoPro also requires SecondApplicationBlocks. Area replay
remains bounded to the existing 12, 13, 255 and invalid provider outcomes. Native
snapshots require that Area already exists; they do not create or save it.
Wireless requires Application, InstalledKeys, InstalledChannels,
ChannelRelayMask, BlockGroup, BlockGroupSecondary, OutputGroup and
OutputGroupSecondary. The Boolean arrays are literal numeric zero/one arrays.
The explicit representation bounds installed keys and channels to 0–16 and the
relay mask to sixteen bits; it preserves metadata independently of report text.
The BlockGroup array has sixteen elements; OutputGroup and its secondary array
must match InstalledChannels, including explicit empty arrays for zero channels.

Cached v1 remains available for its earlier profiles. Cached v2 admits Key, Neo
and NeoPro with authoritative primary/secondary Application identities and
complete Group membership. Wireless requires
`cbus-toolkit-database-cached-projection-v3`, which adds the required root object
`wireless_loader` to the v2 shape:

```json
{
  "installed_keys": 6,
  "installed_channels": 2,
  "channel_relay_mask": 1,
  "block_secondary": [false, true, false, true, false, true, false, true, false, true, false, true, false, true, false, true],
  "output_secondary": [true, false]
}
```

Its Application context secondary mask combines block bits 0–15 and output
channel bits starting at 16. The declared ordered Unit group identities must
match both arrays and the complete Application membership. Names alone cannot
establish an owner. Repeated associations remain repeated; same-address Groups
in different Applications retain separate identities. Missing identities,
duplicate membership, invalid routing, extra mask bits, and metadata/count
disagreement are refused before modeled operations. The primary-only Key/Neo
loaders cannot consume nonzero secondary routing.

The public commands are unchanged: `toolkit-database-csv` accepts an explicit
native snapshot or `--cached-projection`, and `cgate database-csv` captures one
DBGETXML snapshot before projection. Project and network selection retain the
existing manager order; explicit Unit selection retains caller order. All
selected Units must validate before CSV/JSON files are published. A refused or
lost snapshot reply is not retried and creates no output. CSV keeps the original
comma-only quoting, trailing commas, CRLF records and final blank record, with
explicit UTF-8 output. It does not claim native Windows ACP equivalence.

Focused tests cover literal range endpoints, all 256 NeoPro masks for all 34
NeoPro types, both Area owners, provider stop/save outcomes, every wireless
routing bit including the nonserialized channel tail, complete project exports,
and offline/public owned-server atomic refusals. Mock and daemon journeys use
synthetic closed projects, owned loopback endpoints and inert PCI/MQTT peers.
They provide replacement execution evidence. Fresh native GUI enumeration,
cold-load ordering, original manager collection behavior, missing Group creation
and physical acceptance remain separate #56 obligations.
