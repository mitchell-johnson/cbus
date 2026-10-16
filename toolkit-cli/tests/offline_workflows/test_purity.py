"""Independent evidence that the bounded public models perform no external work."""

from __future__ import annotations

import ast
import builtins
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest


PACKAGE = "cbus_toolkit.offline_workflows"
SCENARIOS = (
    "copy-paste", "neo-editor", "catalogue-groups", "discovery-session", "transfer-restore"
)
MODULES = (
    "copy_paste", "neo_editor", "catalogue_groups", "discovery_session", "transfer_restore", "demo"
)
SOURCE = Path(__file__).resolve().parents[2] / "src" / "cbus_toolkit" / "offline_workflows"


@pytest.mark.parametrize("module", MODULES)
def test_models_have_no_direct_external_adapters_or_io_calls(module):
    """Keep a future executor from silently appearing in these offline models.

    Existing planner imports can transitively define transport-capable classes;
    the independent runtime test below guards their invocation as well.
    """
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    forbidden_modules = {"socket", "serial", "subprocess", "ctypes", "urllib", "requests", "httpx", "winreg"}
    forbidden_adapters = {"CGateClient", "NativeProjects", "NativeDatabase", "Programmer", "ProgrammingSession", "UnitSpecStore"}
    file_methods = {"read_bytes", "read_text", "write_bytes", "write_text", "mkdir", "unlink"}
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] in forbidden_modules:
                    violations.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".", 1)[0] in forbidden_modules:
                violations.append((node.lineno, f"from {node.module}"))
            for alias in node.names:
                if alias.name in forbidden_adapters:
                    violations.append((node.lineno, f"adapter {alias.name}"))
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name) and function.id in {"open", *forbidden_adapters}:
                violations.append((node.lineno, f"call {function.id}"))
            elif isinstance(function, ast.Attribute) and function.attr in file_methods:
                violations.append((node.lineno, f"call .{function.attr}"))
    assert violations == []


def _install_external_work_tripwires(monkeypatch):
    attempts = []

    def denied(*args, **kwargs):
        attempts.append("external work attempted")
        raise AssertionError("offline workflow attempted filesystem, transport, process, or backend work")

    monkeypatch.setattr(builtins, "open", denied)
    for name in ("open", "rename", "replace", "remove", "unlink", "mkdir", "makedirs", "rmdir", "system"):
        monkeypatch.setattr(os, name, denied)
    for name in ("open", "read_bytes", "read_text", "write_bytes", "write_text", "rename", "replace", "mkdir", "unlink", "rmdir", "touch"):
        monkeypatch.setattr(Path, name, denied)
    for name in ("__init__", "connect", "connect_ex", "bind", "send", "sendall", "sendto", "listen", "accept"):
        monkeypatch.setattr(socket.socket, name, denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, denied)
    for module_name, class_names in (
        ("cbus_toolkit.cgate", ("CGateClient",)),
        ("cbus_toolkit.native", ("NativeProjects", "NativeDatabase")),
        ("cbus_toolkit.programming", ("Programmer", "ProgrammingSession")),
        ("cbus_toolkit.unitspec", ("UnitSpecStore",)),
    ):
        module = sys.modules[module_name]
        for class_name in class_names:
            monkeypatch.setattr(getattr(module, class_name), "__init__", denied)
    return attempts


def _preload_existing_definitions():
    # Definition imports are deliberately outside the guarded workflow lifetime.
    # No instances are created, no private inputs are read, and no adapters run.
    for module in ("cbus_toolkit.cgate", "cbus_toolkit.native", "cbus_toolkit.programming", "cbus_toolkit.unitspec"):
        importlib.import_module(module)


def test_import_and_all_synthetic_demos_perform_zero_external_work(monkeypatch):
    _preload_existing_definitions()
    # Force the new package modules through their import-time code under guards.
    for name in tuple(sys.modules):
        if name == PACKAGE or name.startswith(PACKAGE + "."):
            monkeypatch.delitem(sys.modules, name)
    with monkeypatch.context() as guarded:
        attempts = _install_external_work_tripwires(guarded)
        modules = [importlib.import_module(f"{PACKAGE}.{name}") for name in MODULES]
        demo = modules[-1]
        all_result = demo.run_demo("all")
        individual_results = [demo.run_demo(name) for name in SCENARIOS]
        serialized = json.dumps(all_result, sort_keys=True, ensure_ascii=False)
        again = json.dumps(demo.run_demo("all"), sort_keys=True, ensure_ascii=False)
    assert attempts == []
    assert serialized == again
    assert all_result
    assert all(isinstance(result, dict) and result for result in individual_results)


def test_demo_returns_defensive_independent_results():
    demo = importlib.import_module(f"{PACKAGE}.demo")
    first = demo.run_demo("all")
    original = json.dumps(first, sort_keys=True, ensure_ascii=False)
    first.clear()
    fresh = demo.run_demo("all")
    assert json.dumps(fresh, sort_keys=True, ensure_ascii=False) == original
