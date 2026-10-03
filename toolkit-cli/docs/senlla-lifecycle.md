# SENLLA update and attribute lifecycle

The internal `senlla_lifecycle` module supplies synchronous counters and
attribute setters for the owning event engine. The
[numeric source fixture](../research/fixtures/senlla-lifecycle-source.json)
pins 65 methods. Independently reviewed source traces establish the manager,
parent, publication and dedicated callback order.

An attribute begins its manager and parent before incrementing its own counter.
It ends its own counter first. At zero it runs its generic callbacks, manager
notification and dedicated AfterChange while the parent is still updating.
Only when those return does it end the manager and parent. The final parent
notification does not replay direct refreshes that were suppressed earlier.

Equal Boolean writes return immediately. Equal object-reference writes still
complete the update and dedicated callback. Clearing a non-null reference
delivers AfterChange once at attribute depth1 and again at depth0. The same
occurs when BeforeChange forces an equal nil assignment. A recursive reference
write while that attribute is updating is ignored; other attributes can still
change. Reference BeforeChange can cancel a write, but its replacement pointer
is ignored by the native setter. Integer BeforeChange runs before validation
and honors its proposed integer.

Managed publication has its own guard. Reference and Boolean getters rearm it;
the direct integer getter does not. Custom key/block Changed rearms before
publishing. Subscribers run in reverse registration order, using the current
list at each index. The source prevents duplicate registration by identity.
An exception stops delivery. If the final attribute callback raises, the value
remains assigned and manager/parent counters stay incremented because the
native attribute EndUpdate does not protect their completion with `finally`.

The stable active tracked-reference handler rereads the root attribute's current
pointer at each notification. It replaces the target subscription before
delivering a pointer change and suppresses equal pointers. A direct target
notification still delivers while the key is updating. Newer root observers
run first; if one changes the template recursively, older observers read the
resulting template. Initial non-null binding and a transition to nil both
deliver; initial nil binding does not.

Focused tests exercise nested callbacks, six independent reference vectors,
the Scene parent-counter suppression and an equal nil expiry override that
reaches the actual bank observer. They use synthetic objects and source-derived
predictions. This component does not install application, Scene, general
expression-controller or form handlers, expose a public whole-unit save, or establish
original, native-service or hardware acceptance. Integer bounds belong to the
owning constructor; invalid counter balancing refuses at this internal boundary.
