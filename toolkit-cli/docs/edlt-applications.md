# eDLT application control phases

The Python `EdltApplications` workflow implements the original Primary and Secondary Application controls for KEYGL5 / 5055EDL / firmware 5.5.00. It loads the model once, prepares the ordered application lists, binds those two controls, commits an ordered sequence, validates and prepares the original model save. The Python workflow and CLI have passed original Toolkit and closed native C-Gate database checks on Python 3.13 and 3.10.

`ApplicationCache` supplies complete ordered application inventory, group presence and the existing lifecycle facts. See [the cache contract](edlt-application-cache.md). Names and formatted displays remain distinct. Duplicate display names are permitted; duplicate numeric object identities are rejected. Caller completeness is an explicit input contract, not verification against a physical network.

```python
from cbus_toolkit.edlt_applications import EdltApplications, ApplicationEdit

editor = EdltApplications(spec)
plan = editor.plan(full_parameters, cache=cache, edits=[
    ApplicationEdit('secondary', 255),
    ApplicationEdit('primary', 57),
    ApplicationEdit('secondary', 56),
])
print(plan.as_dict())
```

Lists preserve cache order and allow applications 48..127 plus 136. Each excludes the other currently stored application. Secondary additionally offers 255 (`<Unused>`). An unavailable request fails before any native parameter writes. No temporary selection is inserted automatically. A same-value selection emits no wrapper change; disabling and re-enabling Secondary does not restore widget selector bits cleared during the intermediate action.

For callers inspecting phases, the methods are `load`, `prepare_applications`, `bind_global_applications`, `commit_application`, `validate_bound_controls` and `prepare_save`. They return immutable issued states. Validation ends the selection sequence; further selections require a new editing operation. A state keeps its original loaded scenes, cached scene item references, widget families, static labels and MRA globals. It cannot be resumed from a diagnostic JSON dictionary or modified with `dataclasses.replace`. Application sequences accept at most 64 selections.

Save uses the original retained model projection. It changes the application pair and final selector bit 7 on unchanged application/group widget models, preserves the lower seven bits after original save-time forcing, and calculates all five configuration CRCs again. It does not run AfterLoad again. For example, disabling Secondary can leave a scene selector at 1 and its item referring to application 57; binding the separate SceneManager can have different effects and is outside this composition.

`apply` requires a canonical plan and an unchanged complete source snapshot, stages only a database programming session, and verifies full readback. `configure` combines planning and staging. Database persistence remains the programming session's explicit save operation. Connected rollback preserves original error and cleanup evidence; interruption does not replay programming.

The current fixed-vector checks cover 210 original model/global-control cases, 1,167 complete parameter snapshots, 18 unavailable requests and 16 explicit malformed-input/cache exclusions. A separate original probe omits dependency getters and uses a canonical 232-byte scene bucket: 39 accepted cases match all 874 parameters in four phases and all eight retained scene scalar/item-reference observations, with one unavailable selection rejected. These include MRA/scene combinations and Fan/MultiLevel status forcing. Historical 256-value scene diagnostics remain archived and are not silently truncated into supported inputs.

The [focused acceptance](../research/fixtures/edlt-applications-acceptance.json) records 13 tests with zero skips on Python 3.13.14 (131.908 seconds) and 3.10.20 (145.089 seconds). Fourteen fresh original/native cases per run compare all 874 parameters in four original phases, all five CRCs, full native staging and save/close/load readback, plus the application and widget-control raw bytes before and after reload. Each case uses an owned closed database project and removes it afterward. Fixed and native checks make 1,229,718 parameter comparisons per Python version.

The CLI preserves selection order:

```sh
cbus-toolkit edlt applications-plan snapshot.json --metadata application-cache.json \
  --select secondary=255 --select primary=57 --select secondary=56
cbus-toolkit cgate unit --lock-address //TEST/254 --source /db//TEST/254/p/20 \
  --dry-run edlt-applications --metadata application-cache.json --select secondary=255
```

Remove `--dry-run` to save to the database source; save the project separately for disk persistence. [CLI acceptance](../research/fixtures/edlt-ordered-control-cli-finalization-acceptance.json) covers both ordered editors, malformed inputs before programming, interruption evidence, full native readback and save/close/load on both Python versions.

The original observations are frozen in `research/fixtures/edlt-application-observations.json` and `research/fixtures/edlt-application-terminal-vectors.json`. Their compactor reads and verifies original capture provenance without importing a Python editor. The initial native pilot used decimal tokens for the original CRC memory path; that fixture encoding error and its failed report are retained. The corrected native fixture uses the original hexadecimal PP representation.

Remaining scope includes dependent widget/group/PageWidget/SceneManager bindings, their explicit mutating getters, metadata creation, the complete Toolkit form and physical transfer. Model-only raw PP setters and forced unavailable wrapper assignments remain research diagnostics, not alternative user-facing selection operations. Full Toolkit parity is incomplete.

The CLI retains staging evidence if the final readback, save, programming cleanup
or connection cleanup fails. A lost save reply reports an uncertain save; a
confirmed save remains confirmed when later cleanup fails. It does not replay
or roll back an uncertain save. Fresh per-command evidence also survives an
interruption that refuses exception attributes, without borrowing a previous
operation's evidence.
