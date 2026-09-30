# Classic DLT FONT preparation boundary

The [static source receipt](../research/fixtures/classic-dlt-font-source.json)
pins 41 Toolkit 1.18.0.2754 methods and the original Edit DLT Label form. It
establishes a metadata preparation contract and identifies the missing renderer
and persistence prerequisites. No FONT production writer was added. No original
instructions, CPU emulator, Windows GUI, renderer, server or hardware ran in
this investigation.

The source inputs are the same pinned EXE/MAP as the classic ICON and TEXT
receipts. [classic_dlt_font_source.py](../research/classic_dlt_font_source.py)
verifies both complete hashes before decoding bounded methods with Capstone.
The output contains derived facts and hashes, without vendor code or images.

## Descriptor and ordinary GUI inputs

The serialized Unicode descriptor is:

```text
image_id,1,font_name,size_text,charset_name,style,x,y,invert,text
```

The serializer concatenates without escaping or validation. The ordinary GUI
supplies style `""`, `B`, `I` or `BI`, invert 0/1, and the first 20 UTF-16 text
units. The text control also has MaxLength 20. Its size list is 6–18 plus 20.
The charset list contains 15 names, including DEFAULT; the receipt records the
14 explicit case-sensitive mappings and fallback value 1.

`IsDLTFontTagValue` checks exactly nine commas and nothing else. The loader does
not invoke that predicate or check the version. Its token operation repeatedly
takes at most 1,024 UTF-16 units of the remaining suffix, so an unrestricted
CSV split is not equivalent. Missing commas yield empty fields while retaining
the clipped suffix. Size defaults to 8; positions default to 0. Invert is false
only for exact `0`. Uppercase B/I substrings select style bits, while no match
retains the prior font style; an empty name retains the prior name. Consequently,
malformed descriptors also depend on the supplied font object's initial state.

## Allocation and coupled persistence

The save radio distinguishes Update Existing from Create New. Create New scans
project graphic references for the first unused ID at or above 2000. Update
Existing parses the old descriptor's first field with fallback -1 and reuses
any nonnegative result; negative values allocate. Save can therefore accept ID0,
although graphics index reload rejects IDs at or below zero. A reliable portable
save/reload contract should explicitly require positive IDs.

The original save upserts by ID and overwrites both bitmap and description. It
stores `Font=` followed by standard padded, unwrapped Base64 of the descriptor
converted to the runtime Windows ANSI codepage. Codepage argument 0 resolves
through the original runtime codepage global. `WideCharToMultiByte` receives
flags 0 and no default-character reporting pointer. A Python host locale or
generic codec choice does not establish the original conversion behavior.

The assigned graphic filename is `Pic<ID>.bmp`. The file agent constructs:

```text
%PROJ%/UPPERPROJECT/UPPERPROJECT-DLTD-Pic<ID>.bmp
%PROJ%/UPPERPROJECT/UPPERPROJECT-DLTD-index.txt
```

It saves the bitmap and then the index separately. Index rows contain
`id,description,filename` followed by CRLF, without CSV escaping. Reload upserts
rows without clearing prior cached items; bitmap loading happens separately.
Metadata-only output cannot be described as this completed FONT save.

## Renderer prerequisites

The original preview draws into an 82×40 monochrome intermediate bitmap, then
into a 62×16 final preview at the selected offsets, optionally inverted. Centering
uses measured text width. A pinned point-size table supplies the intermediate
Y correction. Font height uses `-MulDiv(size, TFont.PixelsPerInch, 72)`.
Measurement and drawing reach Windows `GetTextExtentPoint32` and `ExtTextOut`.
The font list comes from installed Windows fonts, with Arial selected by lookup.
The form's design PixelsPerInch 96 does not prove runtime metrics.

The 62×16 preview is not a transmitted-width contract. The separately observed
flavour default width is 64; this source package does not establish its complete
`LoadDLTBitmap` width, padding and packing path. The existing broadcast compiler's
caller-prepared width range 1–240 is a native encoding bound, not evidence that
the original renderer produces arbitrary widths or that preview width equals
wire width.

A future bounded writer needs:

- The resolved Windows font face, file and version; DPI/TFont pixels-per-inch;
  size, charset/style, metrics and GDI/VCL renderer context.
- An explicit Windows ANSI codepage and conversion contract, or a separately
  declared ASCII-only metadata boundary.
- A fresh authoritative project identity, graphic ID/index/bitmap references,
  exclusive update ownership, and explicit create/update intent.
- Prepared bitmap bytes bound to the descriptor and rendering evidence, plus
  separate bitmap/index persistence receipts and failure handling.

Pure metadata planning is feasible within those stated inputs. Cross-platform
font rendering, complete dialog execution and original coupled persistence
remain unverified.
