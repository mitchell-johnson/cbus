"""Owned native C-Gate for pytest selections that name a disposable test host.

Many native tests accept a disposable C-Gate through ``CBUS_CGATE_TEST_HOST``.
When ``CBUS_NATIVE_SERVICE_BACKEND=local`` explicitly selects the owned
backend, this plugin never uses an externally supplied host.  Before the first
test module that reads ``CBUS_CGATE_TEST_HOST`` is imported, it starts one
owned loopback ``research.local_cgate.LocalCGate`` from
``CBUS_LOCAL_CGATE_VENDOR`` and ``CBUS_CGATE_JAVA`` and publishes its
ephemeral command port to that module.  Nothing is started without the
explicit local selection, and nothing is adopted from an existing process.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


HOST_VARIABLES = ("CBUS_CGATE_TEST_HOST", "CBUS_CGATE_TEST_PORT")
# The owned process listens on loopback, not in a container: tests that point
# a C-Gate CNI at a synthetic simulator must use loopback in both directions.
LOOPBACK_DEFAULTS = {"CBUS_CGATE_SIMULATOR_HOST": "127.0.0.1",
                     "CBUS_CGATE_SIMULATOR_BIND": "127.0.0.1"}

_service = None
_start_error: BaseException | None = None


def _owned_backend_selected() -> bool:
    return os.environ.get("CBUS_NATIVE_SERVICE_BACKEND") == "local"


def _owned_backend_provisioned() -> bool:
    return bool(os.environ.get("CBUS_LOCAL_CGATE_VENDOR") and os.environ.get("CBUS_CGATE_JAVA"))


def _needs_test_host(path: Path) -> bool:
    if not (path.suffix == ".py" and path.name.startswith("test_")):
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    # A module importing another test module may read that module's host.
    return any(marker in text for marker in ("CBUS_CGATE_TEST_HOST", "from tests.test_", "import tests.test_"))


def _start_owned_service() -> None:
    global _service, _start_error
    if _service is not None or _start_error is not None:
        return
    from research.local_cgate import LocalCGate
    service = LocalCGate(os.environ["CBUS_LOCAL_CGATE_VENDOR"], java=os.environ["CBUS_CGATE_JAVA"])
    try:
        # Match the disposable host these tests were written for: loopback
        # clients may create, delete and program disposable projects.
        (service.work / "config/access.txt").write_text("interface 127.0.0.1 Clipsal\n")
        service.start()
    except BaseException as error:
        _start_error = error
        raise
    _service = service
    os.environ["CBUS_CGATE_TEST_HOST"] = "127.0.0.1"
    os.environ["CBUS_CGATE_TEST_PORT"] = str(service.port)
    for name, value in LOOPBACK_DEFAULTS.items():
        os.environ.setdefault(name, value)
    catalogue = Path(os.environ["CBUS_LOCAL_CGATE_VENDOR"]) / "unitspec" / "cbusunits.xml"
    if catalogue.is_file():
        # The catalogue of the service under test, not a separately chosen one.
        os.environ.setdefault("CBUS_CATALOG_PATH", str(catalogue))


def _stop_owned_service() -> None:
    global _service
    service, _service = _service, None
    if service is not None:
        for name in HOST_VARIABLES:
            os.environ.pop(name, None)
        service.close()


def pytest_configure(config):
    if _owned_backend_selected() and any(os.environ.get(name) for name in HOST_VARIABLES):
        raise pytest.UsageError(
            "CBUS_NATIVE_SERVICE_BACKEND=local owns the C-Gate test host; "
            "unset " + ", ".join(HOST_VARIABLES))


def pytest_collect_file(file_path, parent):
    if (_owned_backend_selected() and _owned_backend_provisioned()
            and _needs_test_host(Path(file_path))):
        _start_owned_service()
    return None


@pytest.fixture(scope="session", autouse=True)
def _owned_cgate_test_host():
    """Stop the owned service inside the session so cleanup failures are test errors."""
    yield
    _stop_owned_service()


def pytest_unconfigure(config):
    _stop_owned_service()
