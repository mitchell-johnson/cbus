# SENLLA identification name component

`senlla_identification.py` retains the actual inherited UnitName string
attribute, TagName attribute and persistent edit/controller cache. It executes
the name position of `SetupFlashComponents`, direct form `edtUnitNameExit`,
and FlashEdit's separate OnExit-then-Apply order. This is an internal component;
complete identification and the public SENLLA workflow remain incomplete.

String-controller activation renders under the source update locks. Each
render clears dirty, reads the current string attribute, calls the control,
then rereads the current attribute into the cache. A render callback can leave
dirty true even though cache restoration has replaced its pending text.
Programmatic SetText compares exact UTF-16 text. A changed no-HWND text runs
WM_SETTEXT, CM_TEXTCHANGED and FlashEdit.Change; Change updates the controller
cache before the form's OnChange. The helper supplies no uppercase or
eight-character truncation. The DFM's uppercase style and MaxLength eight
belong to the actual native edit window.

The freshly installed name-change handler obtains GetSelStart first. Its
implementation calls GetHandle and then Win32 EM_GETSEL. Thus any changed
text, including already-valid text, reaches an actual window lifetime that
the portable component does not own. `IdentificationWindowRequired` stops at
that source position after the preceding text/cache operations. It does not
substitute a selection value or skip the handler. An interrupted owning
runtime cannot resume or serialize. Root-link activation and event delivery
for the allocated window must be implemented before this can close a full
fresh identification phase.

Direct form Exit captures the original UTF-16 length and rereads current
control text at every character predicate and accepted-character append. It
retains code units 33 through 96 except 60 and 62. It does not uppercase,
trim or replace spaces. If no units survive, it assigns the source fallback
`NEWUNIT`. A changed assignment reaches OnChange's window boundary before
TagName getters. With unchanged valid text, Exit reads actual TagName, checks
empty first and then the exact case-sensitive `NEWUNIT` value, and writes
current control text through the actual TagName setter when admitted. The
bridge still requires its actual notification/timer owner for that write.

Direct form Exit does not Apply UnitName. Real FlashEdit DoExit invokes form
OnExit first and its umExit controller Apply afterward. Apply honors dirty,
read-only, active and update-lock gates, refreshes after setter failure and
clears dirty only on a successful return. A source callback can interrupt
after a partial model assignment; the component preserves that state instead
of reporting a completed save.

Focused cases cover nested render setters, post-render cache restoration,
exact text/cache behavior, Apply gates and failure, UTF-16 predicate vectors,
TagName getter short circuits and source window interruption order. Some
direct-handler cases deliberately supply an already-populated authored
control state; they are not evidence of native DFM rendering. The derived
fixture records source method, virtual-slot, bitset and DFM hashes only. No
vendor specifications or raw source instructions are included.

Remaining ownership includes the earlier firmware/catalog controls, complete
identification SetData/root links, application and area lists, native window
creation/selection/event delivery, focus, director initialization, Show,
whole-unit Apply/save and public preview/apply. No original Windows,
installed-wheel or hardware acceptance is claimed.
