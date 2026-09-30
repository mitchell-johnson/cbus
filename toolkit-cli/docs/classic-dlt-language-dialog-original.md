# Original classic DLT TEXT dialog evidence

The receipt `research/fixtures/classic-dlt-language-dialog-original.json` combines
15 original TEXT-button replay cases with static source checks for the native
language collection and network lifecycle. Its three extractors consume the
pinned Toolkit 1.18.0.2754 EXE/MAP and retain hashes, identifiers, derived rules
and synthetic observations. Vendor bytes and private project content are absent.

The original native TEXT acceptance handler scans the entire input for UTF-16
units above 255 before truncation. Such input requires the confirmation result
`1`. Accepted empty text becomes `<Default>`; other accepted text becomes its
first 20 UTF-16 units and type TEXT. This can split a surrogate pair. An XML
transaction must explicitly refuse the resulting invalid XML text rather than
silently use code-point truncation. Accepted ordinary group/level edits clear the
selected flavour's broadcast flag and finalize its entire selected language.
The finalizer receives a nil optional language-model override, not a Boolean.

`InitialiseLanguages(false)` builds the separate model cache from supplied
language references and saved TagsDLT. Flavour 1 falls back to legacy flavour 0;
only when both are absent does it need the owner's display representation. That
representation can include a formatted address prefix under Toolkit preferences;
XML TagName alone is insufficient. The false argument removes missing alternate
model flavours. Initializing the cache alone does not change saved XML rows.

`FinaliseLanguage` processes flavours 1–4 in order. It updates a selected legacy
flavour-0 record without changing its ID or identity; an exact flavour-1 record
takes precedence. Missing nonempty rows are appended, while existing rows with
absent or exactly empty model values are deleted by StorageDelete, Extract, Free.
Whitespace is nonempty. Other language IDs, flavours outside 0–4 and shadowed
duplicates are not swept. Non-FONT values are limited to 20 UTF-16 units; type and
value comparison occurs before this truncation. A fresh TEXT-only graph avoids
the retained-value-dependent interpretation of DYNAMIC tags.

Network language initialization is a separate lifecycle. The native Delphi
routine retains its prior language cache and selected object, imports known XML
language IDs, then adds configured language preferences. It is not equivalent to
managed CBusLogicModel.dll normalization. A bounded collection transaction needs
explicit language-reference IDs and owner display metadata where consumed; it
must not infer those preferences from XML. Network language definition/default
editing and physical SET_LANGUAGE broadcasts are outside this TEXT receipt.

The original button and Unicode predicate execute. VCL access, confirmation,
Delphi string helpers, tag storage and finalizer calls are synthetic hooks.
Collection and network results are static source evidence. No complete native
or managed dialog, original collection execution, native C-Gate persistence or
physical label delivery is claimed. Separate native save/reload tests are needed
for persistence acceptance.

Run the focused replay with explicit private input paths:

```sh
CBUS_TOOLKIT_EXE=/path/to/CBusToolkit.exe \
CBUS_TOOLKIT_MAP=/path/to/CBusToolkit.map \
PYTHONPATH=src:. python -m unittest discover -s tests \
  -p test_classic_dlt_language_dialog_original.py -v
```

The local Unicorn JIT needs an execution environment that permits executable
memory. Without the configured original input, only the retained receipt checks
run and the replay test is skipped.
