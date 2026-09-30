# Classic DLT project documentation

The offline documentor admits `KEYBL5`, `KEYML5` and `KEYDL4` firmware
`3.0.00` with complete explicit PP snapshots. It renders the inherited NeoPro
timing, eight-key, controls and canonical scene tables, then appends exactly
`Labels: Static` or `Labels: Dynamic`, without an added HTML break. This is the
original `TDLTDocumentor.DocumentHTML` structure. The label mode describes the
dynamic-update control; the original wrapper does not print label texts or
images.

`EnableDynamicLabels=0` loads `BlockDynamicUpdates=true` and prints Static;
`EnableDynamicLabels=1` prints Dynamic. An absent, malformed or ambiguous bit
remains unknown. A known label mode never changes an incomplete inherited body
to recovered. Firmware outside the admitted slice remains explicitly partial.
The source factory's wider `0..9` registration is not a tested PP profile.

All three native classes have eight physical keys, eight virtual-key slots and
eight blocks, no `IBistable` interface, and disabled infrared-bank capability.
Their PP includes share `I_NEOCORE.xml`: two applications, nine group slots,
eight selectors and scene pointers, and an 80-byte scene table. The DLT model
sets the scene manager's command capacity to 40. Only the first eight group
slots are the inherited key blocks. The shared Neo projection requires all
four join fields to be explicitly 255, canonical scene layout, and the
source-bounded simple Scene key state; Scene Modify and normalization-dependent
states remain partial. Missing group/action metadata is not invented.

Evidence is reproducible from private pinned Toolkit 1.18.0.2754 EXE/MAP and
decoded specifications:

- `research/project_documentor_dlt_static.py` produces the 22-check
  `research/experiments/2026-09-30/project-documentor-dlt-static.json` receipt,
  including class/VMT/interface facts, PP include shapes, the original boolean
  inversion and documentor append order.
- `research/project_documentor_dlt_original.py` executes only the original
  DLT wrapper instructions in four synthetic cases, captured in
  `research/experiments/2026-09-30/project-documentor-dlt-original-leaf.json`.
  The inherited body, class test, boolean getter and string list are hooks.
  Both true/false class cases preserve the inherited call; both DLT flag values
  append the exact original literal after it.
- The control polarity independently agrees with the original loader and
  native PP receipts in classic-DLT work commit `712b7c8b` (`dlt_controls.py`,
  `classic-dlt-controls-original.json` and `classic-dlt-controls-native.json`).
  This documentor imports none of that editor runtime and performs no writes.
- `tests/test_project_documentation_dlt.py` covers all three complete profiles,
  both modes, two application links, a nonempty scene, distinct ActionSelector
  Address/Value, dispatch, missing PP, unsupported states and source receipt
  regeneration. With private inputs and the bounded JIT probe enabled, 26
  focused tests pass.

The original complete generated page has not been captured. Byte comparison,
visual comparison, the full GUI, retained in-process model history, and physical
display or transfer acceptance remain unassessed. The bounded original wrapper
probe needs local JIT memory permission on macOS; a sandboxed Unicorn run can
stall in SIGILL diagnostics. No Windows process, native C-Gate endpoint or real
project is used by either probe.
