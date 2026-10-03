# eDLT label controls and project images

The Toolkit CLI can export project image bytes through C-Gate, derive label
choices from those bytes and an exact project snapshot, and execute explicit
Lighting label/status callback histories through one parent transaction.
This is a supported software profile of KEYGL5 / 5055EDL firmware 5.5.00.
Full Toolkit workflow, original GUI and physical rendering acceptance remain
unfinished; these functions do not change the global parity percentage.

## Export and use image bytes

```sh
cbus-toolkit cgate --host SERVER edlt-project-images PROJECT --output images.json
```

The command reads `FILE DIR %PROJ%/PROJECT`, then downloads the selected
`PROJECT-DLTD-Pic*.bmp` files in returned directory order. Its JSON receipt
reports the SHA-256 of the new export file, read commands and response hashes.
It never overwrites an existing output, saves a project, programs a device or
retries a failed read. The export includes the ordered directory roster,
per-file SHA-256 and Base64 bytes. Keep site exports private.

Supply the file and its reported SHA-256 to either automatic metadata surface:

```sh
cbus-toolkit edlt parent-transaction-plan values.json \
  --project-xml project.xml --unit //PROJECT/254/p/20 \
  --operations operations.json \
  --project-images-export images.json --project-images-sha256 SHA256
```

The same pair is available with `cgate unit … edlt-parent-transaction
--auto-metadata --exclusive-project` and the native SceneManager surfaces.
It requires automatic metadata; caller caches cannot inject an image-present
Boolean or import a detached control receipt. The export's project must match
the selected project. Explicitly exporting an empty directory establishes
missing image matches within this input profile. A failed directory read does
not establish image absence.

The source lookup uses the final four characters before the filename's first
dot as each project image key. For FONT it looks up the TagValue prefix before
the first comma; other non-ICON types use the whole TagValue. Matching is exact,
case-sensitive and first-match in directory order. TEXT and empty types can
also match a project image. ICON uses the exact integer-key spelling in the
Toolkit DLTP index instead. The whole TagValue remains the display name.

The byte decoder admits Windows BMP with a 40-byte BITMAPINFOHEADER,
uncompressed BI_RGB and indexed 1/4/8 or RGB 16/24/32-bit samples. Exports are
bounded to 24 MiB, selected image bytes to 16 MiB, one image to 4 MiB and one
million pixels. Other codecs/compression, host-culture filename filtering,
GDI+ equivalence, opacity and screen rendering remain unverified/refused.
SHA binding proves which input was consumed, not native directory authenticity.

Existing `--toolkit-dltp-dir DIR --toolkit-dltp-sha256 SHA256` behavior is
preserved. Add `--toolkit-dltp-decode` to select the explicit decoded BMP
successor. It decodes every bound index file and records file and RGB sample
hashes; it does not establish GDI+ or original device rendering equivalence.

cmqttd and cgate-mock admit `%PROJ%/PROJECT/…` within their documented flat
virtual repository profile when no actual project named `PROJ` owns that
existing namespace. It shares `%PROJECT%/PROJECT/…` storage. This remains a
virtual FILE namespace, not host filesystem access or universal Schneider
repository-template equivalence.

## Explicit Lighting histories

Add `label_controls` to one existing `lighting` parent operation. For example:

```json
{
  "op": "lighting", "page": 1, "position": 2,
  "group": 12, "mode": "dimmer", "restore_level": 99,
  "label_controls": [
    {"target": "label", "type": 10, "events": [
      {"event": "selected-row", "index": 2,
       "identity": "label:56/12/2", "value": 2}
    ]},
    {"target": "status", "type": 5, "events": [
      {"event": "input", "text": "Owned status"},
      {"event": "enter"}
    ]}
  ]
}
```

The existing parent document still requires 2..22 operations and distinct
widget ownership. Histories for one widget stay inside its owning Lighting
operation. Each target is `label` or `status`; `type` is optional. Label types
are 0, 3 (static) and 10 (generic dynamic). Status types are 0, 1, 2, 3, 5
(static) and 10. The exact source setter resolves generic dynamic text/icon
subtypes from the selected image, including recursive index-reset behavior.
It preserves unrelated bits and bytes; the parent owns final normalization,
CRC calculation and one PP save.

Explicit events cover `input`, `enter`, `leave`, `key-preview`, `selected-row`,
`list-refresh`, `drop-down` and `close`. `enter` is an explicit Enter-key
shorthand, not a focus-enter handler. Enter-key and Leave callbacks perform
the source WriteValue then ReadValue order. Arrow-key suppression
consumes exactly one selection callback. A dynamic selected row needs its
exact ordinal, identity and value from the snapshot-derived four-variant list.
The generic control model also represents detach/rebind and mode transitions;
in the native Lighting workflow, type controls own those transitions.

Input is NUL-free and at most 64 UTF-16 units. Static allocation shares all 64
retained names and the complete unit reference set, retaining the old reference
until assignment. Cached full names and the saved 63-byte UTF-8 PP image are
separate. Pending text cannot reach parent save: issue an explicit binding
commit/read event. Close or a mode transition does not silently commit it.
Native static suggestion ordinals remain refused because the current snapshot
does not establish the original culture-sorted suggestion order.

Bindings are issued in process for one parent owner, exact post-Lighting PP
snapshot, operation position/history and source-derived rows. Neither their
JSON receipts nor caller-supplied initial state can resume or reassign them.
Earlier Language changes supply the current causal Lighting group rows;
later changes cannot enter an earlier history. SceneManager initial scene
labels retain their distinct old-object rules, described in
[buttons and Language ownership](edlt-scene-buttons-language.md).

Original framework scheduling, automatic list notifications, modal behavior,
locale-sorted static selection, broader widget adapters and hardware rendering
are still outstanding. Owned tests execute the CLI, retained models and local
Rust services; static inspection of vendor artifacts is separate evidence.
