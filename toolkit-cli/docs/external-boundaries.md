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
   (9433.htm, 9855.htm, 9858.htm) and stays in scope for channel
   planning (`relay_dimmer_logic.py`); controller logic-engine *code
   editing* may belong to external software. Pinned in code as
   `relay_dimmer_logic.LOGIC_ENGINE_BOUNDARY = "external"`.
   Changes with: editor-capability evidence distinguishing the two.

5. **Non-eDLT device updaters → unevidenced scope.**
   Firmware updating is documented for the eDLT updater (19096.htm);
   other device updater scope needs separate evidence. Changes with:
   per-device updater input/protocol/version evidence.

## Rule

No external-editor behavior is claimed as Toolkit parity. Boundary
changes require the stated evidence first; until then the ledger
treats these areas as explicitly out of scope rather than pending
implementation.
