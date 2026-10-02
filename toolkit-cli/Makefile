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
	cd "$$tmp"; PYTHONPATH="$$project:$$project/tests" "$$tmp/venv/bin/python" -m pytest \
		"$$project/tests" -q -p no:cacheprovider $(PYTEST_EXTRA)

compile:
	$(PY) -m compileall -q src/cbus_toolkit

.PHONY: check check-offline check-native check-hardware build-interop \
	check-session-differential \
	check-tagged-session-differential \
	check-dbsetxml-unit-differential \
	check-cgate-interop check-cmqtt-interop check-interop check-wheel \
	check-parity-register refresh-parity-receipts coverage require-complete compile
