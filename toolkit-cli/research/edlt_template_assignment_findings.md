# Original eDLT template assignment observations

The [67-case fixture](edlt_template_assignment_vectors.json) executes unchanged
original `PPAttribute` constructors and accessors on owned Mono64, in invariant
culture. Every case runs in a separate network-denied process and constructs a
new graph. No site data, C-Gate endpoint, device or original control is used.

The template assignment loop and first-match lookup are explicit harness
proxies transcribed from the fresh source evidence, not extracted original
TemplatesDialog code. The synthetic ListChanged/PropertyChanged handlers record
ordering or inject failures; they are not original Toolkit bindings. The
fixture identifies these limits so later composition cannot silently upgrade
the evidence into complete original form execution.

## Original methods and baseline

Assembly `CBusLogicModel.dll` is pinned to SHA-256
`34e9a52308cf2ea0ac83a2aef9123567d59b5cc35b28f95a2c47c3e6a34e8823`.
Actual loaded assembly hashes and every original PPAttribute method-body hash
are checked in each process. Relevant method identities include:

| Method | Token | RVA |
| --- | --- | --- |
| `.ctor` | `06000669` | `188cb` |
| `get_Value` | `06000652` | `18224` |
| `set_Value` | `06000653` | `18294` |
| `set_ValueFull` | `06000655` | `1834c` |
| `GetValue` | `06000664` | `1871c` |
| `SetValue` | `06000665` | `1873c` |
| `set_HasBeenChanged` | `0600064f` | `18208` |

Each baseline uses the real constructor, assigns Name and dirty state through
the original properties, and adds the explicitly supplied raw tokens to the
original Values BindingList. Listeners attach afterward. Raw baseline tokens
are not passed through the Value setter, which would normalize them before the
experiment. This makes unusual empty/null tokens explicit synthetic inputs,
not claims that a normal C-Gate load creates those token shapes.

## Value setters preserve token structure

The `Value` setter splits on literal ASCII space, preserving empty tokens, and
calls `SetValue(index, token)` in order. It neither clears nor truncates Values.
Thus assigning `X` to `[A,B,C]` yields `[X,B,C]`, and assigning `X Y` then `Z`
yields `[Z,Y,C]`. Assigning an empty string to `[A,B]` yields `['',B]`.
Tabs and newlines are part of a token; they are not delimiters.

SetValue normalizes each token before comparing or storing it:

- Exact lowercase `0xffffffff` becomes `0xff`; `0xFFFFFFFF` and `0Xffffffff`
  remain unchanged.
- A token starting with lowercase `$x` loses its first character and gains
  `0`, preserving the remaining suffix case: `$xab` becomes `0xab`.
- Otherwise a token starting with `$` gains `0x` and uppercases its suffix
  using the current culture: `$ab` becomes `0xAB`, `$Xab` becomes `0xXAB`.
- `$` and `$x` both become `0x`. No numeric validation is performed.

The prefix tests are culture-sensitive. Under the retained invariant runtime,
`$`, U+200D, `xab` enters the `$x` branch and becomes `0`, U+200D, `xab`.
Leading U+200D followed by `$xab` likewise enters that branch, but its literal
substring operation yields `0$xab`. An ordinal prefix test would miss both.
Invariant `.NET ToUpper` also differs from Python full uppercase: `$ß` becomes
`0xß`, and `$ı` becomes `0xı`. Python `.upper()` would produce `0xSS` and
`0xI`. A portable implementation must pin a supported culture/text profile or
explicitly refuse these ambiguous forms. Numeric ASCII `$` hex tokens avoid
these demonstrated Unicode differences.

The `ValueFull` setter has a different contract: it clears Values and stores
the whole string as **one** token. `X Y` therefore produces `['X Y']`.
It is not a substitute for `Value`. A null Value fails before writing; a null
ValueFull first clears the list and then fails, leaving the list empty.

SetValue at an index beyond the end appends one token; it does not fill missing
indices. Negative indices fail. The integer property setter clamps to 0..255,
uses uppercase hex, and likewise retains an old token tail.

