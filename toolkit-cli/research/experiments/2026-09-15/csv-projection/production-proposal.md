# Proposed next production boundary — cached-row projection

The first pilot supports a pure cached-unit projection stage composed with the accepted `document_database_csv` serializer. It does not yet support a generic project XML reader or a native Document Database command. No production file has been changed for this proposal.

## API

Add a separate `toolkit_database_csv_projection.py` module with immutable exact-type records and no I/O:

- `CachedCSVUnit`: original supplied type/firmware, explicitly captured scalar report fields, primary/secondary application labels, ordered retained unit-group references, and an explicit class-resolution profile.
- `CachedCSVGroup`: caller-supplied object identity, numeric address, tag and OID token. The complete ordered relevant group cache is required; absent and unknown are distinct.
- `CSVAreaObservation`: one supplied original `QuickGet` outcome and raw `AreaGroupAddress` text, or a declared failed load. These are captured facts, never inferred from another field or silently duplicated.
- `project_cached_csv_unit(unit, *, group_cache, area_observations, columns) -> CachedCSVProjection`.

The result contains the projected `CSVUnitValues` only when row projection completed, a pure after-state, ordered getter/load/group/reference operations, any required group-save operation, and an explicit completion/partial reason. It retains both raw Area text and effective reference target. It can then call the existing serializer, preserving its original quoting and deferred missing-group placeholders. Existing CSV APIs and their input format remain unchanged.

The initial profile must name the actually evidenced generic/RELAY4 registration and require the admitted input topology. It must not assume any unlisted type is generic or silently replace the firmware comparator with `System.Version`/natural sorting. The first implementation can admit only the captured type/firmware patterns; extending those requires independently prepared original comparator/class cases. Scalar text formatting already belongs to the separately accepted serializer evidence, not this factory pilot.

## Mutation policy

This module only models a supplied cached state; it cannot create or save external metadata. It always evaluates the Area getter stage even when the column is excluded. Relay success requires two explicit sequential load observations. Cold nil reference state and the tested 12/13/255/invalid strings are the initial declared domain. Existing distinct group identities must be retained; changing 12→13 removes the old Area reference membership before adding the new one.

A missing255 path yields the modeled newly created `<Unused>` group and a required `GroupSave` before reference installation. The caller must supply an explicit recorded save outcome to continue that path. A denied save retains the partial cache addition and leaves the Area reference nil. An offline convenience mode may reject any required save and return its dependency evidence, but must not emit a completed row. No automatic native mutation, exception unwind, network fallback or retry is implied.

## Meaningful acceptance before enabling a broader profile

Replay every captured original case from `original-pilot-v1`, comparing literal rows, class, ordered effects, raw/effective Area state, reference target/token/membership, dirty/update state, group identities, and partial save/load outcomes. Test strict input types, complete cache declarations, caller immutability and missing/unknown observations. Compose completed projections with the existing serializer so expected CSV comes from original literal rows rather than a second implementation of the same algorithm.

For a useful wider profile, prepare a small additional original matrix before implementation approval: variable retained unit/group addresses and labels, reordered cache entries, explicit nil/unused application/reference cases, nonempty serial fields, and different missing-group patterns. The present pilot's full constructor/cache deserialization exclusions must remain visible. Do not claim this matrix already ran.

## Database integration still requiring proof

A separate future adapter must establish the actual StorageLoad/QuickGet backend command and response-to-field projection, all required cached application/group facts, and the original class-registration mapping for supported unit types. Native JSON/XML fields cannot be treated as original object fields by name alone. A read-only adapter should reject an unavailable Area group before original metadata creation, with evidence that the native operation would require `GroupSave`; it should not silently produce a different original row. A writing adapter would need its own backup/stale-state/readback/non-atomic failure contract.

Recommendation: use the captured-row projection as the next narrow production stage only if an explicit observed-cache input is useful to the caller. To close the end-to-end report workflow, prioritize proving the backend QuickGet/cache projection next; avoid shipping a generic XML-to-CSV command from this pilot alone. Root owns any eventual shared CLI integration.
