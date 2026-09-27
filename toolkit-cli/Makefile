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
#   make check-offline  source-tree suite without the two Rust interop modules
#   make check-native   strict owned-process C-Gate + original-instruction gate
#                       (fails on missing provision or any skipped test)
#   make check-hardware strict private-manifest hardware gate
#   make check-interop  Python-to-Rust interop against cgate-mock and cmqttd
#                       (rebuilds both binaries before exercising their servers)
#   make check-wheel    build a fresh wheel, install it with every supported
#                       extra in an isolated Python 3.13 venv, and run the
#                       full offline suite without importing from src/
#   make check-parity-register  verify generated scope/evidence accounting
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

check-offline: compile
	$(PY) -m pytest tests/ -q -p no:cacheprovider \
		--ignore=tests/test_rust_cgate_interop.py \
		--ignore=tests/test_cmqtt_interop.py \
		--ignore=tests/test_cmqtt_programming_methods_interop.py \
		$(PYTEST_EXTRA)

check-parity-register:
	$(PY) research/build_parity_register.py --check

check-native: compile
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
		tests/test_rust_cgate_interop.py -q -p no:cacheprovider $(CGATE_INTEROP_PYTEST_EXTRA)

check-cmqtt-interop: compile
	test -x "$(CMQTTD_BIN)"
	CBUS_CMQTTD_BIN="$(CMQTTD_BIN)" $(PY) -m pytest \
		tests/test_cmqtt_interop.py tests/test_cmqtt_programming_methods_interop.py \
		-q -p no:cacheprovider $(CMQTT_INTEROP_PYTEST_EXTRA)

check-interop: build-interop
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
	check-cgate-interop check-cmqtt-interop check-interop check-wheel \
	check-parity-register coverage require-complete compile
