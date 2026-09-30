# Classic DLT predefined ICON dialog transaction

`dlt icon-dialog` models an explicit built-in icon selection followed by original
selected-language finalization. It writes a new local project XML file and is
separate from the exact `dlt text` editor, the bounded `dlt text-dialog` workflow
and the offline broadcast compiler.

```sh
cbus-toolkit dlt icon-dialog show --project-xml project.xml \
  --target //P1/254/56/20 --language 202
cbus-toolkit dlt icon-dialog plan --project-xml project.xml \
  --target //P1/254/56/20 --language 202 --variant 3 --icon 91 > icon-plan.json
cbus-toolkit dlt icon-dialog apply --project-xml project.xml \
  --plan icon-plan.json --output labelled.xml
```

The selected network must already contain exactly one canonical `Language`
definition with `ID` 202. This transaction covers the original visible
predefined selector in language 202. Original Toolkit can retain historical
ICON values in other languages and preselect a hidden ICON radio for them;
those paths are outside this transaction. Language initialization predicates
are not a general prohibition on other original TEXT or ICON dialog paths.

The admitted built-in IDs are **1–91**, bound to the original
`Images/DLTP/index.txt` SHA-256
`c6cca64deaed7bb5ad814b2aaf4c37b580396bf38c057aae8bd616fadfd26310`.
The action stores the selected catalogue item's numeric Value as decimal text,
not the combo-box index or icon name. `show` and `plan` include the catalogue
IDs and source hash. Icon images are not bundled, generated or rendered.

## Graph behavior

The transaction admits a fresh selected-language collection containing canonical
TEXT and ICON records. It loads saved flavours 1–4 in order, using legacy
flavour 0 only when exact flavour 1 is absent. Existing non-FONT values use the
original prefix of 20 UTF-16 units. Missing alternate flavours are absent from
the fresh collection.

A missing first flavour in language 202 initializes to ICON with an empty
value. It never consumes the owner's display name or formatting preferences.
Editing flavour 2 therefore creates flavour 2 without inventing a first label.
An existing TEXT value in language 202 retains its TEXT type until an explicit
ICON action edits that flavour.

The action sets the selected flavour's type to ICON and its value to the chosen
ID. Finalization then processes all four selected-language flavours. It creates
missing nonempty records, updates changed types or values and deletes existing
records with empty model values. A TEXT value already equal to the chosen
decimal ID still requires a type-only update. Whitespace is nonempty.
This is the ordinary, nondeferred action; the original forced-graphic mode is
excluded. Original acceptance also clears the selected flavour's broadcast
mark. The offline transaction does not modify that separate process cache.

Existing OIDs are retained, including an updated legacy-0 record. Exact
flavour 1 takes precedence over a shadowed legacy-0 record. Other languages,
out-of-range flavours and shadowed legacy records remain untouched, including
their FONT/DYNAMIC records. Existing unedited ICON values outside the pinned
palette are preserved; the palette bound applies to new explicit selections.
Active FONT/DYNAMIC or unknown tag types are refused because their cache,
image and font dependencies are not established by this transaction.

The plan exposes initialization normalizations and every resulting record
change. Apply binds the exact source XML hash and recomputes the entire
canonical transaction, including its catalogue facts. Changed input, forged
effects, Boolean numeric fields and ambiguous address/language/flavour aliases
are rejected before output creation. Existing output files are refused.
Unknown XML metadata, comments, namespaces and unrelated graph data are
preserved. A UTF-16 prefix that splits a surrogate pair is refused because XML
cannot retain that original in-memory result.

## Evidence and limits

The source receipt
[`classic-dlt-icon-dialog-original.json`](../research/fixtures/classic-dlt-icon-dialog-original.json)
pins the original action, selector/catalogue rules and language eligibility.
Its retained replay contains 96 ICON-action cases and eight language-eligibility
rows, and distinguishes the selected item's numeric Value from its list index.
Whole-language initialization/finalization comes from the separately pinned
[collection source evidence](classic-dlt-language-dialog-original.md), not
execution of a complete original collection or GUI.

The independent native receipt
[`classic-dlt-icon-dialog-native.json`](../research/fixtures/classic-dlt-icon-dialog-native.json)
covers Group and action-Level storage, same-value type conversion, legacy OID
retention, empty ICON deletion, normalization of another selected TEXT value,
unrelated FONT/DYNAMIC preservation, a missing first flavour, exact-versus-legacy
precedence and project save/close/load. Action Address 42 and Value 43 remain
distinct. The fixture creates its own original C-Gate process and closed
synthetic networks, with temporary data on an explicitly selected volume.

Run the focused `test_dlt_icon_dialog.py`, `test_dlt_icon_dialog_review.py`,
`test_cli_dlt_icon_dialog.py`, `test_classic_dlt_icon_dialog_original.py` and
`test_dlt_icon_dialog_native.py` tests with `PYTHONPATH=src:tests:.` and the pinned
original inputs. `CBUS_DLT_ICON_DIALOG_REPORT` selects the native receipt path.
The retained CPU observations completed before the execution-safety restriction;
they are compared by ordinary Python tests. Fresh CPU replay is separately
opt-in and requires an already approved, verified network-denied execution
route. It was not rerun for the final integration check; ordinary Java/C-Gate
acceptance remains separate.

This transaction does not create network language definitions, modify PP,
reconstruct a warmed Toolkit cache, save a running database, transmit labels or
establish device rendering or persistence. Full FONT save still needs original
font rasterization, graphic-ID allocation and ANSI-codepage metadata behavior.
