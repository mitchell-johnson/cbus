# External-application boundaries (issue #11 box 13, bead cbus-ahr)

Decision record pinning what is **not** Toolkit parity scope, grounded in
`toolkit-surface.md#boundaries-requiring-explicit-decisions`. Each entry
states the decision, the census evidence, and what would change it. No
implementation is claimed here.

## Decisions

1. **Touch-screen / controller dialog editors → external (PICED).**
   The controller dialog topics name PICED as the programming
   application (5414.htm MK2 logic-engine config; 13447.htm Colour
   C-Touch config). Decision: integration-vs-external scope must be
   defined before any controller-editor parity claim. Changes with:
   vendored PICED-interface evidence + per-dialog differential cases.

2. **Security-system editor → out of scope.**
   Security appears as application/message reference only (12335.htm,
   12336.htm, 12338.htm); that does not establish a Toolkit
   security-system editor. Changes with: editor dialog inventory +
   device-accepted workflow evidence.

3. **General scheduler → out of scope; thermostat scheduler only.**
   Navigation documents the thermostat scheduler (2782.htm, 2791.htm,
   7036.htm), not a standalone general scheduler. Changes with:
   general-scheduler dialog inventory + schedule-execution evidence.

4. **Logic-engine code editing → external software.**
   Relay/dimmer *logic control* is an explicit Toolkit workflow
   (9433.htm, 9855.htm, 9858.htm) and stays in scope; the DIN Logic
   tab is implemented by `din_output_settings.py`
   ([DIN output settings](din-output-settings.md)). Controller
   logic-engine *code editing* may belong to external software. Pinned
   in code as `din_output_settings.LOGIC_ENGINE_BOUNDARY = "external"`.
   Changes with: editor-capability evidence distinguishing the two.

5. **Non-eDLT device updaters → unevidenced scope.**
   Firmware updating is documented for the eDLT updater (19096.htm);
   other device updater scope needs separate evidence. Changes with:
   per-device updater input/protocol/version evidence.

## PICED handoff: negative static search (P8.04)

Toolkit 1.18.0.2754 contains no PICED or controller handoff to implement.
`research/barcode_scanner_original.py` records the searched binaries,
patterns and match counts in
`research/fixtures/barcode-scanner-original-vectors.json`
(`piced_negative_search`):

- **Inputs:** `CBusToolkit.exe`
  (SHA-256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab`)
  and `CBusToolkit.map`
  (`f96f05cef7c2bdf0f295397d97249b50c45db013f3fcaa2c502f76e2c10dd1eb`).
- **MAP symbols:** 0 case-insensitive matches for `piced`.
- **EXE strings:** 0 ASCII matches. There are 3 UTF-16 matches, and all
  are resource strings (IDs 64325, 64347 and 64349). Each one only warns
  the user to close a running PICED instance before Toolkit renames,
  restores or deletes a project.
- **Other application binaries:** none of the other 26 `.exe`/`.dll`
  files in the Toolkit application directory contains `piced` in either
  encoding.
- **Process launches:** every `ShellAPI.ShellExecute` and
  `Windows.CreateProcess` caller in the MAP targets C-Gate server
  start-up, web pages, IP utilities, documentation or dependency checks.
  None of them starts PICED or passes a project or controller to it.

Fifteen help topics mention PICED as the programming application for
controllers (see decision 1). Help text alone does not establish a
Toolkit-owned roundtrip. Controller and PICED editing therefore stays
external. The only Toolkit-owned PICED behavior is the three
close-PICED warnings. Changing this requires a Toolkit build or a
separate component that contains an actual launcher or exchange path.

## Rule

No external-editor behavior is claimed as Toolkit parity. Boundary
changes require the stated evidence first; until then the ledger
treats these areas as explicitly out of scope rather than pending
implementation.
