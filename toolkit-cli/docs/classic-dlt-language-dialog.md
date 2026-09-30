# Classic DLT language TEXT dialog transaction

`dlt text-dialog` implements the recovered native TEXT action and selected
language finalization as an offline project XML transaction. It is separate
from `dlt text`, which remains an exact record editor.

| Behavior | `dlt text` | `dlt text-dialog` |
|---|---|---|
| Selected variant 1 absent | Creates variant 1 | Uses legacy variant 0 first, retaining its identity |
| Empty input | Explicit blank TEXT record | Literal `<Default>` |
| Text length | Local 1024-character bound | Original prefix of 20 UTF-16 units |
| Other selected-language variants | Preserved exactly | Initialized and finalized together; long text normalizes and empty records are deleted |
| Non-Latin-1 input | Stored exactly | Original whole-input confirmation required before truncation |

Both workflows write a new local XML file. Neither saves a running C-Gate
database or sends labels to physical units.

```sh
cbus-toolkit dlt text-dialog show --project-xml project.xml \
  --target //P1/254/56/20 --language 1
cbus-toolkit dlt text-dialog plan --project-xml project.xml \
  --target //P1/254/56/20 --language 1 --variant 3 --text Kitchen > dialog-plan.json
cbus-toolkit dlt text-dialog apply --project-xml project.xml \
  --plan dialog-plan.json --output labelled.xml
```

The selected language must already have exactly one network `Language` entry
using `ID`, and be one of the pinned factory's TEXT languages: 1–14 or 64–116.
ID 0 is the default marker and 202 is an ICON language. This workflow does not
infer or change the default language, create language definitions, or rebuild
Toolkit's process language cache and preferences.

For confirmed input containing characters above U+00FF, add
`--confirm-non-latin1`. The original predicate checks the entire input, including
text beyond the retained prefix. A UTF-16 prefix that splits a surrogate pair
is refused because XML cannot store that original in-memory result. Ordinary
supplementary characters whose complete pair fits within 20 units are supported.
These storage rules do not establish physical text delivery or rendering.

## Initialization and finalization

The bounded workflow uses a fresh TEXT-only collection for the selected
language. Exact flavour 1 takes precedence over legacy flavour 0. Existing
TEXT values are initialized with their 20-unit prefix. Missing alternate
flavours 2–4 are absent from the fresh model. The explicit action then sets the
selected flavour to the accepted prefix, or `<Default>` for empty input.

Finalization processes flavours 1–4 in order. It updates existing records only
when their value changes, creates missing nonempty records, and deletes existing
records whose model value is absent or exactly empty. Whitespace is nonempty.
The nil optional language-model override selects the cached language; it is
distinct from the false initialization flag. Unselected languages, shadowed
legacy records and out-of-range flavours are preserved. Consumed non-TEXT
records are refused because FONT/ICON/DYNAMIC and warmed-cache transitions need
additional semantics.

When both exact flavour 1 and legacy flavour 0 are absent, original Toolkit
uses the owner's display representation. That can include an address prefix
under process preferences, so XML `TagName` alone is insufficient. Supply
`--owner-default-representation '20 - Kitchen'` with the exact intended value
when it affects finalization. The plan records that context as caller supplied.
An action editing flavour 1 itself can omit this context because it overwrites
the temporary default; the plan marks the unobserved value rather than guessing.

The plan exposes the initialized flavours, truncations, explicit action and
every create/update/delete effect. It binds the exact source XML hash and
recomputes the entire canonical candidate on apply. OIDs of existing records,
unknown XML metadata, comments, unrelated language rows and unit PP are retained
by the offline editor. Applying to changed input or tampered effects fails
before an output file is created. Existing output files are refused.

## Evidence

[`classic-dlt-language-dialog-original.json`](../research/fixtures/classic-dlt-language-dialog-original.json)
contains 15 executions of the original TEXT handler/Unicode predicate and
source receipts for 50 native collection/network methods. Original handler
acceptance is compared with the portable model, including declined confirmation,
Unicode after the retained prefix and the explicitly refused split-pair case.
The collection and network lifecycle are recovered from source; they were not
executed as complete original routines. See the
[original evidence boundary](classic-dlt-language-dialog-original.md).

[`classic-dlt-language-dialog-native.json`](../research/fixtures/classic-dlt-language-dialog-native.json)
independently verifies original C-Gate database XML behavior for a Group and a
Trigger action Level. It covers legacy-0 OID retention, deletion of an existing
empty alternate, normalization of other selected variants, creation of the
literal default marker, preservation of another language, confirmed Unicode
and project save/close/load. The action's distinct Address and Value remain
intact. This establishes native storage behavior, not original dialog execution.

Run the focused `test_dlt_language_dialog.py`,
`test_dlt_language_dialog_review.py`, `test_cli_dlt_language_dialog.py`,
`test_classic_dlt_language_dialog_original.py` and
`test_dlt_language_dialog_native.py` tests with `PYTHONPATH=src:tests:.`.
The integration check also runs `test_dlt_project_labels.py` and
`test_dlt_project_cli.py` to verify the exact editor remains unchanged.
Original replay uses the pinned `CBUS_TOOLKIT_EXE` and adjacent `.map` (or
`CBUS_TOOLKIT_MAP`). Native tests use the owned local C-Gate settings described
in [classic label controls](classic-dlt-label-controls.md);
`CBUS_DLT_DIALOG_REPORT` writes a fresh native receipt.

Full native/managed dialog parity, process-preference reconstruction, image/font
editing, default-language changes, physical transmission and display persistence
remain outside this bounded workflow.
