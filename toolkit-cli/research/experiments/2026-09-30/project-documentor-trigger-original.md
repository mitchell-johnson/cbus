# Original trigger-group root workflow comparison

`research/project_documentor_trigger_original.py` executes only the original
Toolkit 1.18 `TProjectDocumentor.InsertHTMLTriggerGroup` method instructions in
Unicorn. The pinned EXE/MAP hashes are checked before mapping. The retained
synthetic receipt is `research/fixtures/project-documentor-trigger-original.json`;
the method span is `0xf07d60`–`0xf083b4`, SHA-256
`809b055f49b8c13d976f1360bf639b1cd63a020ab33a41893a3080937f9e573a`.

All called routines are explicit stubs: object/collection getters, documentor
factory, `ActionSelectorUse`, HTML helpers, Delphi string handling, string-list
addition, and object cleanup. No original factory, leaf action implementation,
programming loader, project or GUI executes. The comparison therefore pins the
root wrapper and does not claim a complete original generated page.

The six cases cover no levels, no units, all empty action descriptions, one
reported use, interleaved uses across multiple levels and units, and a nonempty
HTML leaf. Deliberately unsorted synthetic manager orders establish that the
wrapper preserves the supplied level order and unit order. Each receipt keeps
the exact factory type/firmware call sequence and action callback level/unit
identity, including distinct level Address and Value. The callback's Value is
synthetic metadata, not a newly established native Value getter behavior.

The root calls the documentor factory and `ActionSelectorUse` for every unit
under every trigger level. It does not test the programming-load flag checked
by the separate status-report method. Nonempty descriptions produce the unit
link and nested list; empty descriptions produce no unit entry. The unused
message appears once for a level only when every unit returned an empty
string. The Python wrapper matches every captured output line and callback
sequence under the same explicit leaf inputs.

Validation: `tests/test_project_documentation_trigger_original.py` passes seven
offline tests and intentionally skips its original-instruction reproduction
unless both `CBUS_TOOLKIT_EXE` and `CBUS_RUN_DOCUMENTOR_ORIGINAL=1` are set.
With the original source paths and executable-memory permission, all eight
tests passed, including fresh reproduction of all six cases. Executable-memory
permission is needed by this host's Unicorn runtime; ordinary sandbox execution
fails before any original instructions execute.

Remaining acceptance gaps are original project/model loading and load-error
outcomes, unrecovered per-device action descriptions, original factory and
leaf composition in one complete run, and a generated-page capture. The
separately retained ordering evidence also leaves persisted sort preferences,
Windows user-locale name collation, and equal-name native manager history
unobserved. Numeric snapshot order remains an explicit offline profile.
