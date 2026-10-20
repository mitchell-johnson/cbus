# Toolkit 1.18.0 C-Gate client inventory

`inventory.json` records which C-Gate commands C-Bus Toolkit 1.18.0.2754
sends and which replies it accepts, recovered by static analysis only. Use
it to check that `cgate-mock` answers Toolkit's commands in the shapes
Toolkit parses. `tests/test_toolkit_client_inventory.py` does that check.

## How it was recovered

- Tool: REA (`rea-agents` 6.7.0, managed provider `rea-dotnet-static` v1).
  `rea inspect-managed-members` read the ldstr literals and constants of
  every managed assembly. Nothing was loaded or executed.
- `SharpCGateCommunicator.dll` 7.15.0.0 (the managed client used by
  `CBusLogicModel` and eDLT) yields each `Command*.Prepare` template and the
  integer reply codes each `ProcessResponses` accepts.
- `CBusToolkit.exe` is native Delphi, which REA's managed provider cannot
  read. Its 131 `CIS_Tcgc*` command classes were covered by attributing
  strings in `.text` to the nearest preceding symbol in the shipped
  `CBusToolkit.map`. That attribution is reliable for Delphi literal
  layout but is not proven by disassembly. The integer reply-code compares
  in the native code were not recovered.

Vendor binaries, decompiled source, the client certificate password and the
embedded private key are not committed. Only command text, reply codes and
reply fragments are recorded here.
