# Local verification battery for the Python C-Bus Toolkit CLI.
#
# This is not the release wheel gate: it runs everything provisionable on
# this machine and reports the completion gate status (expected nonzero while
# parity work remains). The fresh-wheel run with all 14 native gates is
# separate; see docs/implementation-status.md for the recipe and the
# remaining provisions (owned TEST_HOST server, Windows/mono, Toolkit EXE,
# CSV admission).
#
#   make check          full source-tree suite (provision-gated tests report skips)
#   make check-offline  source-tree suite without Rust interop modules
#   make check-native   strict owned-process C-Gate + original-instruction gate
#                       (fails on a stale skip census, missing provision or
#                       any skipped test)
#   make check-hardware strict private-manifest hardware gate
#   make check-interop  Python-to-Rust interop against cgate-mock and cmqttd
#                       (rebuilds both binaries, runs the native SESSION_ID
#                       differential, then exercises both server suites)
#   make check-session-differential
#                       nine original-vs-Rust SESSION_ID cases on each binary
#   make check-tagged-session-differential
#                       eleven exact numeric-tag wire cases on each binary
#   make check-dbsetxml-unit-differential
#                       twelve exact-wire Unit mapper cases plus two full Network reads
#   make check-dbgetxml-wire-interop
#                       Python client and pipelined XML reads on both Rust servers
#   make check-wheel    build a fresh wheel, install it with every supported
#                       extra in an isolated Python 3.13 venv, and run the
#                       full offline suite without importing from src/
#   make check-parity-register  verify generated scope/evidence accounting
#   make refresh-parity-receipts
#                       rebuild both servers, re-run every source-bound
#                       differential into research/fixtures, then regenerate
#                       the contract inventory, applicability and register
#   make coverage       print the evidence-derived completion gate status
#   make require-complete
#                       enforce the evidence-derived gate (nonzero until parity)
#   make compile        byte-compile the package

VENV = .venv
PY = $(VENV)/bin/python
RUST_DIR = ../rust
WHEEL_PY ?= python3.13
PYTEST_EXTRA ?= -ra
CGATE_INTEROP_PYTEST_EXTRA ?= $(PYTEST_EXTRA)
CMQTT_INTEROP_PYTEST_EXTRA ?= $(PYTEST_EXTRA)
CGATE_MOCK_BIN ?= $(abspath $(RUST_DIR)/target/debug/cgate-mock)
CMQTTD_BIN ?= $(abspath $(RUST_DIR)/target/debug/cmqttd)
NATIVE_GATE_MANIFEST ?= research/release-gates/native.json
NATIVE_GATE_JUNIT ?= research/runtime/release-gates/native.xml
NATIVE_GATE_OUTPUT ?= research/runtime/release-gates/native.json
HARDWARE_GATE_JUNIT ?= research/runtime/release-gates/hardware.xml
HARDWARE_GATE_OUTPUT ?= research/runtime/release-gates/hardware.json
export PYTHONPATH = src:tests

check: compile check-parity-register
	$(PY) -m pytest tests/ -q -p no:cacheprovider $(PYTEST_EXTRA)

check-offline: compile check-parity-register
	$(PY) -m pytest tests/ -q -p no:cacheprovider \
		--ignore=tests/test_rust_cgate_interop.py \
		--ignore=tests/test_cmqtt_interop.py \
		--ignore=tests/test_cmqtt_programming_methods_interop.py \
		--ignore=tests/test_cmqtt_dali_commissioning_interop.py \
		$(PYTEST_EXTRA)

check-parity-register:
	$(PY) research/build_cgate_contract_inventory.py --check
	$(PY) research/build_parity_register.py --check

check-native: compile
	$(PY) research/skip_census.py --check
	$(PY) research/release_gate.py $(NATIVE_GATE_MANIFEST) --gate native \
		--junit $(NATIVE_GATE_JUNIT) --output $(NATIVE_GATE_OUTPUT)

check-hardware: compile
	: $${CBUS_HARDWARE_GATE_MANIFEST:?Set CBUS_HARDWARE_GATE_MANIFEST to the private hardware test manifest}
	$(PY) research/release_gate.py "$${CBUS_HARDWARE_GATE_MANIFEST}" --gate hardware \
		--junit $(HARDWARE_GATE_JUNIT) --output $(HARDWARE_GATE_OUTPUT)

coverage:
	$(VENV)/bin/cbus-toolkit coverage --require-complete; \
	status=$$?; echo "coverage-gate-exit=$$status (1 while parity work remains)"; exit 0

require-complete:
	$(VENV)/bin/cbus-toolkit coverage --require-complete

