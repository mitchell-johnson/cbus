# Conversion and wireless batch: 2026-09-30

This batch follows the published firmware safeguard `500d8431` and integrates
the audited conversion and wireless chains. Both feature rows remain
`in_progress`; no broad parity obligation is completed by this batch.

The conversion registry admits 123 of 292 pairs and refuses 169. The added
profiles are five coupler-to-Neo directions at exactly 1.2.67→2.2.00 and ten
non-sensor InputUnit directions at exactly 1.2.67→1.2.67. The tweaker Python
API remains separate from the typed native C-Gate conversion CLI. See
[conversion rules](toolkit-conversion-tweakers.md).

Wireless adds WGATE5N/F Connection at 2.2.90..2.4.99, WGATE5F Scenes using
existing metadata, WTXU project-only creation, and typed cached GET versus
explicit opted-in DO workflows. Database persistence is not radio acceptance.
The native action case observes absent runtime caches and 401 refusal; no
physical DO is executed. See [wireless](wireless.md).

## Historical receipt provenance

Preserve every recorded hash. A receipt whose shared source later changed
certifies its historical capture, not the final merged source:

| Receipt | Source commit | Later shared-source change |
| --- | --- | --- |
| `coupler-tweaker-native.json` | `6fdb3ccaeec5bae0c6b549e8266503c416cefec0` | InputUnit changes `toolkit_conversion_tweakers.py` |
| `input-tweaker-native.json` | `2007228b9142999aac876be6a6fec0268f571a8f` | No audited owner-tip code-hash drift |
| `wireless-scenes-native-acceptance.json` | `e5ee2f09d2b8210877d1eb7f3aaf5eb1070cd3c4` | WGATE5N changes `wireless_connection.py` |
| `wireless-project-remotes-native-acceptance.json` | `7f8a2c34c432628e8b51803ba5d5831c92bf34ad` | Actions/base support changes `wireless_cli.py` and `cli.py` |
| `wireless-base-connection-native-acceptance.json` | `1959475f6a96d7a6444adb8bef9bde513b1b345a` | Merged firmware journal admission changes whole `cli.py`; the original five-file source bundle is retained and hash-checked independently |

Final-source reruns require new receipts; never rewrite historical hashes to
make them appear current. Closed synthetic C-Gate evidence does not execute
original Toolkit forms, touch a C-Bus network or establish device persistence.

## Native checks and original replay scope

The focused owned native tests are:

- `tests/test_coupler_tweaker_native.py::NativeCouplerTweakerTests::test_original_literals_all_five_profiles_raw_pp_and_project_reload`
- `tests/test_input_tweaker_native.py::NativeInputTweakerTests::test_original_literals_all_ten_profiles_raw_pp_and_project_reload`
- `tests/test_wireless_connection_native.py::WirelessConnectionNativeTest::test_plan_stale_apply_raw_readback_and_save_close_reload`
- `tests/test_wireless_scenes_native.py::WirelessScenesNativeTest::test_native_scene_arrays_editor_preservation_and_reload`
- `tests/test_wireless_project_remotes_native.py::WirelessProjectRemotesNativeTest::test_owned_metadata_creation_save_boundaries_and_preservation`
- `tests/test_wireless_base_connection_native.py::WirelessBaseConnectionNativeTest::test_plan_stale_apply_raw_readback_and_save_close_reload`
- `tests/test_wireless_actions_native.py::WirelessActionsNativeTest::test_database_units_do_not_invent_runtime_caches_or_trigger_physical_refresh`

Provision native inputs explicitly. Missing inputs skip; that is not native
acceptance. The six positive database nodes and the negative cached-action node
are now explicitly selected in the native release manifest. The regenerated
skip census requires and selects all 253 native-runnable tests; registration
alone does not prove that they ran. The focused combined receipt records actual
execution separately.

Exclude physical wireless learn/join/pairing, effectful DO acceptance, hardware
and power-cycle tests from a closed-project database replay. Keep synthetic
Python peers, Rust interop and static source proofs separate from original
Toolkit execution. No original GUI tweaker or wireless form replay is established.
The current native skip census has no explicit `NATIVE_EXCLUSIONS`; do not add
exclusions to hide a failing native test. Broader workflow conversion/wireless
obligations and strict evidence dimensions remain unchanged.

The base-connection historical source bundle (`research/fixtures/wireless-base-connection-native-source.zip`, SHA-256 `8e7c0c6e347790c57d82a2dd7984b4c42537c876b5a999c6aeb0eaaa67b0f40b`) contains exactly the five repository-owned files fingerprinted by its original receipt at `1959475f`. Those bytes are only hashed, never imported or executed. The three unchanged wireless production modules are also checked against current source; fresh merged CLI/native behavior receives separate integration validation. Initial stale-fingerprint failures remain in the combined acceptance history.
