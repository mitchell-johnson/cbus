# Local verification battery for the Python C-Bus Toolkit CLI.
#
# This is not the release wheel gate: it runs everything provisionable on
# this machine and reports the completion gate status (expected nonzero while
# parity work remains). The fresh-wheel run with all 14 native gates is
# separate; see docs/implementation-status.md for the recipe and the
# remaining provisions (owned TEST_HOST server, Windows/mono, Toolkit EXE,
# CSV admission).
#
#   make check          full offline suite (operator-gated tests skip cleanly)
#   make check-native   owned-process C-Gate + original-instruction suites
#                       (needs CBUS_CGATE_JAVA/CBUS_CGATE_JAVAC/CBUS_LOCAL_CGATE_VENDOR)
#   make check-interop  Python-to-Rust interop against cgate-mock
#                       (rebuilds the mock first; the test itself skips when
#                       the binary predates the mock sources)
#   make coverage       print the completion ledger gate status
#   make compile        byte-compile the package

VENV = .venv
PY = $(VENV)/bin/python
RUST_DIR = ../rust
export PYTHONPATH = src:tests

check: compile
	$(VENV)/bin/python -m pytest tests/ -q -p no:cacheprovider

check-native: compile
	: $${CBUS_CGATE_JAVA:?Set CBUS_CGATE_JAVA to the owned JDK 11 java binary}
	: $${CBUS_CGATE_JAVAC:?Set CBUS_CGATE_JAVAC to the owned JDK 11 javac binary}
	: $${CBUS_LOCAL_CGATE_VENDOR:?Set CBUS_LOCAL_CGATE_VENDOR to the original cgate/app dir}
	$(VENV)/bin/python -m pytest tests/test_native_network_oracle.py \
		tests/test_pci_incoming.py tests/test_project_repair.py tests/test_local_cgate.py \
		tests/test_pci_routing.py tests/test_repositories.py \
		tests/test_native_thermostat_schedule_integration.py \
		tests/test_project_repair_native.py tests/test_pci_routed_identify_original.py \
		tests/test_pci_routed_recall_original.py -q -p no:cacheprovider

coverage:
	$(VENV)/bin/cbus-toolkit coverage --require-complete; \
	status=$$?; echo "coverage-gate-exit=$$status (1 while parity work remains)"; exit 0

check-interop: compile
	cd $(RUST_DIR) && cargo build -p cbus-cgate
	$(VENV)/bin/python -m pytest tests/test_rust_cgate_interop.py -q -p no:cacheprovider

compile:
	$(PY) -m compileall -q src/cbus_toolkit

.PHONY: check check-native check-interop coverage compile