## Getter and dirty-state consequences

Value and ValueFull use the same getter: append a separator only when the
current StringBuilder length is nonzero, then append the next token. Leading
empty/null tokens therefore disappear in the joined string. For example,
`['','','B','']` reads as `B `, which cannot reconstruct the original tokens.
This getter is unsuitable as the sole snapshot for exact token restoration.

The recorded getters do not mutate values or dirty state. The integer getter
reads only token 0, recognizes `0x` case-insensitively, accepts its framework
numeric whitespace, and can return signed -1 from raw `0xffffffff`. An empty
or null first token fails for the integer getter. The Boolean getter is false
only for exact `0x0`; null, decimal `0` and `0X0` all return true. An index
beyond the end returns null; a negative index fails. ValuesAsInt combines
hexadecimal tokens little-endian (`0x01 0x02` returns 513).

Outside initialization, changing a token updates the BindingList, emits its
ListChanged event, sets HasBeenChanged true, and emits PropertyChanged("Value").
This repeats per token. During initialization, ListChanged still fires, while
the setter's dirty assignment and PropertyChanged notification are suppressed.
Setting HasBeenChanged directly does not emit a property notification.

## Template loop boundaries and failures

The proxy follows `TemplatesDialog.BtnLoadClick`, token `060001e7`, RVA
`f368`, in this order for **each child**:

1. Convert nonempty Application decimal tokens to lowercase hexadecimal.
2. Set the static `PPAttribute.bInitialiseMode` to true.
3. Find the first exact-name matching attribute.
4. If present and joined Value differs from the raw assignment string, call
   the original Value setter, then explicitly set HasBeenChanged true.
5. Set the static flag to false.

The initialization flag is set and cleared per child, not once per complete
assignment list. A malformed Application fails before changing the flag or
performing lookup, even if no Application attribute exists. A pre-existing
stale true flag survives that failure. A successful child clears a stale flag
to false instead of restoring its previous value.

The comparison precedes token normalization. Assigning `$ab` to
`['0xAB','tail']` emits no list events because the normalized token is already
equal, but explicitly marks the attribute dirty because the joined raw
comparison differed. Conversely, assigning `B ` to `['','','B','']` skips the
setter altogether and preserves both the original token shape and dirty flag.

An injected list listener failure occurs after the affected token changed but
before the remainder of SetValue. During the template proxy, a failure at the
second token can leave `[X,Y,C]`, dirty=false and initialize=true. With two
attributes, failure in the second leaves the first changed and dirty, the
second changed and not dirty, and the global flag true. A direct property
listener failure leaves the first changed token and dirty=true. Property
listener failures are suppressed by initialization in the template proxy.

These failures expose the original partial-state behavior. A safe immutable
staging transaction should not copy that failure behavior into a live editor.
Its success projection must still preserve the established raw-token, dirty
and assignment-order rules within its admitted scope.

## Suggested staging representation

Use an ordered immutable collection of `{name, tokens, dirty}` snapshots,
including explicit empty/null token facts when admitted, rather than a map of
joined Value strings. Report both raw assignment candidates and final token
projections. Keep the reset baseline, ordered assignment result and second
model load as separate evidence-bearing stages. Refuse unsupported culture,
binding or lifecycle inputs before invoking a live setter; discard the whole
detached stage on failure. Token projection alone does not establish parent
reset, binding refresh, Apply/OK persistence or original GUI acceptance.

## Reproduction

Run `edlt_template_assignment_original.py --logic-dll OWNED_DLL --mono-root
OWNED_MONO --output NEW_DIRECTORY`. To replay the literal results, add
`--verify-fixture toolkit-cli/research/edlt_template_assignment_vectors.json`.
The runner checks pinned runtime/compiler/assembly hashes, loaded assemblies,
method-body consistency across fresh processes, network denial and unchanged
inputs. It records bounded stdout/stderr and a report. It never patches vendor
methods, constructs a Toolkit model or form, or contacts any endpoint.
