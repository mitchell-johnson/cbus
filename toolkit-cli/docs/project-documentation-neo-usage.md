# Neo and DLT documentor usage descriptions

`project_documentation_neo_usage.py` consumes the shared fresh Neo PP projection
for KEYM8, KEYM4, KEYA3 and KEYB4 in the admitted old/pro class firmware ranges,
KEYE1 2.5.00, and the separately admitted KEYBL5/KEYML5/KEYDL4 3.0.00 DLT
profiles. Scene Modify, configured join modes, noncanonical scene allocations and
unresolved PP inputs retain explicit unrecovered status. Multisensor profiles
remain outside this adapter even though their action documentor inherits Neo.

The action description follows the original call chain: primary-application
Classic key recalls, Neo scene-trigger replacement, then NeoPro
secondary-application key recalls. It preserves key-major/block-major order,
duplicate recalls, the stored-level-1 **Address** comparison enclosing the
stored-level-2 **Value** comparison, retrigger code 7 and expiry codes 12/6.
A scene trigger replaces prior text; the last matching virtual key wins. The
secondary pass can append to that scene text, and identical primary/secondary
applications can run both recall passes. A Scene key's encoded ramp/action
nibbles are not microfunctions: the source loader assigns its actual idle
microfunction group. Unlike the direct fan/temperature getters, Neo's source
loader creates a control group at address 255 and can resolve action selector
255; neither address is silently suppressed here.

Input dependencies list matching blocks before scene commands. Only native
physical keys contribute block labels with disabled joins; KEYE1's native
MaximumKeyCount is four, irrespective of its connected-key mask. Unused macros
are excluded and unmatched blocks retain `Block (Unused)`. Neo scene use tests
all key scene references, including ordinary keys' default Scene 1 reference;
DLT's separate override always labels a retained command `Scene N`. Other
dependencies preserve Area, indicator brightness, key disable, corridor and
control-group order. Indicator brightness uses GroupAddress[8] whenever its PP
string is nonempty. The corridor group is reported even when corridor linking is
disabled. Possible join dependencies stay partial unless disabled PP is explicit.

Evidence:

- `research/fixtures/project-documentor-neo-usage-static.json` pins 79 checks to
  Toolkit 1.18 EXE/MAP method hashes, literals, branch instructions, class VMTs,
  PP bindings and native key/block counts.
- `research/fixtures/project-documentor-neo-action-original.json` compares 15
  synthetic cases by executing original Classic/Neo/NeoPro instructions.
- `research/fixtures/project-documentor-neo-input-original.json` compares seven
  synthetic cases by executing original Neo/DLT Input dependency instructions.
- `tests/test_project_documentation_neo_usage.py` compares portable output to
  those independent receipts and exercises complete and missing PP snapshots.

The original-instruction probes stub Delphi strings, collection accessors and
unit getters. They do not run original PP loaders, the GUI, a full project or a
generated HTML page. Synthetic vectors can describe object states outside the
bounded fresh PP adapter, to isolate method branches. Runtime generated-page,
byte/visual and printing acceptance remain unassessed.

To reproduce the static receipt, provide the exact pinned `CBusToolkit.exe` and
`.map` to `research/project_documentor_neo_usage_static.py`. The companion
`project_documentor_neo_usage_original.py` writes action vectors by default and
Input vectors with `--group-inputs`; its offline Unicorn emulator requires
executable memory. Tests opt into original execution only with
`CBUS_TOOLKIT_EXE` and `CBUS_RUN_DOCUMENTOR_ORIGINAL=1`.
