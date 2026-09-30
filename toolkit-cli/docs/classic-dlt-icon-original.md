# Classic DLT ICON source evidence

The [original receipt](../research/fixtures/classic-dlt-icon-dialog-original.json)
pins the ordinary classic ICON choice to built-in catalogue IDs 1–91 and the
visible selector to language 202. It combines source inspection with bounded
execution of original instruction bodies against synthetic controls and storage
hooks. It does not establish full native GUI execution, bitmap rendering,
database persistence, label delivery or device display.

The executable is Toolkit 1.18.0.2754, SHA-256
`9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`;
the MAP is SHA-256
`f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`.
The separate `Images/DLTP/index.txt` is 2,392 bytes, SHA-256
`c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310`.
No vendor bitmap bytes or filenames are retained. The catalogue receipt contains
91 derived ID/description pairs and 18 method hashes.

## Action and language rules

`TfrmEditDLTLabel.Execute` hides the ICON radio unless the current language ID is
202. Its existing-tag selection remains separate: existing type ICON selects
that radio even if it is hidden. TEXT is not disabled merely because the
language is 0 or 202. A later force-graphic flag can select DYNAMIC and disable
TEXT; the ordinary ICON transaction excludes that mode.

The initialization predicates are different from the visible-choice gate.
`GetHasTagTypePredefined` is true only for a nonnil language type with ID 202;
`GetHasTagTypeText` is true for a nonnil ID other than 0 or 202. They govern the
missing-first-flavour default in collection initialization. The ordinary fresh
202 collection gives a missing first flavour ICON with an empty constructor
value. Existing TEXT or ICON values retain their type and use the first 20 UTF-16
code units. The shared [collection evidence](../research/classic_dlt_language_collection_original.py)
also pins false-initialization alternate removal, finalization of all four
flavours, empty deletion and retention of the selected legacy flavour-0 identity.
That collection source receipt is reproduced in the ICON receipt; this probe
hooks the finalizer and does not execute the collection graph.

The original ICON OK branch first reads `ItemIndex`. A negative index skips tag
changes but still follows the ordinary finalization path. Otherwise, it sets
TagType 1, reads the selected item's integer `Value`, converts it to a Unicode
string and stores that value. The identifier is not the selected index or image
index. The handler itself does not validate language or catalogue membership;
restricting the portable action to visible language-202 choices and pinned IDs
1–91 is an explicit admission boundary.

Ordinary acceptance clears the selected flavour's broadcast flag, calls group
or level `FinaliseLanguage` for the selected language with a nil model override,
and sets ModalResult 1. Deferred mode skips the flag reset and finalizer, while
still accepting a selected value. No-selection and deferred cases are observed
source behavior; they need not be admitted by a higher-level explicit-ID API.

## Catalogue identity and order

`PopulatePredefinedGraphicsList` calls `GetPictogramList(1)`. Type 1 selects DLTP
and the executable-relative index. Each valid record supplies positive integer
ID, description and bitmap filename. The factory registers decimal ID names in
index order. The pinned file has unique IDs 1–91 and nonempty labels, so a fresh
factory produces that same order. Combo item Value receives the parsed ID;
ImageIndex receives the zero-based list position.

The source does not provide a general duplicate-free installation contract.
Registration appends duplicates, listing updates an existing name's description
in place (an empty description deletes it), and bitmap lookup takes the first
exact-name cache entry. A previously registered DLTP set bypasses index reload.
The portable catalogue is therefore tied to the pinned built-in installation,
not an arbitrary modified index or warm process cache.

## Retained execution and checks

The retained run completed before the subsequent execution-environment alert:
exit 0 in 2.92 seconds, using the approved escalated synthetic-memory route. The
tool response did not attest network-denial enforcement. The harness performed
no network calls. No fresh CPU replay was launched after that alert; replay in
the current environment remains pending verification of an approved network-denied
route. The historical observations are preserved without claiming current-route
approval.

There are 96 ICON button cases: all 91 catalogue IDs, a deliberately mismatched
index/value pair, an off-catalogue synthetic value, group and level no-selection
cases, and a deferred case. Eight language records execute both original default
predicates; the seven nonnil records also execute the visibility/type-selection
fragment for each of TEXT, ICON, DYNAMIC and FONT. Nine action/language method
receipts and 30 shared collection method receipts accompany the observations.
Execution was bounded to 3,000 instructions per button call and 300 per predicate
or fragment; actual instruction counts were not retained.

Four receipt-only checks passed with no skips:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest \
  tests.test_classic_dlt_icon_dialog_original.IconDialogOriginalEvidenceTests -v
```

The test module additionally contains an opt-in fresh-source replay. It requires
both the pinned input variables and `CBUS_CLASSIC_DLT_ICON_REPLAY=1`, which must
only be set after the execution route is verified. Global `CBUS_TOOLKIT_EXE`
alone never starts this CPU replay. Running the complete module without that
explicit opt-in reports four passes and one skip.
