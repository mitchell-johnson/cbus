# Managed Toolkit label API surface (supplemental evidence)

The [pinned method inventory](managed-label-api-surface.json) was extracted from
the official Toolkit 1.18.0.2754 installer payload. The isolated Windows VM
reports that Toolkit release; its installed DLL hashes were not separately
captured. This supplements the [native C-Gate LABEL
fixture](../../fixtures/edlt-dynamic-cache-native-scope.json), which already
contains the release-pinned `HELP LABEL`/`LABEL ?` transcripts and negative
`LABEL GET`, `READ`, `CACHE` and `INVENTORY` syntax responses.

`CGateConnection` exposes methods to send lighting/trigger labels and dynamic
data, plus `LabelClearEdlt`. Its method table contains no label-cache readback
entry point. The Toolkit label editor has `SendLabels` and its send thread; the
model's named unit/factory operation is `ClearEdltLabel`. `LABEL KFIGET` in the
native service reads eight key-function indicators, not cached label contents.
These observations support the existing `dynamic_label_device_readback: false`
capability. They do not rule out a generic method or undocumented physical
firmware protocol.

To reproduce the supplemental metadata enumeration with ignored vendor DLLs,
use `dnfile==0.18.0` to read each assembly's `TypeDef` rows, enumerate every
`MethodList.Name` for the named types, and compare the complete-file SHA-256
digests to the fixture. The retained fixture verifier remains:

```sh
python3 toolkit-cli/research/verify_edlt_dynamic_cache_scope.py \
  --cgate-app /path/to/ignored/cgate/app \
  --toolkit-app /path/to/ignored/toolkit/app
```

The current Windows project was kept offline with its CNI host blocked. No
physical eDLT was queried and this supplement supplies no acceptance receipt
for a device-cache inventory.