build-interop:
	cd $(RUST_DIR) && cargo build -p cbus-cgate -p cmqttd
	test -x "$(CGATE_MOCK_BIN)"
	test -x "$(CMQTTD_BIN)"

check-cgate-interop: compile
	test -x "$(CGATE_MOCK_BIN)"
	CBUS_CGATE_MOCK_BIN="$(CGATE_MOCK_BIN)" $(PY) -m pytest \
		tests/test_rust_cgate_interop.py \
		'tests/test_cgate_named_database_interop.py::test_public_named_safe_graph_separate_project_selected_sessions[mock]' \
		'tests/test_cgate_named_database_interop.py::test_public_renamed_associated_level_cli_owner_and_wire[mock]' \
		'tests/test_cgate_named_database_interop.py::test_public_associated_empty_tags_copy_after_reload[mock]' \
		'tests/test_cgate_named_database_interop.py::test_public_associated_raw_level_value_literal_and_preservation[mock]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_named_unit_preservation_and_lifecycle[mock]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_numeric_unit_issued_identity[mock]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_guards_are_read_only[mock]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_failure_is_exact_once_without_rollback[mock]' \
		'tests/test_cgate_neopro_csv_interop.py::test_public_neopro_csv_project_network_selection_on_owned_backend[mock]' \
		'tests/test_cgate_neopro_csv_interop.py::test_public_neopro_csv_late_unsupported_profile_refuses_atomically[mock]' \
		'tests/test_cgate_neopro_csv_interop.py::test_public_neopro_csv_lost_snapshot_terminal_is_not_retried[mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[dimmer-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[relay-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[classic-key-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[coupler-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[input-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_stale_plan_and_alias_collision_refuse[mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay[lost-add-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay[lost-save-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay[lost-set-mock]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_declared_assignment_failure_keeps_reviewed_plan[mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[dimmer-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[relay-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[classic-key-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[coupler-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[input-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[backup-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[add-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[set-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[pp-save-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[delete-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[readdress-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[project-save-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[close-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[load-mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_stale_plan_and_occupied_backup_no_write[mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_declared_assignment_refusal_preserves_source[mock]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_malformed_recovery_and_apply_guards_never_connect' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_project_network_selection_on_owned_backend[mock]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_late_refusal_on_owned_backend_is_atomic[bad-profile-mock]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_late_refusal_on_owned_backend_is_atomic[channel-tail-mock]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_late_refusal_on_owned_backend_is_atomic[secondary-owner-mock]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_lost_snapshot_is_not_retried[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_exact_action_creation[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_action_dialog_seed_and_save[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_dialog_cancel_preserves_metadata[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_trigger_then_action_dialog_order[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_lost_save_never_replays[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_dialog_name_guards_precede_mutation[mock]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_restored_display_name_is_not_retained[mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[classic-prefix-no-inherited-hook-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[classic-prefix-no-inherited-hook-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-standard-pa6-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-standard-pa6-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[saturn-pcx-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[saturn-pcx-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[reflection-pcx-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[reflection-pcx-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-classic-model-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-classic-model-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keye-shared-spec-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keye-shared-spec-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[dlt-source-retains-dlt-only-fields-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[dlt-source-retains-dlt-only-fields-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_unknown_receipt_never_replays[lost-create-save-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_unknown_receipt_never_replays[lost-replace-delete-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_stale_plan_and_source_firmware_refuse[mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-secondary-mask-removal-before-area-reshape-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-secondary-mask-removal-before-area-reshape-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-matching-application-object-removes-primary-too-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-matching-application-object-removes-primary-too-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-unused-secondary-keeps-lexical-application-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-unused-secondary-keeps-lexical-application-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-all-secondary-area-is-independent-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-all-secondary-area-is-independent-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-forward-swap-decimal-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-forward-swap-decimal-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-catalogue-alias-forward-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-catalogue-alias-forward-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-reverse-swap-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-reverse-swap-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-alias-reverse-swap-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-alias-reverse-swap-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-six-default-fields-and-polarity-aligned-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-six-default-fields-and-polarity-aligned-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-self-retains-fresh-learning-history-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-self-retains-fresh-learning-history-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-self-no-st7-lux-rewrite-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-self-no-st7-lux-rewrite-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-to-multisensor-rename-and-fresh-unassigned-groups-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-to-multisensor-rename-and-fresh-unassigned-groups-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-multisensor-self-input-flag-overridden-and-join-reset-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-multisensor-self-input-flag-overridden-and-join-reset-replace-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_lost_success_never_replays[create-PP SAVE_TO_SOURCE-mock]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_lost_success_never_replays[replace-DBDELETE-mock]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_all_templates_and_ordered_selection[mock]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_late_refusal_is_atomic[bad-profile-mock]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_late_refusal_is_atomic[missing-application-mock]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_lost_snapshot_is_not_retried[mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[corridor-and-activation-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[cancel-repeat-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[preceding-enable-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[scene-interleave-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[initial-scene-getter-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[corridor-future-absence-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[application-switch-future-absence-mock]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_lost_save_success_is_not_replayed[mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keybir2-literal-keyb2-catalogue-alias-create-mock]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keybir2-literal-keyb2-catalogue-alias-replace-mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_all_literals_and_ordered_selection[mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_lost_snapshot_is_terminal_without_replay[mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[bad-profile-mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[missing-application-mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[missing-secondary-input-group-mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[missing-unused-temperature-group-mock]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[bad-fan-route-mock]' \
		'tests/test_cgate_project_documentation_interop.py::test_public_database_document_snapshot_and_literal_bodies[mock]' \
		'tests/test_cgate_project_documentation_interop.py::test_public_database_document_absent_network_is_atomic[mock]' \
		'tests/test_cgate_project_documentation_interop.py::test_public_database_document_lost_snapshot_has_no_output_or_retry[mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[application-description-group-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[cancel-repeated-primary-secondary-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-application-group-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-cancelled-application-fresh-primary-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-initial-scene-before-action-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-application-scene-corridor-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[preceding-and-future-owner-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[expanded-reserved-confirmed-mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_lost_save_is_not_replayed[mock]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_add_guards_refuse_without_persistent_send[mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[default-repair-grid-before-widget-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[cancel-repeated-selected-list-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[absent-collection-chinese-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[zero-default-first-selected-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[allocated-widget-then-grid-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[language-parent-and-scene-add-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_lost_success_stops_without_replay[add-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_lost_success_stops_without_replay[set-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_lost_success_stops_without_replay[pp-save-mock]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_invalid_history_never_writes[mock]' \
		'tests/test_cgate_project_documentation_sensors_interop.py::test_public_database_document_sensor_families_preserves_snapshot[mock]' \
		'tests/test_cgate_project_documentation_wireless_interop.py::test_public_database_document_wireless_families_preserves_snapshot[mock]' \
		'tests/test_cgate_project_documentation_l1_interop.py::test_public_database_document_l1_preserves_snapshot_and_literal_body[mock]' \
		'tests/test_cgate_project_documentation_architectural_interop.py::test_public_database_document_architectural_families_preserves_snapshot[mock]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_history_preview_apply_and_preservation[cell-transactions-mock]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_history_preview_apply_and_preservation[cached-split-name-mock]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_history_preview_apply_and_preservation[malformed-preserved-mock]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_pending_cell_close_refuses_without_write[mock]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_lost_successful_save_is_not_replayed[mock]' \
		'tests/test_cgate_project_documentation_native_addresses_interop.py::test_public_native_report_exact_named_identity_and_physical_references[mock-thermostat]' \
		'tests/test_cgate_project_documentation_native_addresses_interop.py::test_public_native_report_exact_named_identity_and_physical_references[mock-wireless]' \
		'tests/test_cgate_project_documentation_st7_light_level_interop.py::test_public_database_document_st7_zero_timers_stored_scenes_and_direct_roles[mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[application-secondary-selector-one-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[trigger-callback-action-valid-in-both-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[action-selected-duplicate-name-exact-identity-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[null-current-retains-stale-action-binding-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[scene-two-rebinding-does-not-leak-first-labels-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[label-selection-3-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_refusals_precede_database_writes[cache-injection-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_refusals_precede_database_writes[future-parent-action-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_prior_parent_add_visible_later_add_excluded[mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_lost_successful_save_never_replayed[pp-save-mock]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_lost_successful_save_never_replayed[project-save-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[action-add-explicit-rebind-sees-new-generation-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[action-add-current-getter-view-new-old-binding-separate-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[canceled-action-add-keeps-bound-generation-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[trigger-add-then-explicit-callback-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[canceled-trigger-add-keeps-current-and-inventory-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[old42-choice-writes-current43-setter-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[old42-existing-choice-current43-existing-labels-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[trigger-callback-creates-missing-retained-action-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[missing-trigger-getter-requested-not-first-free-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[initial-loader-reserves-before-first-dialog-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[all-eight-loader-getters-reserve-before-first-dialog-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[later-initial-getter-keeps-earlier-label-generation-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_ordered_parent_add99_scene_add2_later_add100[mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[terminal-fallback-zero-not-borrowed-early-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_standalone_owner[action-add-explicit-rebind-sees-new-generation-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_standalone_owner[missing-trigger-getter-requested-not-first-free-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_standalone_owner[terminal-fallback-zero-not-borrowed-early-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_refusal_before_creation[new-choice-stale-bound-generation-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_refusal_before_creation[divergent-action-add-combo-target-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_refusal_before_creation[pending-name-wrong-bound-target-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_known_failure_rolls_back_created_graph[mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_lost_successful_save_never_replayed[pp-save-mock]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_lost_successful_save_never_replayed[project-save-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[dynamic-text-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[project-font-image-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[text-image-collision-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[decoded-dltp-icon-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[label-and-status-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[static-commit-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[language-current-rows-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[pending-refusal-mock]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_lost_successful_save_is_not_replayed[mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[action-new-retains-old-items-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[action-old-selected-trigger-new-raw-trigger-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[action-cancel-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[trigger-new-explicit-write-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[trigger-cancel-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-zero-address-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-one-address-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-two-address-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-secondary-zero-address-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-no-selected-row-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-multiple-selected-rows-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-valid-getter-retains-old-labels-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-explicit-setter-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-explicit-refresh-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-cancel-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-noop-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[later-language-cannot-enter-earlier-view-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-and-action-old-binding-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_known_failure_restores_source[action-new-retains-old-items-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_known_failure_restores_source[language-explicit-setter-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[pp-save-action-new-retains-old-items-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[pp-save-language-explicit-setter-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[project-save-action-new-retains-old-items-mock]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[project-save-language-explicit-setter-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[ascii64-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[multibyte64-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[split63-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[astral64-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[old63-reserved-new62-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[unicode-blank-clear-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[u001c-is-not-dotnet-blank-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[bom-is-not-dotnet-blank-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[u180e-with-known-nonblank-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[malformed-exact-reuse-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[ordered-grid-control-widget-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_pending_scene_name_and_cache_injection_refuse_without_write[pending-name-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_pending_scene_name_and_cache_injection_refuse_without_write[cache-injection-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_lost_successful_save_not_replayed[pp-save-mock]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_lost_successful_save_not_replayed[project-save-mock]' \
		-q -p no:cacheprovider $(CGATE_INTEROP_PYTEST_EXTRA)

check-cmqtt-interop: compile
	test -x "$(CMQTTD_BIN)"
	CBUS_CMQTTD_BIN="$(CMQTTD_BIN)" $(PY) -m pytest \
		tests/test_cmqtt_interop.py tests/test_cmqtt_programming_methods_interop.py \
		tests/test_cmqtt_dali_commissioning_interop.py \
		tests/test_cmqtt_network_new_cli.py \
		tests/test_cmqtt_network_save_db_cli.py tests/test_cgate_file_upload.py \
		'tests/test_cgate_named_database_interop.py::test_public_named_safe_graph_separate_project_selected_sessions[daemon]' \
		'tests/test_cgate_named_database_interop.py::test_public_renamed_associated_level_cli_owner_and_wire[daemon]' \
		tests/test_cgate_named_database_interop.py::test_public_renamed_associated_level_cli_auth_and_restart \
		'tests/test_cgate_named_database_interop.py::test_public_associated_empty_tags_copy_after_reload[daemon]' \
		tests/test_cgate_named_database_interop.py::test_public_associated_empty_tags_copy_auth_stops_before_initializer \
		'tests/test_cgate_named_database_interop.py::test_public_associated_raw_level_value_literal_and_preservation[daemon]' \
		tests/test_cgate_named_database_interop.py::test_public_associated_raw_level_value_auth_and_restart \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_named_unit_preservation_and_lifecycle[daemon]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_numeric_unit_issued_identity[daemon]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_guards_are_read_only[daemon]' \
		'tests/test_cgate_barcode_database_interop.py::test_public_barcode_failure_is_exact_once_without_rollback[daemon]' \
		'tests/test_cgate_neopro_csv_interop.py::test_public_neopro_csv_project_network_selection_on_owned_backend[daemon]' \
		'tests/test_cgate_neopro_csv_interop.py::test_public_neopro_csv_late_unsupported_profile_refuses_atomically[daemon]' \
		'tests/test_cgate_neopro_csv_interop.py::test_public_neopro_csv_lost_snapshot_terminal_is_not_retried[daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[dimmer-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[relay-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[classic-key-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[coupler-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_preview_apply_family[input-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_stale_plan_and_alias_collision_refuse[daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay[lost-add-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay[lost-save-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_lost_receipt_retains_scaffold_without_replay[lost-set-daemon]' \
		'tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_declared_assignment_failure_keeps_reviewed_plan[daemon]' \
		tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_authentication_refuses_before_planning_or_writes \
		tests/test_cgate_toolkit_tweaker_interop.py::test_public_toolkit_tweaker_local_guards_never_connect \
		tests/test_cgate_barcode_database_interop.py::test_public_barcode_owned_login_denial_and_positive_apply \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[dimmer-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[relay-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[classic-key-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[coupler-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_replace_full_family_lifecycle[input-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[backup-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[add-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[set-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[pp-save-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[delete-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[readdress-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[project-save-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[close-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_lost_receipt_never_replays[load-daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_stale_plan_and_occupied_backup_no_write[daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_declared_assignment_refusal_preserves_source[daemon]' \
		'tests/test_cgate_toolkit_tweaker_lifecycle_interop.py::test_public_tweaker_lifecycle_authentication_redacts_and_stops_before_write' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_project_network_selection_on_owned_backend[daemon]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_late_refusal_on_owned_backend_is_atomic[bad-profile-daemon]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_late_refusal_on_owned_backend_is_atomic[channel-tail-daemon]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_late_refusal_on_owned_backend_is_atomic[secondary-owner-daemon]' \
		'tests/test_cgate_csv_families_interop.py::test_public_csv_families_lost_snapshot_is_not_retried[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_exact_action_creation[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_action_dialog_seed_and_save[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_dialog_cancel_preserves_metadata[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_trigger_then_action_dialog_order[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_lost_save_never_replays[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_dialog_name_guards_precede_mutation[daemon]' \
		'tests/test_cgate_edlt_scene_add_dialog_interop.py::test_public_scene_manager_restored_display_name_is_not_retained[daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[classic-prefix-no-inherited-hook-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[classic-prefix-no-inherited-hook-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-standard-pa6-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-standard-pa6-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[saturn-pcx-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[saturn-pcx-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[reflection-pcx-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[reflection-pcx-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-classic-model-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[neo-classic-model-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keye-shared-spec-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keye-shared-spec-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[dlt-source-retains-dlt-only-fields-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[dlt-source-retains-dlt-only-fields-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_unknown_receipt_never_replays[lost-create-save-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_unknown_receipt_never_replays[lost-replace-delete-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_stale_plan_and_source_firmware_refuse[daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_auth_stops_before_selection_or_write[daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-secondary-mask-removal-before-area-reshape-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-secondary-mask-removal-before-area-reshape-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-matching-application-object-removes-primary-too-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-matching-application-object-removes-primary-too-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-unused-secondary-keeps-lexical-application-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-unused-secondary-keeps-lexical-application-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-all-secondary-area-is-independent-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[neo-all-secondary-area-is-independent-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-forward-swap-decimal-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-forward-swap-decimal-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-catalogue-alias-forward-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-catalogue-alias-forward-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-reverse-swap-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-reverse-swap-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-alias-reverse-swap-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[dali-alias-reverse-swap-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-six-default-fields-and-polarity-aligned-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-six-default-fields-and-polarity-aligned-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-self-retains-fresh-learning-history-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-pir-self-retains-fresh-learning-history-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-self-no-st7-lux-rewrite-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-self-no-st7-lux-rewrite-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-to-multisensor-rename-and-fresh-unassigned-groups-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-light-level-to-multisensor-rename-and-fresh-unassigned-groups-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-multisensor-self-input-flag-overridden-and-join-reset-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_literal_and_lifecycle[older-multisensor-self-input-flag-overridden-and-join-reset-replace-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_lost_success_never_replays[create-PP SAVE_TO_SOURCE-daemon]' \
		'tests/test_cgate_toolkit_tweaker_remaining_interop.py::test_public_remaining_conversion_lost_success_never_replays[replace-DBDELETE-daemon]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_all_templates_and_ordered_selection[daemon]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_late_refusal_is_atomic[bad-profile-daemon]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_late_refusal_is_atomic[missing-application-daemon]' \
		'tests/test_cgate_csv_completion_interop.py::test_public_csv_completion_lost_snapshot_is_not_retried[daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[corridor-and-activation-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[cancel-repeat-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[preceding-enable-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[scene-interleave-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[initial-scene-getter-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[corridor-future-absence-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_history_one_save_and_full_preservation[application-switch-future-absence-daemon]' \
		'tests/test_cgate_edlt_parent_add_dialog_interop.py::test_public_parent_add_lost_save_success_is_not_replayed[daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keybir2-literal-keyb2-catalogue-alias-create-daemon]' \
		'tests/test_cgate_toolkit_tweaker_dlt_interop.py::test_public_dlt_tweaker_profile_create_and_replace[keybir2-literal-keyb2-catalogue-alias-replace-daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_all_literals_and_ordered_selection[daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_lost_snapshot_is_terminal_without_replay[daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[bad-profile-daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[missing-application-daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[missing-secondary-input-group-daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[missing-unused-temperature-group-daemon]' \
		'tests/test_cgate_csv_last_profiles_interop.py::test_public_csv_last_profiles_refusal_is_atomic[bad-fan-route-daemon]' \
		'tests/test_cgate_project_documentation_interop.py::test_public_database_document_snapshot_and_literal_bodies[daemon]' \
		'tests/test_cgate_project_documentation_interop.py::test_public_database_document_absent_network_is_atomic[daemon]' \
		'tests/test_cgate_project_documentation_interop.py::test_public_database_document_lost_snapshot_has_no_output_or_retry[daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[application-description-group-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[cancel-repeated-primary-secondary-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-application-group-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-cancelled-application-fresh-primary-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-initial-scene-before-action-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[reset-application-scene-corridor-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[preceding-and-future-owner-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_complete_history[expanded-reserved-confirmed-daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_reset_add_lost_save_is_not_replayed[daemon]' \
		'tests/test_cgate_edlt_application_reset_add_interop.py::test_public_application_add_guards_refuse_without_persistent_send[daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[default-repair-grid-before-widget-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[cancel-repeated-selected-list-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[absent-collection-chinese-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[zero-default-first-selected-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[allocated-widget-then-grid-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_parent_complete_history[language-parent-and-scene-add-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_lost_success_stops_without_replay[add-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_lost_success_stops_without_replay[set-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_lost_success_stops_without_replay[pp-save-daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_invalid_history_never_writes[daemon]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_authentication_stops_before_write[missing]' \
		'tests/test_cgate_edlt_static_language_add_interop.py::test_public_static_language_authentication_stops_before_write[wrong]' \
		'tests/test_cgate_project_documentation_sensors_interop.py::test_public_database_document_sensor_families_preserves_snapshot[daemon]' \
		'tests/test_cgate_project_documentation_wireless_interop.py::test_public_database_document_wireless_families_preserves_snapshot[daemon]' \
		'tests/test_cgate_project_documentation_l1_interop.py::test_public_database_document_l1_preserves_snapshot_and_literal_body[daemon]' \
		'tests/test_cgate_project_documentation_architectural_interop.py::test_public_database_document_architectural_families_preserves_snapshot[daemon]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_history_preview_apply_and_preservation[cell-transactions-daemon]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_history_preview_apply_and_preservation[cached-split-name-daemon]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_history_preview_apply_and_preservation[malformed-preserved-daemon]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_pending_cell_close_refuses_without_write[daemon]' \
		'tests/test_cgate_edlt_static_grid_editor_interop.py::test_public_static_grid_lost_successful_save_is_not_replayed[daemon]' \
		'tests/test_cgate_project_documentation_native_addresses_interop.py::test_public_native_report_exact_named_identity_and_physical_references[daemon-thermostat]' \
		'tests/test_cgate_project_documentation_native_addresses_interop.py::test_public_native_report_exact_named_identity_and_physical_references[daemon-wireless]' \
		'tests/test_cgate_project_documentation_st7_light_level_interop.py::test_public_database_document_st7_zero_timers_stored_scenes_and_direct_roles[daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[application-secondary-selector-one-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[trigger-callback-action-valid-in-both-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[action-selected-duplicate-name-exact-identity-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[null-current-retains-stale-action-binding-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[scene-two-rebinding-does-not-leak-first-labels-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selectors_preview_apply_fresh_complete_graph[label-selection-3-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_refusals_precede_database_writes[cache-injection-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_refusals_precede_database_writes[future-parent-action-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_prior_parent_add_visible_later_add_excluded[daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_lost_successful_save_never_replayed[pp-save-daemon]' \
		'tests/test_cgate_edlt_scene_selector_interop.py::test_public_selector_lost_successful_save_never_replayed[project-save-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[action-add-explicit-rebind-sees-new-generation-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[action-add-current-getter-view-new-old-binding-separate-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[canceled-action-add-keeps-bound-generation-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[trigger-add-then-explicit-callback-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[canceled-trigger-add-keeps-current-and-inventory-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[old42-choice-writes-current43-setter-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[old42-existing-choice-current43-existing-labels-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[trigger-callback-creates-missing-retained-action-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[missing-trigger-getter-requested-not-first-free-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[initial-loader-reserves-before-first-dialog-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[all-eight-loader-getters-reserve-before-first-dialog-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[later-initial-getter-keeps-earlier-label-generation-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_ordered_parent_add99_scene_add2_later_add100[daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_preview_apply_fresh_complete_graph[terminal-fallback-zero-not-borrowed-early-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_standalone_owner[action-add-explicit-rebind-sees-new-generation-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_standalone_owner[missing-trigger-getter-requested-not-first-free-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_standalone_owner[terminal-fallback-zero-not-borrowed-early-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_refusal_before_creation[new-choice-stale-bound-generation-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_refusal_before_creation[divergent-action-add-combo-target-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_refusal_before_creation[pending-name-wrong-bound-target-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_known_failure_rolls_back_created_graph[daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_lost_successful_save_never_replayed[pp-save-daemon]' \
		'tests/test_cgate_edlt_scene_inventory_interop.py::test_public_inventory_lost_successful_save_never_replayed[project-save-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[dynamic-text-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[project-font-image-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[text-image-collision-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[decoded-dltp-icon-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[label-and-status-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[static-commit-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[language-current-rows-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_and_lighting_callbacks[pending-refusal-daemon]' \
		'tests/test_cgate_edlt_lighting_images_interop.py::test_public_byte_images_lost_successful_save_is_not_replayed[daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[action-new-retains-old-items-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[action-old-selected-trigger-new-raw-trigger-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[action-cancel-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[trigger-new-explicit-write-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[trigger-cancel-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-zero-address-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-one-address-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-two-address-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-secondary-zero-address-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-no-selected-row-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[lighting-multiple-selected-rows-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-valid-getter-retains-old-labels-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-explicit-setter-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-explicit-refresh-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-cancel-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-noop-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[later-language-cannot-enter-earlier-view-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_preview_apply_fresh[language-and-action-old-binding-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_known_failure_restores_source[action-new-retains-old-items-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_known_failure_restores_source[language-explicit-setter-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[pp-save-action-new-retains-old-items-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[pp-save-language-explicit-setter-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[project-save-action-new-retains-old-items-daemon]' \
		'tests/test_cgate_edlt_scene_controls_language_interop.py::test_public_controls_language_lost_success_never_replayed[project-save-language-explicit-setter-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[ascii64-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[multibyte64-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[split63-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[astral64-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[old63-reserved-new62-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[unicode-blank-clear-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[u001c-is-not-dotnet-blank-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[bom-is-not-dotnet-blank-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[u180e-with-known-nonblank-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[malformed-exact-reuse-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_preview_apply_and_fresh_names[ordered-grid-control-widget-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_pending_scene_name_and_cache_injection_refuse_without_write[pending-name-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_pending_scene_name_and_cache_injection_refuse_without_write[cache-injection-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_lost_successful_save_not_replayed[pp-save-daemon]' \
		'tests/test_cgate_edlt_scene_name_control_interop.py::test_public_scene_name_control_lost_successful_save_not_replayed[project-save-daemon]' \
		-q -p no:cacheprovider $(CMQTT_INTEROP_PYTEST_EXTRA)

check-session-differential: build-interop
	$(PY) research/cgate_session_differential.py \
		--mock-bin "$(CGATE_MOCK_BIN)" \
		--output research/runtime/cgate-session-differential-mock.json
	PYTHONPATH=src:research $(PY) research/run_cgate_session_cmqttd_differential.py \
		--cmqttd-bin "$(CMQTTD_BIN)" \
		--output research/runtime/cgate-session-differential-cmqttd.json

check-tagged-session-differential: build-interop
	PYTHONPATH=src:. $(PY) research/cgate_tagged_session_differential.py \
		--mock-bin "$(CGATE_MOCK_BIN)" \
		--cmqttd-bin "$(CMQTTD_BIN)" \
		--output-dir research/runtime

check-dbsetxml-unit-differential: build-interop
	PYTHONPATH=src:. $(PY) research/cgate_dbsetxml_unit_differential.py \
		--mock-bin "$(CGATE_MOCK_BIN)" \
		--cmqttd-bin "$(CMQTTD_BIN)" \
		--output-dir research/runtime

check-dbgetxml-wire-interop: build-interop
	CBUS_CGATE_MOCK_BIN="$(CGATE_MOCK_BIN)" CBUS_CMQTTD_BIN="$(CMQTTD_BIN)" \
		PYTHONPATH=src:. $(PY) -m pytest \
		tests/test_cgate_dbgetxml_framing_interop.py -q -p no:cacheprovider

# Regenerate the source-bound parity receipts after a fingerprinted Rust or
# Python source changes. Every differential is a real re-run against freshly
# built cgate-mock and cmqttd on owned loopback ports; never edit hashes by
# hand. Order matters: the contract inventory hashes the Rust C-Gate sources,
# the physical applicability receipt hashes the inventory, and the register
# validates every receipt. The tagged and DBSETXML differentials fingerprint
# this Makefile and CI, so edit those first. A failed differential stops the
# target and leaves its failed receipt in the working tree for inspection.
# research/fixtures/cgate-session-differential-pre-fix.json is deliberately
# not regenerated: it is the retained red run of a pinned pre-fix binary
# (provenance pre-fix-binary) that tests expect to stay failed.
refresh-parity-receipts: build-interop
	$(PY) research/build_cgate_contract_inventory.py
	$(PY) research/cgate_session_differential.py \
		--mock-bin "$(CGATE_MOCK_BIN)" \
		--output research/fixtures/cgate-session-differential-fixed.json
	PYTHONPATH=src:research $(PY) research/run_cgate_session_cmqttd_differential.py \
		--cmqttd-bin "$(CMQTTD_BIN)" \
		--output research/fixtures/cgate-session-differential-cmqttd.json
	PYTHONPATH=src:. $(PY) research/cgate_tagged_session_differential.py \
		--mock-bin "$(CGATE_MOCK_BIN)" \
		--cmqttd-bin "$(CMQTTD_BIN)" \
		--output-dir research/runtime
	cp research/runtime/cgate-tagged-session-differential-mock.json \
		research/fixtures/cgate-tagged-session-differential-cgate-mock.json
	cp research/runtime/cgate-tagged-session-differential-cmqttd.json \
		research/fixtures/cgate-tagged-session-differential-cmqttd.json
	PYTHONPATH=src:. $(PY) research/cgate_dbsetxml_unit_differential.py \
		--mock-bin "$(CGATE_MOCK_BIN)" \
		--cmqttd-bin "$(CMQTTD_BIN)" \
		--output-dir research/fixtures
	PYTHONPATH=src $(PY) research/cgate_session_physical_applicability.py \
		--output research/fixtures/cgate-session-physical-applicability.json
	$(PY) research/build_parity_register.py
	$(MAKE) check-parity-register

check-interop: check-session-differential check-tagged-session-differential check-dbsetxml-unit-differential check-dbgetxml-wire-interop
	$(MAKE) check-cgate-interop
	$(MAKE) check-cmqtt-interop

check-wheel:
	@tmp=$$(mktemp -d); trap 'rm -rf "$$tmp"' EXIT; \
	project=$$(pwd -P); source_root="$$project/src"; \
	PYTHONPATH= $(WHEEL_PY) -m pip wheel --no-deps --wheel-dir "$$tmp/dist" .; \
	PYTHONPATH= $(WHEEL_PY) -m venv "$$tmp/venv"; \
	wheel=$$(find "$$tmp/dist" -maxdepth 1 -name 'cbus_toolkit_cli-*.whl' -print -quit); \
	test -n "$$wheel"; \
	PYTHONPATH= "$$tmp/venv/bin/python" -m pip install --force-reinstall "$$wheel[test,research,serial,usb]"; \
	package_path=$$(PYTHONPATH= "$$tmp/venv/bin/python" -c \
		'from pathlib import Path; import cbus_toolkit; print(Path(cbus_toolkit.__file__).resolve())'); \
	case "$$package_path" in "$$source_root"/*) echo "wheel gate imported source tree: $$package_path" >&2; exit 1;; esac; \
	case "$$package_path" in */site-packages/cbus_toolkit/__init__.py) :;; \
		*) echo "wheel gate did not import installed package: $$package_path" >&2; exit 1;; esac; \
	installed_target=$$(dirname "$$(dirname "$$package_path")"); \
	installed_console="$$tmp/venv/bin/cbus-toolkit"; test -x "$$installed_console"; \
	cd "$$tmp"; CBUS_OFFLINE_INSTALLED_TARGET="$$installed_target" \
		CBUS_OFFLINE_INSTALLED_CONSOLE="$$installed_console" \
		PYTHONPATH="$$project:$$project/tests" "$$tmp/venv/bin/python" -m pytest \
		"$$project/tests" -q -p no:cacheprovider $(PYTEST_EXTRA)

compile:
	$(PY) -m compileall -q src/cbus_toolkit

.PHONY: check check-offline check-native check-hardware build-interop \
	check-session-differential \
	check-tagged-session-differential \
	check-dbsetxml-unit-differential \
	check-cgate-interop check-cmqtt-interop check-interop check-wheel \
	check-parity-register refresh-parity-receipts coverage require-complete compile
