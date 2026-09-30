# Old Bytecraft body/actions and canonical SceneModify slice

This slice follows the immutable encoded Scene24 / old Bytecraft output commit.
It closes the bounded old DIMPR12 software body, packed scene records and
independent group/action consumers, and canonical KEYC/CIR SceneModify consumers.
Firmware/class gates are unchanged. L1 and broad/history models remain excluded.
Central DALI/SENLL, CLI registration and capability ledgers are not changed.

## Exact source corrections

The initial Bytecraft assessment omitted SETG DL after its masked channel tests.
The loader normalizes before calling the Boolean setters, preserving channels
8–11. Mode is exactly record byte0 equal to1. The constructor and pinned schema
declare 33 records, each 32 zero-default bytes; native packed getter fallbacks
are zero. The adapter nevertheless requires every consumed record explicitly,
because whole native PP/default delivery has not executed.

The separate channel flags are sixteen canonical text bits with their eight-bit
halves exchanged. They are not packed byte pairs. Restore reads logical bit15,
which is raw token7. DMX words use high then low byte, curves/fades use low-even
and high-odd nibbles. Max voltage0 normalizes to255/LINE. Curves outside0–5 are
not admitted for used output channels; fades0–15 and word patches0–65535 follow
the pinned types without inventing clamps. Both summary control groups use
Enable application203, while channel and Area groups use the primary application.

The body retains the original malformed channel row/header prefix, missing
scene-table angle bracket, Bytecraft curve/fade strings, scene0 restore and
conditional columns. Basic scene Off suppression is separate from scene-use
classification; an off-only Basic scene still participates in actions/input.
Inclusion in unused output channels can create a header-only scene subtable.
Existing group/selector metadata supplies actual names and links; no original
auto-created labels are synthesized. Selector identity uses Address, not Value,
including255. Actions use zero-based scene labels and preserve every match;
input uses channel-major/scene-minor order and one-based labels. Other retains
Area then both Enable control references, including unused identities.

The previous SceneModify conclusion applied an ordinary template refresh branch
to a special path. The exact template25 branch assigns the derived ramp template
to a separate extension reference under its lock. Template25 and all raw stages
remain, Scene1/Instant remains, and no timer default runs. The Classic body hides
the raw microfunction subtable (that is template26 only), while Classic actions
read those raw stages. Input activity uses the non-Unused template and all eight
Scene1 references. Indicator and internal ramp-template fields are unconsumed.
Admission still requires the unshared linear primary unused-group block.

## Evidence and verification

Parallel GPT-6.1-sol workers produced the packed loader, body grammar and disjoint
SceneModify closure; a separate GPT-6.1-sol reviewer checked the implementation.
The reviewer found an eager Bytecraft input scene read for a query with no
matching channel. The decoder now returns known empty before touching records,
as the native identity gate does. A regression case preserves that boundary.

The Bytecraft loader receipt has 67 exact checks and reproduces all thirteen
prior assessment spans. Its body receipt has 122 exact checks across34 methods.
SceneModify has31 new checks,15 inherited checks,24 narrow method hashes and153
synthetic source-table/context transitions. Prior Classic/Neo method vectors
are compared from retained receipts without rerunning original instructions.
All source artifacts use pinned hashes and sanitized relative references.

The configured targeted run covered the new body/loader/usage and Modify paths,
prior Scene24/ordinary KEYC/CIR, core report dispatch/receipts, classic usage and
shared Neo regressions. It reported334 passed,2 intentional original-execution
skips and one research-return tuple/list comparison failure. The new body helper
now returns JSON-compatible description lists without changing the serialized
receipt; the failed source comparison then passed. Thus all335 targeted checks
passed after correction. No product-code failure remained. No full suite ran.

An additional automated source CLI smoke passed with seven synthetic units:
five fully canonical Modify KEYC/CIR profiles and old/L1 DIMPR12. Six bodies
recovered; forty Modify controls, exact DMX/fade cells and ordered scene0/1/2/32
action text were verified. L1 remained partial. UTF-8 BOM/CRLF and honest parity
metadata were checked. The incomplete fixture retains37 markers; its checked
software receipt records original execution=false and byte/visual=unassessed.
The synthetic XML uses escaped metadata names and no interface endpoint.

No original CPU probe, hardware operation, build, installation or heavy copy ran.

## Remaining boundaries and integration

Old DIMPR12 requires explicit complete records, consumed body fields and existing
metadata. Original full PP-loader/default delivery, auto-created graph capacity,
retained callbacks/history and generated-page capture remain unexecuted. L1
logic/default loading, Architectural families and other Neo/DLT SceneModify are
separate projections. Canonical KEYC/CIR closure does not broaden those profiles.
Whole-page byte/visual equivalence, collection ordering/locale preferences and
printing remain unassessed.

Apply this commit after the prior documentor chain. Preserve concurrent central
documentor registrations, DALI/SENLL modules and all existing supporting-module
hashes. Add the Bytecraft body/loader and NeoClassic Modify modules to the core
receipt/test union, then regenerate that receipt from the integrated source.
The generic changes are narrow Bytecraft body/group/action dispatch; no shared
CLI or generated capability edits are included.

For the recorded targeted check, use an existing environment with pinned
CBUS_TOOLKIT_EXE, CBUS_TOOLKIT_MAP and CBUS_BYTECRAFT_SPEC variables:

```sh
CBUS_RUN_DOCUMENTOR_ORIGINAL=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
  python -m pytest tests/test_project_documentation_bytecraft.py \
  tests/test_project_documentation_bytecraft_loader.py \
  tests/test_project_documentation_bytecraft_usage.py \
  tests/test_project_documentation_neoclassic_modify.py \
  tests/test_project_documentation_neoclassic_modify_consumers.py \
  tests/test_project_documentation_neoclassic_scene_keys.py \
  tests/test_project_documentation_neoclassic.py \
  tests/test_project_documentation_neoclassic_usage.py \
  tests/test_project_documentation.py tests/test_project_documentation_usage.py \
  tests/test_project_documentation_neo.py tests/test_project_documentation_neo_usage.py \
  -q -p no:cacheprovider
```

The CLI smoke was added after that run and passed separately. Static helper
reproduction does not establish native runtime acceptance.
